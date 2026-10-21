# -*- coding: utf-8 -*-
"""Палетки истощения и заводнения объекта — порт листа «PVT_MBE_Waterflood».

Лист объекта RE Tools кроме матбаланса (object_builder.mbe_table, E3:Y38)
содержит модель вытеснения и макрос FDP_Functions, который строит палетки
для расчёта добычи и РИГИС:

1. По давлению (строки 3–38, сетка E) при текущем Swi (D4):
   So = Get_So(Np, 100, Boi, Bo, Swi), Sg = Get_Sg (0 при P ≥ Pb), ОФП Бейкера
   Kro/Krw, вязкость смеси BG = Get_mu_from_Krelative(μw, μo, Krw, Kro) и
   обводнённость BH = Get_fw_from_Krealtive(μw, μo, Bo, Bw, Krw, Kro).
   Np (столбец M) — решение матбаланса при базовом Swi: макрос FDP_Functions
   его не пересчитывает при переборе Swi.
2. Характеристика вытеснения (Z:AX) — две единицы потока (Flow Unit 1, 2:
   h, k, φ из D11:D16). На каждом шаге (строка) «депрессия» AY растёт по
   графику книги; дебиты нефти и воды единицы потока
       Qн = k·Kro_adapt·dP / (18,41·Boi·μoi·6,5),  Qв — то же с Krw_adapt, Bwi, μwi;
   накопленная нефть — Qн предыдущего шага × 365/1000 (не больше подвижных
   запасов Nm), Sw = Swi + (1 − Swi − Sorw)·Np/Nm (округление до 0,001, как в
   книге). ОФП смеси — среднее по проницаемости единиц, отбор от НПЗ —
   (Np1 + Np2)/(Nm1 + Nm2). ОФП «адаптированы» на безводный период:
   Kro не меняется первые 20 % (AZ36), Krw — 35 % (BA36) отбора подвижных.
3. FDP_Functions перебирает 12 значений Swi (от 1 − Sorw − 0,001 до Swl) и
   собирает палетки (строки — сетка, столбцы — Swi):
   - Mu (P × Sw) — BG; Sg (P × Sw) — U; %обв (P × Sw) — BH;
   - Kro Mix и Krw Mix (%НПЗ × Sw) — интерполяция AF/AG по отбору от НПЗ
     на сетке 0, 1/35 … 1;
   - после цикла (Swi — базовое): %обв Mix (%НПЗ × Sw) по Kro/Krw Mix при
     начальных PVT и палетка «доля НПЗ при предельной обводнённости»
     (%обв × Sw) — обратная интерполяция (не ниже 0).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from . import rigis_physics as ph
from .interp import Curve, Grid2D
from .object_builder import MPA_ATMA, _cpvt, c_gas_1atm, c_wat_1atm, pressure_grid, pvt_json

# «депрессия» шагов модели вытеснения, AY3:AY38 книги
DP_SCHEDULE = [5, 10, 30, 50, 80, 110, 150, 200, 250, 300, 350, 400, 450, 500, 500, 500, 500, 500,
               762.7119654195088, 1163.4590843881804, 1774.768329877783, 2707.274082090767, 4129.7406721614925,
               6299.605249474353, 9609.56860238728, 14658.665911120814, 22360.67977499783, 34109.51603860972,
               52031.47203463257, 79370.05259840966, 121072.97762556569, 184687.6174479749, 281726.9113847827,
               429752.97258771094, 655555.4687344988, 999999.9999999995]
ADAPT_KRO = 0.2       # AZ36: доля отбора подвижных запасов без влияния на Kro
ADAPT_KRW = 0.35      # BA36: то же для Krw (безводный период)
def _npz_grid() -> list[float]:
    """Q70:Q105: 0, 1/35, затем +1/35 накопительно (как формулы листа), последний — 1."""
    out = [0.0, 1 / 35]
    for _ in range(33):
        out.append(out[-1] + 1 / 35)
    return out + [1.0]


NPZ_GRID = _npz_grid()
WC_GRID = [0.0] + [5.0 * k for k in range(1, 18)] + [90.0] + [92.0 + 0.5 * k for k in range(17)]  # AE109:AE144


def xl_round(x: float, digits: int) -> float:
    """ROUND Excel: половина — от нуля."""
    q = Decimal(1).scaleb(-digits)
    return float(Decimal(repr(x)).quantize(q, rounding=ROUND_HALF_UP))


# --- ОФП нефть-вода (b_RG_3Ph_Model) ------------------------------------------

def krw_ow(fw, m1, swc, sor, sw) -> float:
    if sw < swc:
        return 0.0
    sd = 1.0 if (1 - sor - swc) == 0 else (sw - swc) / (1 - sor - swc)
    return fw * sd ** m1


def kro_ow(fo, m2, swl, sor, sw) -> float:
    if sw == 1:
        return 0.0
    sd = 1.0 if (1 - sor - swl) == 0 else (sw - swl) / (1 - sor - swl)
    return fo * (1 - sd) ** m2


def krw_ow_adapt(final_water, exw_ow, swc, adapt, sor, swl, swi, sw) -> float:
    """Get_Krw_ow_adapt — дословно (в ветке Swi > Swc знаменатель условия — с Swl)."""
    if sw <= swc:
        return 0.0
    if swi > swc:
        if (sw - swi - (1 - sor - swi) * adapt) / (1 - sor - swl) <= 0:
            sd = (swi - swc) / (1 - sor - swc)
        else:
            sd = (sw - swc - (1 - sor - swc) * adapt) / (1 - sor - swc - (1 - sor - swc) * adapt)
    else:
        if (sw - swi - (1 - sor - swi) * adapt) <= 0:
            sd = 0.0
        else:
            sd = (sw - swi - (1 - sor - swi) * adapt) / (1 - sor - swi - (1 - sor - swi) * adapt)
    return final_water * sd ** exw_ow


def kro_ow_adapt(final_oil, exo_ow, swl, swi, sor, sw, adapt) -> float:
    """Get_Kro_ow_adapt — дословно (Sw = 1 в VBA ни на что не влияет)."""
    if (1 - sor - swl) <= 0:
        sd = 1.0
    elif (sw - swi - (1 - sor - swi) * adapt) / (1 - sor - swl) <= 0:
        sd = (swi - swl) / (1 - sor - swl)
    else:
        sd = (sw - swl - (1 - sor - swl) * adapt) / (1 - sor - swl - (1 - sor - swl) * adapt)
    return final_oil * (1 - sd) ** exo_ow


def mu_liq(mu_w, mu_o, sw, fw, m1, fo, m2, swc, sor) -> float:
    """Get_Mu_liq (BA3:BA19)."""
    krw = krw_ow(fw, m1, swc, sor, sw)
    kro = kro_ow(fo, m2, swc, sor, sw)
    den = kro * mu_w + krw * mu_o
    return 0.0 if den == 0 else mu_w * mu_o / den


# --- PVT по сетке давлений ----------------------------------------------------

@dataclass
class PvtRow:
    p: float
    rs: float
    bo: float
    bg: float
    mu_o: float
    mu_g: float
    mu_w: float
    bw: float
    co: float
    cw: float
    cg: float


def pvt_rows(params: dict, grid: list | None = None) -> list[PvtRow]:
    """F:K и BB:BF листа по сетке давлений E3:E38."""
    cfg = pvt_json(params)
    pvt = _cpvt(cfg)
    t = params["t_C"]
    out = []
    for p in grid or pressure_grid(params["depth"], params["pb"]):
        x = pvt.calc(p, t)
        out.append(PvtRow(p, x["rs"], x["bo"], x["bg"], x["mu_oil"], x["mu_gas"],
                          ph.mu_water_cP(p, t, cfg["gamma_wat"]), ph.bw_m3m3(p, t), x["co_1MPa"] / MPA_ATMA,
                          c_wat_1atm(p, t, cfg["gamma_wat"]), c_gas_1atm(p, t, cfg["gamma_gas"])))
    return out


@dataclass
class InitialPvt:
    """BA20:BA27: PVT при начальном давлении."""
    boi: float
    bwi: float
    bgi: float
    muoi: float
    muwi: float
    mugi: float
    cwi: float


def initial_pvt(params: dict) -> InitialPvt:
    r = pvt_rows(params, [params["p_init"]])[0]
    return InitialPvt(r.bo, r.bw, r.bg, r.mu_o, r.mu_w, r.mu_g, r.cw)


# --- столбцы листа при заданном Swi --------------------------------------------

def _safe(fn, default):
    """IFERROR листа."""
    try:
        v = fn()
    except (ZeroDivisionError, ValueError, OverflowError):
        return default
    return default if isinstance(v, complex) else v


@dataclass
class DepletionRow:
    p: float
    so: float     # T
    sg: float     # U
    kro: float    # W
    krw: float    # X
    mu: float     # BG — вязкость смеси по Бейкеру
    wc: float     # BH — обводнённость по Бейкеру, %


def depletion_rows(params: dict, swi: float, np_pct: list, pvt: list[PvtRow], init: InitialPvt) -> list[DepletionRow]:
    """T, U, W, X, BG, BH при Swi (D4) и заданном столбце Np, % (M3:M38)."""
    q = params
    out = []
    for r, np_ in zip(pvt, np_pct):
        so = (1 - swi) * (1 - np_ / 100) * (r.bo / init.boi)
        sg = 0.0 if r.p >= q["pb"] else 1 - swi - so
        kro = ph.kro_baker(swi, q["swl"], sg, q["sorg_og"], q["sorw_ow"], q["end_oil"], q["exo_ow"], q["exo_og"])
        krw = ph.krw_baker(swi, q["swcr_ow"], so, sg, q["sorg_og"], q["end_water"], q["sorw_ow"], q["exw_ow"], q["swl"])
        # отрицательное основание в дробной степени: в VBA — ошибка, на листе IFERROR → 0 и 100
        bad = isinstance(kro, complex) or isinstance(krw, complex)
        mu = 0.0 if bad else _safe(lambda: ph.mu_from_kr(r.mu_w, r.mu_o, krw, kro), 0.0)
        wc = 100.0 if bad else _safe(lambda: ph.fw_from_kr(r.mu_w, r.mu_o, r.bo, r.bw, krw, kro), 100.0)
        out.append(DepletionRow(r.p, so, sg, kro, krw, mu, wc))
    return out


@dataclass
class FloodRow:
    dp: float
    npz: float       # AC — отбор от НПЗ, д. ед.
    ngz: float       # AD — отбор от НГЗ
    sw: float        # AE — средняя Sw
    kro_mix: float   # AF
    krw_mix: float   # AG
    wc: float        # AH, %
    sw1: float       # AN
    sw2: float       # AV
    np1: float       # AO, тыс. м³
    np2: float       # AW


def flood_rows(params: dict, swi: float, init: InitialPvt, adapt_kro: float = ADAPT_KRO,
               adapt_krw: float = ADAPT_KRW, schedule: list = DP_SCHEDULE) -> list[FloodRow]:
    """Характеристика вытеснения двух единиц потока (Z:AX) при Swi."""
    q = params
    sorw, swl, swcr = q["sorw_ow"], q["swl"], q["swcr_ow"]
    k1, k2 = q["k_fu1"], q["k_fu2"]
    n1 = ph.get_n(q["phi_fu1"], init.boi, 1, 100, swi, q["heff_fu1"])
    nm1 = ph.get_n(q["phi_fu1"], init.boi, 1, 100, swi + sorw, q["heff_fu1"])
    n2 = ph.get_n(q["phi_fu2"], init.boi, 1, 100, swi, q["heff_fu2"])
    nm2 = ph.get_n(q["phi_fu2"], init.boi, 1, 100, swi + sorw, q["heff_fu2"])
    oil_den = 18.41 * init.boi * init.muoi * 6.5

    def kr(sw):
        return (kro_ow_adapt(q["end_oil"], q["exo_ow"], swl, swi, sorw, sw, adapt_kro),
                krw_ow_adapt(q["end_water"], q["exw_ow"], swcr, adapt_krw, sorw, swl, swi, sw))

    out: list[FloodRow] = []
    np1 = np2 = 0.0
    qo1 = qo2 = 0.0
    for i, dp in enumerate(schedule):
        if i > 0:
            v1, v2 = qo1 * 365 / 1000 + np1, qo2 * 365 / 1000 + np2
            np1 = nm1 if v1 > nm1 else v1
            np2 = nm2 if v2 > nm2 else v2
        if i == 0:
            sw1 = swi
        elif i == 1:
            sw1 = swi + (1 - swi - sorw) * (np1 / nm1)
        else:
            sw1 = xl_round(swi + (1 - swi - sorw) * (np1 / nm1), 3)
        sw2 = swi if i == 0 else xl_round(swi + (1 - swi - sorw) * (np2 / nm2), 3)
        kro1, krw1 = kr(sw1)
        kro2, krw2 = kr(sw2)
        qo1 = k1 * kro1 * dp / oil_den
        qo2 = k2 * kro2 * dp / oil_den
        kro_m = (kro1 * k1 + k2 * kro2) / (k1 + k2)
        krw_m = (krw1 * k1 + k2 * krw2) / (k1 + k2)
        out.append(FloodRow(dp, (np1 + np2) / (nm1 + nm2), (np1 + np2) / (n1 + n2),
                            (sw1 * nm1 + sw2 * nm2) / (nm1 + nm2), kro_m, krw_m,
                            ph.fw_from_kr(init.muwi, init.muoi, init.boi, init.bwi, krw_m, kro_m), sw1, sw2, np1, np2))
    return out


# --- палетки (FDP_Functions) ----------------------------------------------------

@dataclass
class FdpPallets:
    """Палетки объекта: оси x — Swi (12 значений), y — сетка; f[y][x]."""
    sw: list
    p: list
    npz_grid: list
    wc_grid: list
    mu: list          # D70:O105 — вязкость смеси, сП (P × Sw)
    sg: list          # D109:O144 — газонасыщенность (P × Sw)
    wc: list          # D148:O183 — обводнённость по Бейкеру, % (P × Sw)
    kro_mix: list     # R70:AC105 (%НПЗ × Sw)
    krw_mix: list     # AF70:AQ105
    wc_mix: list      # R109:AC144 — обводнённость, % (%НПЗ × Sw)
    npz: list         # AF109:AQ144 — доля НПЗ при предельной обводнённости (%обв × Sw)

    def grid(self, name: str) -> Grid2D:
        """2D-палетка для crv_interpolation_2D (x — Sw, y — сетка листа)."""
        y = {"mu": self.p, "sg": self.p, "wc": self.p, "kro_mix": self.npz_grid, "krw_mix": self.npz_grid,
             "wc_mix": self.npz_grid, "npz": self.wc_grid}[name]
        return Grid2D(self.sw, y, getattr(self, name))


def sw_axis(params: dict) -> list[float]:
    """D69:O69: от 1 − Sorw − 0,001 до Swl, 11 равных шагов."""
    d = 1 - params["sorw_ow"] - 0.001
    o = params["swl"]
    out = [d]
    for _ in range(10):
        out.append(out[-1] - (d - o) / 12)
    return out + [o]


def fdp_pallets(params: dict, np_pct: list | None = None) -> FdpPallets:
    """Все палетки объекта (порт макроса FDP_Functions).

    np_pct — столбец M (Np, % НГЗ) при базовом Swi; по умолчанию — решение
    матбаланса object_builder.mbe_table.
    """
    if np_pct is None:
        from .object_builder import mbe_table
        np_pct = [r.np_pct for r in mbe_table(params)]
    pvt = pvt_rows(params)
    init = initial_pvt(params)
    sws = sw_axis(params)
    cols = {k: [] for k in ("mu", "sg", "wc", "kro_mix", "krw_mix")}
    for swi in sws:
        dep = depletion_rows(params, swi, np_pct, pvt, init)
        cols["mu"].append([d.mu for d in dep])
        cols["sg"].append([d.sg for d in dep])
        cols["wc"].append([d.wc for d in dep])
        fl = flood_rows(params, swi, init)
        kro_c = Curve([r.npz for r in fl], [r.kro_mix for r in fl])
        krw_c = Curve([r.npz for r in fl], [r.krw_mix for r in fl])
        cols["kro_mix"].append([kro_c(x) for x in NPZ_GRID])
        cols["krw_mix"].append([krw_c(x) for x in NPZ_GRID])
    t = {k: [list(r) for r in zip(*v)] for k, v in cols.items()}          # столбцы → строки
    wc_mix = [[ph.fw_from_kr(init.muwi, init.muoi, init.boi, init.bwi, w, o) for w, o in zip(rw, ro)]
              for rw, ro in zip(t["krw_mix"], t["kro_mix"])]
    npz_cols = []
    for j in range(len(sws)):
        c = Curve([wc_mix[i][j] for i in range(len(NPZ_GRID))], NPZ_GRID)
        npz_cols.append([max(c(w), 0.0) for w in WC_GRID])
    npz = [list(r) for r in zip(*npz_cols)]
    return FdpPallets(sws, [r.p for r in pvt], list(NPZ_GRID), list(WC_GRID), t["mu"], t["sg"], t["wc"],
                      t["kro_mix"], t["krw_mix"], wc_mix, npz)
