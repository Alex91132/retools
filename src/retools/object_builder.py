# -*- coding: utf-8 -*-
"""Построение объекта разработки и палеток секций ГС из параметров — без книги.

1. Таблица матбаланса листа «PVT_MBE_Waterflood» (E3:Y38). Сетка давлений —
   как в книге: от D6/10 + 250 до Pb за 14 шагов, от Pb до 10 атм за 21 шаг.
   В каждой строке (сверху вниз, как макрос GoalSeek_Np) ищется накопленный
   отбор Np (% НГЗ), при котором MBE_LHS = MBE_RHS·100; газовый фактор —
   по ОФП Бейкера (Krg — по насыщенностям предыдущей строки, как в книге),
   накопленный газ — трапецией. Отсюда So, Sg (ниже Pb), Ct.
2. Палетки коэффициента секции ГС («Нормировка Jd ГС по секциям», блоки DA:GW):
   Jd(L) = Get_Jd(…Get_J_obsolete(L)…) для мощностей 1, 5, 15, 50 м; клетка
   палетки = Jd(L общ) / ((L общ / L секции) · Jd(L секции)), 1 — если секция
   длиннее общей длины (формула листа).

Палетка «доля НПЗ при предельной обводнённости» (AF108:AQ144) и остальные
палетки листа строятся портом макроса FDP_Functions — модуль waterflood.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass

from scipy.optimize import brentq

from . import rigis_physics as ph
from .cpvt import CPVT, z_gas
from .field_object import FieldObject, JdSectionPallets, JD_THICKNESS
from .interp import Curve, Grid2D

T_K_MIN = 273
ATMA_MPA = 0.101325
MPA_ATMA = 1 / ATMA_MPA

# сетка длин палеток Jd книги (C4:CX4 = DA5:DA104), м — 100 узлов
JD_L_GRID = [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9,
             0.95, 1.0, 1.05, 1.1, 1.15, 1.2, 1.25, 1.3, 1.35, 1.4, 1.45, 1.5, 1.55, 1.6, 1.65, 1.7, 1.75, 1.85, 1.95,
             2.0, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 3.0, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 4.0,
             4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 5.0, 5.2, 5.4, 5.6, 5.9, 6.2, 6.5, 6.8, 7.2, 7.6, 8.1, 8.6,
             9.1, 10.0, 12.5, 15.0, 17.5, 20.0, 30.0, 50.0, 75.0, 100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 800.0,
             1000.0, 1200.0, 1400.0, 1700.0, 2000.0]


def _cpvt(cfg: dict) -> CPVT:
    return CPVT(gamma_gas=cfg["gamma_gas"], gamma_oil=cfg["gamma_oil"], gamma_wat=cfg["gamma_wat"],
                rsb_m3m3=cfg["rsb_m3m3"], pb_atma=cfg["pb_atma"], bob_m3m3=cfg["bob_m3m3"],
                muob_cP=cfg["muob_cP"], corr=cfg.get("PVT_corr_set", 1), t_res_C=cfg["t_res_C"])


def pvt_json(params: dict) -> dict:
    """encode_PVT (D18): параметры флюида листа объекта."""
    return {"gamma_gas": params["gamma_gas"], "gamma_oil": params["rho_oil"], "gamma_wat": params["gamma_wat"],
            "rsb_m3m3": params["rsi"], "pb_atma": params["pb"], "t_res_C": params["t_C"], "bob_m3m3": params["bob"],
            "muob_cP": params["muob"], "PVT_corr_set": params.get("corr_set", 1)}


def c_wat_1atm(p_atma: float, t_C: float, gamma_w: float) -> float:
    """unf_pvt_compressibility_wat_1atma (Unifloc)."""
    f = 1.8 * (t_C + T_K_MIN) - 460
    psi = p_atma * ATMA_MPA * 145.04
    return 0.1 * 145.04 / (7.033 * psi + 0.5415 * ph._sal_ppm(gamma_w) - 537 * f + 403300)


def c_gas_1atm(p_atma: float, t_C: float, gamma_g: float) -> float:
    """compressibility_gas_1atm: (1/p − dZ/dp / z)·0.101325, z — Kareem."""
    t_k = t_C + T_K_MIN
    p = p_atma * ATMA_MPA
    z1 = z_gas(t_k, p, gamma_g)
    z2 = z_gas(t_k, p + 0.01, gamma_g)
    return (1 / p - 1 / z1 * (z2 - z1) / 0.01) * ATMA_MPA


def pressure_grid(depth: float, pb: float) -> list[float]:
    """E3:E38: 15 точек от depth/10 + 250 до Pb, затем 21 шаг до 10 атм."""
    e3 = depth / 10 + 250
    upper = [e3]
    for _ in range(13):
        upper.append(upper[-1] - (e3 - pb) / 14)
    lower = [pb]
    for _ in range(20):
        lower.append(lower[-1] - (pb - 10) / 21)
    return upper + lower + [10.0]


def _krg_og(final_gas, exg, sgcr, sorg, sg, swl):
    return 0.0 if sg < sgcr else ((sg - sgcr) / (1 - sorg - sgcr - swl)) ** exg * final_gas


@dataclass
class MbeRow:
    p: float
    rs: float
    bo: float
    bg: float
    ct: float
    mu_o: float
    mu_g: float
    np_pct: float
    gp: float
    rp: float
    gor: float
    so: float
    sg: float
    kro: float
    krg: float


def mbe_table(params: dict) -> list[MbeRow]:
    """Таблица матбаланса объекта (порт E3:Y38 + GoalSeek_Np)."""
    cfg = pvt_json(params)
    pvt = _cpvt(cfg)
    t = params["t_C"]
    pi, pb, swl, swi = params["p_init"], params["pb"], params["swl"], params["swi"]
    m_cap, cf = params["gas_cap_m"], params["c_f"]
    sorw, sorg, swcr, sgcr = params["sorw_ow"], params["sorg_og"], params["swcr_ow"], params["sgcr_og"]
    fo, fg = params["end_oil"], params["end_gas"]
    exo, exoog, exg = params["exo_ow"], params["exo_og"], params["exg_og"]
    init = pvt.calc(pi, t)
    boi, bgi, rsi = init["bo"], init["bg"], params["rsi"]
    cwi = c_wat_1atm(pi, t, cfg["gamma_wat"])
    rows: list[MbeRow] = []
    prev = None
    for p in pressure_grid(params["depth"], pb):
        x = pvt.calc(p, t)
        rs, bo, bg, mu_o, mu_g = x["rs"], x["bo"], x["bg"], x["mu_oil"], x["mu_gas"]
        co = x["co_1MPa"] / MPA_ATMA
        cw = c_wat_1atm(p, t, cfg["gamma_wat"])
        cg = c_gas_1atm(p, t, cfg["gamma_gas"])
        rhs = ph_mbe_rhs(bo, boi, rsi, rs, bg, bgi, swl, cwi, cf, pi, p, m_cap) * 100
        if prev is None:
            krg_fn = lambda sg: _krg_og(fg, exg, sgcr, sorg, sg, swl)   # noqa: E731  Y3 — по своей строке
        else:
            krg_prev = ph.krg_baker(swi, swl, prev.so, prev.sg, sorg, fg, sgcr, exg, sorw, swcr)
            krg_fn = lambda sg, k=krg_prev: k   # noqa: E731  Y_i — по предыдущей строке

        def state(np_pct):
            so = (1 - swi) * (1 - np_pct / 100) * (bo / boi)                  # Get_So(Np, 100, Boi, Bo, Sw)
            sg = 0.0 if p >= pb else 1 - swi - so                            # get_sg (при p ≥ Pb в VBA — 0)
            kro = ph.kro_baker(swi, swl, sg, sorg, sorw, fo, exo, exoog)
            krg = krg_fn(sg)
            gor = rs + (krg / kro) * ((mu_o * bo) / (mu_g * bg))
            if prev is None:
                gp = np_pct * gor
            else:
                gp = prev.gp + (prev.gor + gor) / 2 * (np_pct - prev.np_pct)
            rp = gor if abs(np_pct) < 1e-300 else gp / np_pct
            return so, sg, kro, krg, gor, gp, rp

        def resid(np_pct):
            *_, rp = state(np_pct)
            return np_pct * (bo + (rp - rs) * bg) - rhs                       # MBE_LHS − MBE_RHS·100

        if abs(rhs) < 1e-14:
            np_pct = 0.0
        else:
            guess = prev.np_pct if prev is not None else 0.0
            lo, hi = guess - 1.0, guess + 1.0
            while resid(lo) * resid(hi) > 0 and hi - lo < 1e4:
                lo, hi = lo - (hi - lo), hi + (hi - lo)
            np_pct = brentq(resid, lo, hi, xtol=1e-14, rtol=1e-14, maxiter=500)
        so, sg, kro, krg, gor, gp, rp = state(np_pct)
        ct = co * (1 - swi - sg) + cw * swi + cg * sg + cf                  # Get_C_t_3ph
        row = MbeRow(p, rs, bo, bg, ct, mu_o, mu_g, np_pct, gp, rp, gor, so, sg, kro, krg)
        rows.append(row)
        prev = row
    return rows


def ph_mbe_rhs(bo, boi, rsi, rs, bg, bgi, sw, cw, cf, pi, p, m):
    return (bo - boi) + (rsi - rs) * bg + m * (bg / bgi - 1) + boi * (1 + m) * ((sw * cw + cf) / (1 - sw)) * (pi - p)


def build_object(params: dict, npz_pallet: Grid2D | None = None, name: str = "объект") -> FieldObject:
    """Объект разработки из параметров (кривые P → Bo, Ct, So, Sg по матбалансу).

    npz_pallet — палетка «доля НПЗ при предельной обводнённости»; по умолчанию
    строится по параметрам (waterflood.fdp_pallets, порт FDP_Functions).
    """
    p = dict(params)
    p["pvt_json"] = json.dumps(pvt_json(p))
    rows = mbe_table(p)
    if npz_pallet is None:
        from .waterflood import fdp_pallets
        npz_pallet = fdp_pallets(p, [r.np_pct for r in rows]).grid("npz")
    return FieldObject(name=name, params=p, p_curve=[r.p for r in rows], bo_curve=[r.bo for r in rows],
                       ct_curve=[r.ct for r in rows], so_curve=[r.so for r in rows], sg_curve=[r.sg for r in rows],
                       npz_pallet=npz_pallet)


@dataclass
class JdPalletSettings:
    """Параметры генерации палеток секций (строка 1 листа «Нормировка Jd»)."""
    mu: float            # ES1 вязкость смеси, сПз
    b: float             # EW1 объёмный коэффициент жидкости
    k: float             # FE1 проницаемость, мД
    phi: float           # FI1 пористость
    c_t: float           # FM1 сжимаемость, 1/атм
    t_p: float = 60.0    # FT1, сут
    r_e: float = 350.0   # FX1, м
    r_w: float = 0.07    # GB1, м
    kv_kh: float = 0.1   # GF1


def build_jd_pallets(s: JdPalletSettings, l_grid: list[float] | None = None, thickness=JD_THICKNESS) -> JdSectionPallets:
    """Палетки коэффициента секции ГС (блоки DA:GW) из параметров."""
    l_grid = JD_L_GRID if l_grid is None else l_grid
    grids = []
    for h in thickness:
        jd = [ph.get_j_obsolete(s.kv_kh, s.phi, L, s.t_p, s.r_e, s.r_w, h, s.k, 0.0, s.mu, s.c_t, s.b, 0.3)
              for L in l_grid]          # Get_Jd — общий множитель, в отношении сокращается
        f = []
        for i_sec, l_sec in enumerate(l_grid):
            row = []
            for i_tot, l_tot in enumerate(l_grid):
                if l_sec > l_tot:
                    row.append(1.0)
                else:
                    den = (l_tot / l_sec) * jd[i_sec]
                    row.append(jd[i_tot] / den if den else 1.0)
            f.append(row)
        grids.append(Grid2D(l_grid, l_grid, f))
    return JdSectionPallets(grids=tuple(grids), thickness=tuple(thickness))


def jd_settings_from_object(obj: FieldObject, p: float | None = None, **overrides) -> JdPalletSettings:
    """Параметры генерации палеток по объекту (строка 1 листа «Нормировка Jd»).

    k, φ — средневзвешенные по мощности единиц потока (D11:D16); B — Get_B_liq при
    начальной обводнённости (BA23); Ct — по кривой объекта при давлении p
    (по умолчанию Pb, как EP1 книги); вязкость — смесь по ОФП Бейкера при Swi
    (в книге — палетка Mu макроса FDP_Functions; расхождение коэффициентов ≤ 0,001).
    """
    prm = obj.params
    p = prm["pb"] if p is None else p
    h1, h2 = prm.get("heff_fu1") or 1.0, prm.get("heff_fu2") or 0.0
    k = (h1 * (prm.get("k_fu1") or 0) + h2 * (prm.get("k_fu2") or 0)) / (h1 + h2)
    phi = (h1 * (prm.get("phi_fu1") or 0) + h2 * (prm.get("phi_fu2") or 0)) / (h1 + h2)
    t = prm["t_C"]
    x = obj.pvt.calc(prm["p_init"], t)
    mu_w = ph.mu_water_cP(prm["p_init"], t, obj.pvt_cfg["gamma_wat"])
    bw = ph.bw_m3m3(prm["p_init"], t)
    swi = prm["swi"]
    kro = ph.kro_baker(swi, prm["swl"], 0.0, prm["sorg_og"], prm["sorw_ow"], prm["end_oil"], prm["exo_ow"], prm["exo_og"])
    krw = max(ph.krw_baker(swi, prm["swcr_ow"], 1 - swi, 0.0, prm["sorg_og"], prm["end_water"], prm["sorw_ow"],
                           prm["exw_ow"], prm["swl"]), 0.0)
    fw = ph.fw_from_kr(mu_w, x["mu_oil"], x["bo"], bw, krw, kro)
    s = JdPalletSettings(mu=ph.mu_from_kr(mu_w, x["mu_oil"], krw, kro), b=ph.b_liq(x["bo"], bw, fw),
                         k=k or 10.0, phi=phi or 0.2, c_t=obj.ct(p))
    for key, val in overrides.items():
        setattr(s, key, val)
    return s
