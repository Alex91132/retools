# -*- coding: utf-8 -*-
"""Рейтинг ГТМ и расчёт добычи по скважинам — порт листов «Рейтинг ГТМ» и
«Расчёт добычи» RE Tools (формулы строки 7, протянутые макросом CalculateFDP).

Рейтинг (по скважине): свойства объекта (лист PVT_MBE_Waterflood), PVT при
начальном давлении, насыщенности и ОФП Бейкера, продуктивность Get_J,
депрессия Get_dP, стартовые Qж/Qн/обводнённость, безразмерная
продуктивность Jd, запасы (НГЗ на истощение и вытеснение — круг площади
«стадиона» вокруг ствола, прирост от ППД по соотношению скважин ППД/доб.),
подвижные запасы и потенциальный КИН (палетка доли НПЗ при предельной
обводнённости).

Расчёт добычи — шаг за шагом (месяц, при скачках давления — 10 суток), две
части пласта:
- истощаемая (1 − доля заводняемых толщин): Рпл — по матбалансу объекта от
  накопленного отбора (кривая LHS → P листа объекта), ОФП Бейкера при
  начальной Sw, продуктивность kh/(18,42·B·μ)·Jd;
- заводняемая: Рпл — по матбалансу с закачкой (ППД с заданного месяца,
  приёмистость — по давлению нагнетания и Jd ППД, не больше максимальной и
  текущей компенсации), Sw растёт с отбором от НПЗ, ОФП смеси — палетки
  Kro/Krw Mix, продуктивность — Get_J с текущими μ, Ct, B;
- Qж = Qж ист. + Qж завод.; остановка по минимальному Qн и предельной
  обводнённости; сводка по датам — лист «Результат расчёта».

Имена переменных — буквы столбцов книги, чтобы порт сверялся с листами один
к одному. Особенности книги сохранены и отмечены в комментариях.
"""
from __future__ import annotations

import calendar
import datetime as dt
import json
import math
from dataclasses import dataclass, field

from . import rigis_physics as ph
from .cpvt import CPVT
from .interp import Curve
from .productivity import get_completion, get_j
from .waterflood import FdpPallets

XL_PI = math.pi          # PI() Excel — полная точность (в VBA — 3,14159265358979)
NA = float("nan")        # #Н/Д листа


def _isna(x) -> bool:
    return isinstance(x, float) and math.isnan(x)


# --- лист объекта -------------------------------------------------------------------

@dataclass
class ObjectSheet:
    """Данные листа объекта (PVT_MBE_Waterflood), которые читают формулы рейтинга и расчёта.

    p, lhs, ct, so, sg, bo — столбцы E, O, I, T, U, G строк 3–38; params — D2:D38
    (ключи field_object.PARAM_ROWS); bwi, cwi — BA21, BA27; piezo_lag, ma_period —
    AZ38, BA38; pallets — палетки FDP_Functions.
    """
    params: dict
    p: list
    lhs: list
    ct: list
    so: list
    sg: list
    bo: list
    bwi: float
    cwi: float
    piezo_lag: float
    ma_period: float
    pallets: FdpPallets
    name: str = "PVT_MBE_Waterflood"
    _c: dict = field(default_factory=dict, repr=False)

    def __post_init__(self):
        q = self.params
        cfg = q["pvt_json"] if isinstance(q.get("pvt_json"), dict) else (
            json.loads(q["pvt_json"]) if q.get("pvt_json") else None)
        if cfg is None:
            from .object_builder import pvt_json
            cfg = pvt_json(q)
        self.pvt_cfg = cfg
        self.pvt = CPVT(gamma_gas=cfg["gamma_gas"], gamma_oil=cfg["gamma_oil"], gamma_wat=cfg["gamma_wat"],
                        rsb_m3m3=cfg["rsb_m3m3"], pb_atma=cfg["pb_atma"], bob_m3m3=cfg["bob_m3m3"],
                        muob_cP=cfg["muob_cP"], corr=cfg.get("PVT_corr_set", 1), t_res_C=cfg["t_res_C"])
        self._c = {"p_of_lhs": Curve(self.lhs, self.p), "lhs_of_p": Curve(self.p, self.lhs),
                   "ct": Curve(self.p, self.ct), "so": Curve(self.p, self.so), "sg": Curve(self.p, self.sg),
                   "bo": Curve(self.p, self.bo), "g_sg": self.pallets.grid("sg"),
                   "g_kro": self.pallets.grid("kro_mix"), "g_krw": self.pallets.grid("krw_mix"),
                   "g_npz": self.pallets.grid("npz")}

    def crv(self, name: str, x: float) -> float:
        return self._c[name](x)

    def grid(self, name: str, x: float, y: float) -> float:
        return self._c[name](x, y)

    def pvt_at(self, p: float) -> dict:
        x = self.pvt.calc(p, self.pvt_cfg["t_res_C"])
        t = self.pvt_cfg["t_res_C"]
        return {"bo": x["bo"], "bg": x["bg"], "rs": x["rs"], "mu_o": x["mu_oil"], "mu_g": x["mu_gas"],
                "mu_w": ph.mu_water_cP(p, t, self.pvt_cfg["gamma_wat"]), "bw": ph.bw_m3m3(p, t)}

    @classmethod
    def from_book(cls, book: dict) -> "ObjectSheet":
        """Из выгрузки листа (tests/fixtures/pvt_mbe_book.json)."""
        from .field_object import PARAM_ROWS
        q = {k: book["D"][str(r)] for k, r in PARAM_ROWS.items()}
        t = book["table"]
        p = book["pallets"]
        pal = FdpPallets(p["mu"]["x"], p["mu"]["y"], p["kro_mix"]["y"], p["npz"]["y"], p["mu"]["f"], p["sg"]["f"],
                         p["wc"]["f"], p["kro_mix"]["f"], p["krw_mix"]["f"], p["wc_mix"]["f"], p["npz"]["f"])
        a = book["aux"]
        return cls(q, t["E"], t["O"], t["I"], t["T"], t["U"], t["G"], a["BA21"], a["BA27"], a["AZ38"], a["BA38"], pal)

    @classmethod
    def from_params(cls, params: dict, name: str = "объект", piezo_lag: float = 4, ma_period: float = 1) -> "ObjectSheet":
        """Лист объекта из параметров: матбаланс решается заново, палетки — FDP_Functions."""
        from .object_builder import mbe_table
        from .waterflood import fdp_pallets, initial_pvt
        rows = mbe_table(params)
        init = initial_pvt(params)
        pal = fdp_pallets(params, [r.np_pct for r in rows])
        lhs = [r.np_pct * (r.bo + (r.rp - r.rs) * r.bg) for r in rows]
        return cls(dict(params), [r.p for r in rows], lhs, [r.ct for r in rows], [r.so for r in rows],
                   [r.sg for r in rows], [r.bo for r in rows], init.bwi, init.cwi, piezo_lag, ma_period, pal, name)


# --- рейтинг ГТМ ----------------------------------------------------------------------

INPUT_COLS = ("A B C D E F G H I J K L M N O P Q R S T U V W X Y Z AA AB AC AD AE AF AG AH AI AJ AK AL AM AN AO "
              "AP AQ AR AS AT AU AV AW AX AY").split()


def _num(v) -> float:
    return 0.0 if v is None or v == "" else v


def rating_row(inp: dict, obj: ObjectSheet, cj_with_ci: bool = False) -> dict:
    """Строка «Рейтинга ГТМ»: входы (A:AY) + расчётные столбцы (AZ:DG).

    cj_with_ci — вариант книги для строк 8 и ниже: «НПЗ вытеснение» CJ считается
    от НГЗ вытеснения вместе с приростом от ППД (CH + CI), хотя прирост НПЗ от ППД
    (CK) потом прибавляется к нему ещё раз; в строке 7 книги и по умолчанию — от CH.
    """
    r = {k: inp.get(k) for k in INPUT_COLS}
    g = lambda c: _num(r.get(c))     # noqa: E731
    q = obj.params
    r["E"] = r["A"]
    r["K"] = get_completion(g("T"), int(g("Y")), int(g("V")))
    # BG:CE — параметры листа объекта
    for col, key in (("BG", "swl"), ("BH", "swi"), ("BI", "depth"), ("BJ", "t_C"), ("BM", "rho_oil"),
                     ("BN", "gamma_wat"), ("BO", "pb"), ("BP", "sorw_ow"), ("BQ", "sorg_og"), ("BR", "swcr_ow"),
                     ("BS", "sgcr_og"), ("BT", "end_oil"), ("BU", "end_water"), ("BV", "end_gas"), ("BW", "exo_ow"),
                     ("BX", "exw_ow"), ("BY", "exo_og"), ("BZ", "exg_og"), ("CA", "c_f")):
        r[col] = q[key]
    r["BK"] = q.get("rock_density") or 2.3
    r["CB"], r["CC"], r["CD"], r["CE"] = obj.piezo_lag, obj.ma_period, obj.bwi, obj.cwi
    R, Q, AI, M, N, O, S = g("R"), g("Q"), g("AI"), g("M"), g("N"), g("O"), g("S")
    v = obj.pvt_at(R)
    r["CQ"], r["CR"], r["CS"], r["CT"], r["CU"], r["CV"], r["CW"] = (v["mu_o"], v["mu_w"], v["mu_g"], v["bo"], v["bw"],
                                                                     v["bg"], v["rs"])
    d4 = q["swi"]
    r["CX"] = 1 - (obj.crv("so", R) / (1 - d4) * (1 - Q)) - Q
    r["CY"] = 1 - Q - r["CX"]
    try:
        r["CZ"] = ph.kro_baker(Q, r["BG"], r["CX"], r["BQ"], r["BP"], r["BT"], r["BW"], r["BY"])
        if isinstance(r["CZ"], complex):
            r["CZ"] = 0.0
    except (ValueError, ZeroDivisionError):
        r["CZ"] = 0.0
    r["DA"] = ph.krg_baker(Q, r["BG"], r["CY"], r["CX"], r["BQ"], r["BV"], r["BS"], r["BZ"], r["BP"], r["BR"])
    r["DB"] = ph.krw_baker(Q, r["BR"], r["CY"], r["CX"], r["BQ"], r["BU"], r["BP"], r["BX"], r["BG"])
    r["DC"] = ph.mu_from_kr(r["CR"], r["CQ"], r["DB"], r["CZ"])
    r["DD"] = obj.crv("ct", R)
    r["BD"] = ph.fw_from_kr(r["CR"], r["CQ"], r["CT"], r["CU"], r["DB"], r["CZ"])
    r["DE"] = _b_liq(r["CT"], r["CU"], r["BD"])
    r["DF"] = _get_j_row(r, r["DC"], r["DD"], r["DE"]) * g("AW")
    d = ph.get_dp(r["BO"], AI, r["BD"], R)
    r["DG"] = 0.0 if d < 0 else (g("AV") if d > g("AV") else d)
    r["BC"] = r["DG"] * r["DF"] * g("AW")
    r["BE"] = r["BC"] * r["BM"] * (1 - r["BD"] / 100)
    try:
        r["BF"] = ph.gor(r["CW"], r["DA"], r["CZ"], r["CQ"], r["CT"], r["CS"], r["CV"])
    except ZeroDivisionError:
        r["BF"] = 0.0
    r["CF"] = 0.0 if M * O == 0 else (18.42 * r["DC"] * r["DE"] * r["DF"]) / (M * O)       # Get_Jd
    r["AO"] = r["CF"]
    AF, U, AA = g("AF"), g("U"), g("AA")
    side = AA * 2 * U if r.get("AE") == "Поперёк" else U * 2 * AF
    r_eq = math.sqrt((AF * 2 * U + side + XL_PI * AF ** 2) / XL_PI)    # «стадион» (в книге 2·AF·U учтено дважды)
    r["CG"] = ph.get_n(N, r["CT"], 1, r_eq, Q, M * (1 - S))
    r["CH"] = ph.get_n(N, r["CT"], 1, r_eq, Q, M * S)
    r["CI"] = 0.0 if g("AL") == 0 else g("AM") * ph.get_n(N, r["CT"], 1, AF, Q, M * S)
    mov = (1 - Q - r["BP"]) / ((1 - Q - r["BP"]) + r["BP"])
    r["CJ"] = mov * ((r["CH"] + r["CI"]) if cj_with_ci else r["CH"])
    r["CK"] = mov * r["CI"]
    r["CL"], r["CM"] = Q, g("AU")
    r["CN"] = obj.grid("g_npz", r["CL"], r["CM"])
    sg_r, sg_ai = obj.crv("sg", R), obj.crv("sg", AI)
    r["CO"] = r["CG"] * ((1 - Q - sg_r / (1 - d4) * (1 - Q)) - (1 - Q - sg_ai / (1 - d4) * (1 - Q))) / (
        obj.crv("bo", AI) / obj.crv("bo", R))
    r["CP"] = (r["CJ"] + r["CK"]) * r["CN"]
    r["AZ"] = (r["CG"] + r["CH"] + r["CI"]) * r["BM"]
    r["BB"] = (r["CO"] + r["CP"]) * r["BM"]
    r["BA"] = r["BB"] / r["AZ"]
    return r


def _b_liq(bo, bw, fw):
    return bo * (1 - fw / 100) + (bw or 1.0) * fw / 100


def _get_j_row(r: dict, mu: float, ct: float, b: float) -> float:
    g = lambda c: _num(r.get(c))     # noqa: E731
    return get_j(g("P"), g("N"), g("T"), g("U"), g("AJ"), g("AF"), g("AG"), g("M"), g("O"), g("AH"), mu, ct, b,
                 int(g("Y")), g("AB"), g("AC"), g("AA"), g("W"), g("X"), int(g("V")), r.get("AE") or "")


def _dp_clamped(pb, pwf, fw, pr, lo, hi):
    d = ph.get_dp(pb, pwf, fw, pr)
    if lo is not None and d < lo:
        return lo
    if d > hi:
        return hi
    return d


# --- расчёт добычи ---------------------------------------------------------------------

def _date(v) -> dt.date:
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return dt.datetime.fromisoformat(str(v)).date()


def _days_to_month_end(d: dt.date) -> int:
    """DAYS(EOMONTH(FL,0)+1, FL)."""
    last = calendar.monthrange(d.year, d.month)[1]
    return (dt.date(d.year, d.month, last) - d).days + 1


def _mbe_lhs(np_, bo, bg, rs, rp, we=0.0, wp=0.0, bw=0.0, ginj=0.0, bginj=0.0, winj=0.0, bwi=0.0):
    return np_ * (bo + (rp - rs) * bg) - (we - wp * bw) - ginj * bginj - winj * bwi


def _stdev(xs):
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def production_rows(rating: list[dict], obj, max_rows: int | None = None, progress=None) -> list[dict]:
    """Лист «Расчёт добычи»: строки по скважинам и шагам (как после макроса CalculateFDP).

    obj — ObjectSheet или словарь {код объекта (столбец G): ObjectSheet};
    progress(i_well, n_wells, row) — необязательный обратный вызов.
    """
    rows: list[dict] = []
    dy_hist: list[float] = []
    gt_prev = 0
    prev: dict | None = None
    while gt_prev < len(rating):
        if max_rows is not None and len(rows) >= max_rows:
            break
        w = rating[gt_prev]
        o = obj[w.get("G")] if isinstance(obj, dict) else obj
        r = _step(w, prev, o, dy_hist)
        r["GT"] = gt_prev + 1 if (r["FM"] == r["AY"] or r["AY"] == 0) else gt_prev
        rows.append(r)
        dy_hist.append(r["DY"])
        gt_prev = r["GT"]
        prev = r
        if progress is not None:
            progress(gt_prev, len(rating), r)
    return rows


def _step(w: dict, p: dict | None, obj: ObjectSheet, dy_hist: list) -> dict:
    """Одна строка листа «Расчёт добычи» (w — строка рейтинга, p — предыдущая строка листа)."""
    r = dict(w)
    for c in INPUT_COLS:             # INDEX пустой ячейки рейтинга — 0
        if r.get(c) is None:
            r[c] = 0
    g = lambda c: _num(r.get(c))     # noqa: E731
    pv = (lambda c: p.get(c)) if p is not None else (lambda c: None)
    # FM — месяц работы; новая скважина — 1
    if p is None or (str(r["A"]) + str(r["E"])) != (str(p["A"]) + str(p["E"])):
        FM = 1
    else:
        nxt = _date(p["FL"]) + dt.timedelta(days=p["FN"])
        FM = p["FM"] if nxt.month == _date(p["FL"]).month else p["FM"] + 1
    first = FM == 1
    FL = _date(r["J"]) if first else _date(p["FL"]) + dt.timedelta(days=p["FN"])
    R, Q, AI, AX, AT, AV, S = g("R"), g("Q"), g("AI"), g("AX"), g("AT"), g("AV"), g("S")
    BM, BO, BP, CD = r["BM"], r["BO"], r["BP"], r["CD"]
    lhs_r = obj.crv("lhs_of_p", R)
    # --- истощаемая часть (Dep) ---
    if first:
        CL = R
    else:
        x = obj.crv("p_of_lhs", pv("CM"))
        CL = AI if x < AI else x
    v = obj.pvt_at(CL)
    CR, CS, CT, CU, CV, CW, CX = v["bo"], v["bw"], v["bg"], v["mu_o"], v["mu_w"], v["mu_g"], v["rs"]
    CY, CZ = Q, CL
    DA = obj.grid("g_sg", CY, CZ)
    DB = 1 - CY - DA
    DC = _safe(lambda: ph.kro_baker(CY, r["BG"], DA, r["BQ"], BP, r["BT"], r["BW"], r["BY"]), 0.0)
    DD = ph.krg_baker(CY, r["BG"], DB, DA, r["BQ"], r["BV"], r["BS"], r["BZ"], BP, r["BR"])
    DE = ph.krw_baker(CY, r["BR"], DB, DA, r["BQ"], r["BU"], BP, r["BX"], r["BG"])
    DF = ph.mu_from_kr(CV, CU, DE, DC)
    DK = ph.fw_from_kr(CV, CU, CR, CS, DE, DC)
    DG = _b_liq(CR, CS, DK)
    DH = (g("O") * g("M") * (1 - S)) / (18.42 * DG * DF) * r["CF"]
    DI = _dp_clamped(BO, AI, DK, CL, 0.0, AV)
    stop_prev = (not first) and _stopped(p)
    DJ = DI * DH if first else (0.0 if stop_prev else DI * DH)
    DL = DJ * BM * (1 - DK / 100)
    DM = _safe(lambda: ph.gor(CX, DD, DC, CU, CR, CW, CT), 0.0)
    # --- заводняемая часть (WF): давление ---
    AP, AN, BI, BK = g("AP"), g("AN"), r["BI"], r["BK"]
    if AP == 0 and first:
        DN = 1 / 3 * (BI * BK * 0.0981 - 0.7 * R) + R - 3
    elif AP == 0:
        DN = 1 / 3 * (BI * BK * 0.0981 - 0.7 * pv("DW")) + pv("DW") - 3
    else:
        DN = AN + BI * 0.0981
    if first:
        DY = R
    else:
        x = obj.crv("p_of_lhs", pv("ED"))
        DY = AI * 0.9 if x < AI * 0.9 else (DN * 0.9 if x > DN * 0.9 else x)
    DZ = r["CH"] if FM <= g("AL") else r["CH"] + r["CI"]
    EA = r["CJ"] if FM <= g("AL") else r["CJ"] + r["CK"]
    EB = Q
    EC = 0.0 if first else pv("EE") * pv("EN") / 1000 / EA
    CB, CC = r["CB"], r["CC"]
    hist = dy_hist + [DY]
    n = len(hist)                    # строка листа: индекс n-1 в hist
    if EC < 0.01:
        DX = 0.0
    else:
        win = hist[max(0, n - 1 - int(CC)):n]
        DX = _stdev(win) / (sum(win) / len(win)) if len(win) > 1 else 0.0
    if FM < CC:
        DW = DY
    elif DX > 0.05:
        win = hist[max(0, n - 1 - int(CC)):n - 1]
        DW = sum(win) / len(win)
    else:
        DW = DY
    if FM < CB + CC or FM < g("AL"):
        DV = DY
    elif FM <= CB + g("AL"):
        DV = pv("DV")
    else:
        a, b = n - 1 - int(CC) - int(CB), n - 1 - int(CB)
        win = hist[max(0, a):b]
        DV = sum(win) / len(win) if win else DY
    FN = 10 if DX > 0.05 else _days_to_month_end(FL)
    v2 = obj.pvt_at(DY)
    EK, EL, EM, EN, EO, EP = v2["mu_o"], v2["mu_w"], v2["mu_g"], v2["bo"], v2["bw"], v2["bg"]
    rs_dy = v2["rs"]
    EQ = rs_dy if first else (pv("EQ") if (pv("EQ") < rs_dy or rs_dy < 0) else rs_dy)
    ER = Q + EC * (1 - Q - BP)
    ES = DY
    ET = obj.grid("g_sg", ER, ES)
    EU = 1 - ER - ET
    EV = _safe(lambda: ph.kro_baker(ER, r["BG"], ET, r["BQ"], BP, r["BT"], r["BW"], r["BY"]), 0.0)
    EW = ph.krw_baker(ER, r["BR"], EU, ET, r["BQ"], r["BU"], BP, r["BX"], r["BG"])
    EX = ph.krg_baker(ER, r["BG"], EU, ET, r["BQ"], r["BV"], r["BS"], r["BZ"], BP, r["BR"])
    EY = _safe(lambda: obj.grid("g_kro", EB, EC), 0.0)
    EZ = obj.grid("g_krw", EB, EC)
    FA = min(EV, EY)
    FB = EW if FM < g("AL") else EZ
    FC = ph.mu_from_kr(EL, EK, FB, FA)
    FD = obj.crv("ct", DY)
    FI = ph.fw_from_kr(EL, EK, EN, EO, FB, FA)
    FE = _b_liq(EN, EO, FI)
    FF = _get_j_row(r, FC, FD, FE) * S * g("AW")
    FG = _dp_clamped(BO, AI, FI, DY, 1.0, AV)
    FH = FG * FF if first else (0.0 if stop_prev else FG * FF)
    FJ = FH * BM * (1 - FI / 100)
    FK = _safe(lambda: ph.gor(EQ, EX, FA, EK, EN, EM, EP), 0.0)
    # --- итог шага ---
    BC = NA if DJ + FH == 0 else DJ + FH
    BE = NA if (DL + FJ == 0 or DL + FJ < AT) else DL + FJ
    BD = NA if (_isna(BE) or BE == 0) else (1 - BE / BM / BC) * 100
    BF = NA if _isna(BE) else _safe(lambda: (DL * DM + FJ * FK) / BE, NA)
    # --- накопленные (истощение) ---
    CN = DJ * (1 - DK / 100) * FN * AX + (0 if first else pv("CN"))
    CO = DJ * (DK / 100) * FN * AX + (0 if first else pv("CO"))
    CP = CN * DM if first else pv("CP") + (pv("DM") + DM) / 2 * (CN - pv("CN"))
    CQ = _safe(lambda: CP / CN, 0.0)
    CM = _mbe_lhs(CN, CR, CT, CX, CQ, 0.0, CO, CS, 0.0, 0.0, 0.0, CD) / (r["CG"] * 10) + lhs_r
    # --- накопленные (заводнение) ---
    EE = FJ * FN * AX / BM + (0 if first else pv("EE"))
    EF = FH * (FI / 100) * FN * AX + (0 if first else pv("EF"))
    EG = EE * FK if first else pv("EG") + (pv("FK") + FK) / 2 * (EE - pv("EE"))
    EJ = EG / EE if EE else NA
    # ППД и аквифер
    AS = g("AS")
    DQ = 0.0 if AS == 0 else _safe(lambda: FH * FN / FG, 0.0)
    if first:
        DU = R
    else:
        try:
            d = R - pv("EI") / (DZ * AS * 1000) / (r["CA"] + r["CE"])
            step = obj.p[0] / 100 * EC
            DU = pv("DU") + step if d - pv("DU") > step else d
        except ZeroDivisionError:
            DU = 0.0
    EI = 0.0 if first else _safe(lambda: (pv("DU") - pv("DY")) * pv("DQ") + pv("EI"), 0.0)
    DO = 1 / 3 * (BI * BK * 0.0981 - 0.7 * DY) + DY
    DP = (g("O") * g("M") * S) / (18.42 * EO * FC) * (g("AO") if DN < DO else g("AO") * AP)
    # DR: в книге — #Н/Д, если на предыдущей строке Qж завод. = 0 (в т. ч. у предыдущей скважины)
    DR = NA if (p is not None and pv("FH") == 0) else DN - DY
    GC = ((EE * EN + CN * CR) - (0 if first else (pv("EE") * pv("EN") + pv("CN") * pv("CR")))) / 1000
    GD = ((EF * EO + CO * CS) - (0 if first else (pv("EF") * pv("EO") + pv("CO") * pv("CS")))) / 1000
    GE = ((EG * EP + CP * CT) - (0 if first else (pv("EG") * pv("EP") + pv("CP") * pv("CT")))) / 1000
    GF = GC + GD + GE
    lim = g("AQ") * g("AM")
    cur = GF * g("AR") * 1000 / FN / AX
    DS = lim if cur > lim else (0.0 if GF < 0 else cur)
    if FM < g("AL"):
        DT = 0.0
    elif _isna(DR):
        DT = NA
    else:
        DT = DS if DR * DP > DS else DR * DP
    EH = (DT * FN * AX) + (0 if first else pv("EH"))
    ED = _mbe_lhs(EE, EN, EP, EQ, EJ, EI, EF, EO, 0.0, 0.0, EH, CD) / (DZ * 10) + lhs_r
    # --- добыча шага ---
    FO = BE * FN / 1000 * AX
    FP = FO / BM
    FS = BC * FN / 1000 * AX
    FR = FS - FP
    FQ = FO + FR
    FT = DT * FN * AX / 1000
    FU = _safe(lambda: BE * BF / BM / 1000000 * AX, NA)
    cum = {}
    for c, val in (("FV", FO), ("FW", FP), ("FX", FQ), ("FY", FR), ("FZ", FS), ("GA", FT), ("GB", FU)):
        cum[c] = val if first else val + pv(c)
    GG = (EE * EN + EF * EO + EG * EP + CN * CR + CO * CS + CP * CT) / 1000
    GH = _safe(lambda: FT / (GC + GD + GE), NA)
    GI = 0.0 if first else _safe(lambda: pv("GA") / pv("GG"), NA)
    GJ = NA if DJ + FH == 0 else (DY if DJ == 0 else (CL * DJ + DY * FH) / (DJ + FH))
    GK = NA if DJ + FH == 0 else (DY - FG) * S + (CL - DI) * (1 - S)
    GL = BE if first else pv("GL")
    nz = r["CG"] + r["CH"] + r["CI"]
    r.update(dict(
        FM=FM, FL=FL, FN=FN, CL=CL, CM=CM, CN=CN, CO=CO, CP=CP, CQ=CQ, CR=CR, CS=CS, CT=CT, CU=CU, CV=CV, CW=CW,
        CX=CX, CY=CY, CZ=CZ, DA=DA, DB=DB, DC=DC, DD=DD, DE=DE, DF=DF, DG=DG, DH=DH, DI=DI, DJ=DJ, DK=DK, DL=DL,
        DM=DM, DN=DN, DO=DO, DP=DP, DQ=DQ, DR=DR, DS=DS, DT=DT, DU=DU, DV=DV, DW=DW, DX=DX, DY=DY, DZ=DZ, EA=EA,
        EB=EB, EC=EC, ED=ED, EE=EE, EF=EF, EG=EG, EH=EH, EI=EI, EJ=EJ, EK=EK, EL=EL, EM=EM, EN=EN, EO=EO, EP=EP,
        EQ=EQ, ER=ER, ES=ES, ET=ET, EU=EU, EV=EV, EW=EW, EX=EX, EY=EY, EZ=EZ, FA=FA, FB=FB, FC=FC, FD=FD, FE=FE,
        FF=FF, FG=FG, FH=FH, FI=FI, FJ=FJ, FK=FK, BC=BC, BD=BD, BE=BE, BF=BF, FO=FO, FP=FP, FQ=FQ, FR=FR, FS=FS,
        FT=FT, FU=FU, GC=GC, GD=GD, GE=GE, GF=GF, GG=GG, GH=GH, GI=GI, GJ=GJ, GK=GK, GL=GL,
        GM=_safe(lambda: 1 - BE / GL, NA), GN=BD / 100, GO=_safe(lambda: FR / FP, NA), GP=_safe(lambda: cum["FY"] / cum["FW"], NA),
        GQ=cum["GA"] / nz, GR=(cum["FW"] + cum["FY"]) / nz, GS=cum["FW"] / nz, **cum))
    return r


def _safe(fn, default):
    try:
        v = fn()
    except (ZeroDivisionError, ValueError, OverflowError, TypeError):
        return default
    return default if isinstance(v, complex) else v


def _stopped(p: dict) -> bool:
    """IF(OR(BE6<=AT6, BD6>=AU6), 0, …): #Н/Д на предыдущей строке тоже останавливает."""
    be, bd = p["BE"], p["BD"]
    if _isna(be) or _isna(bd):
        return True
    return be <= _num(p.get("AT")) or bd >= _num(p.get("AU"))


# --- «Результат расчёта» -------------------------------------------------------------------

def result_by_month(rows: list[dict]) -> list[dict]:
    """Сводка по календарным месяцам (аналог листа «Результат расчёта»).

    Дебиты скважины в месяце — средние по дням её шагов (месяц с 10-суточным
    шагом не удваивается), затем сумма по скважинам; добыча за месяц — сумма
    по шагам; накопленные — на конец месяца, у закончивших расчёт скважин
    переносятся дальше. Сводная таблица книги — кэш прошлого расчёта и с
    текущими строками листа не совпадает, поэтому сверяется не она, а строки.
    """
    months: dict = {}
    for r in rows:
        key = (r["FL"].year, r["FL"].month)
        well = (str(r["A"]), str(r["E"]))
        m = months.setdefault(key, {})
        w = m.setdefault(well, {"days": 0.0, "qo": 0.0, "ql": 0.0, "inj": 0.0, "oil_t": 0.0, "liq_m3": 0.0,
                                "inj_m3": 0.0, "p": [], "pwf": []})
        days = r["FN"]
        if not _isna(r["BE"]):
            w["days"] += days
            w["qo"] += r["BE"] * days
            w["ql"] += r["BC"] * days
            w["inj"] += (0.0 if _isna(r["DT"]) else r["DT"]) * days
            w["oil_t"] += r["FO"]
            w["liq_m3"] += r["FS"]
            w["inj_m3"] += r["FT"] if not _isna(r["FT"]) else 0.0
            w["p"].append(r["GJ"])
            w["pwf"].append(r["GK"])
        w["cum"] = (r["FV"], r["FW"], r["FZ"], r["GB"], r["GA"])
    out, last_cum = [], {}
    for key in sorted(months):
        m = months[key]
        for well, w in m.items():
            last_cum[well] = w["cum"]
        work = [w for w in m.values() if w["days"] > 0]
        qo = sum(w["qo"] / w["days"] for w in work)
        ql = sum(w["ql"] / w["days"] for w in work)
        rho = rows[0]["BM"] if rows else 1.0
        cum = [sum(c[i] for c in last_cum.values() if not _isna(c[i])) for i in range(5)]
        ps = [x for w in work for x in w["p"] if not _isna(x)]
        pw = [x for w in work for x in w["pwf"] if not _isna(x)]
        out.append({"date": dt.date(key[0], key[1], 1), "n_wells": len(work), "q_oil": qo, "q_liq": ql,
                    "water_cut": 0.0 if ql == 0 else max(0.0, (1 - qo / rho / ql) * 100),
                    "inj": sum(w["inj"] / w["days"] for w in work), "oil_t": sum(w["oil_t"] for w in m.values()),
                    "liq_m3": sum(w["liq_m3"] for w in m.values()), "inj_m3": sum(w["inj_m3"] for w in m.values()),
                    "cum_oil_t": cum[0], "cum_oil_m3": cum[1], "cum_liq_m3": cum[2], "cum_gas": cum[3],
                    "cum_inj": cum[4], "p_res": sum(ps) / len(ps) if ps else NA,
                    "p_wf": sum(pw) / len(pw) if pw else NA})
    return out
