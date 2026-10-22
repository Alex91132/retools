# -*- coding: utf-8 -*-
"""Прогноз добычи во времени для подобранной компоновки (помесячно).

Модель — на той же физике срезов, что и подбор (rigis.compute): каждый месяц
пересчитываются дебиты срезов при текущих пластовом давлении и
насыщенностях. Между месяцами меняются:

- пластовое давление — по таблице матбаланса объекта (object_builder.mbe_table):
  начальному давлению соответствует уже отобранная доля Np₀ (% НГЗ); текущая —
  Np₀ + (1 − VRR)·(Np + Wp·Bw/Bo) / НГЗ дренируемого объёма: попутная вода
  тоже отбирает пластовый объём (в нефтяном эквиваленте, Bw ≈ 1); компенсация
  VRR (закачка, законтурная вода) — доля отобранного объёма, которая замещается
  водой (VRR = 1 — давление держится);
- насыщенность у забоя среза — по выбранной модели вытеснения (displacement):
  «piston» — упрощённо: ΔSw = VRR·ΔNp·Bo / Vпор среза, обводнение сразу;
  «bl» — Баклей–Леверетт (dynamics): пришедшая вода (VRR от отобранного
  пластового объёма) движется фронтом; до прорыва срез отдаёт начальную
  обводнённость, после — насыщенность у забоя по Велджу. При заданном ВНК
  вода поднимается снизу через столб «ВНК — ствол» с гравитацией (конус), при
  ГНК и газовой шапке (m > 0) газ опускается сверху — доля (1 − VRR)·m/(1 + m)
  отбора, у забоя растут Sg и ГФ; без контактов — фронт с латерали по
  дренируемому объёму среза;
- дренируемый объём ствола — «стадион» вокруг фильтров: площадь 2·R·L + π·R²
  (R — радиус контура зоны, L — длина фильтров), делится между срезами
  пропорционально длине; мощность — h эфф зоны, пористость — Кп среза.

Перетоки из изолированных зон: (а) негерметичность пакеров — изолированный
коллектор отдаёт в фильтры долю ε своего потенциала, ε растёт на leak_growth в
год (износ эластомеров); (б) по пласту вдоль ствола (crossflow) — доля по
сопротивлению пути через соседние срезы (dynamics.crossflow_eps). Добыча
перетоком участвует в матбалансе и обводняет изолированные срезы так же, как
вскрытые.

Ограничения работы: минимальный дебит нефти и предельная обводнённость —
после их достижения скважина останавливается. Коэффициент эксплуатации
уменьшает число рабочих суток в месяце.

Прогноз хранит помесячные потенциалы всех работающих срезов (вскрытых и
изолированных) и долю, которую срез отдал бы закрытым, — по ним подбор на
накопленную добычу (lifetime) оценивает, что даст вскрытие каждого среза.

Это не перенос листа «Расчёт добычи» книги (он — в gtm_calc), а прозрачная
модель для сравнения вариантов компоновки.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from .field_object import FieldObject, JdSectionPallets
from .interp import Curve
from .object_builder import mbe_table
from .rigis import compute

DAYS_IN_MONTH = 30.4
BW = 1.0              # объёмный коэффициент воды в отборе пластового объёма
RHO_AIR = 1.205       # кг/м³ при стандартных условиях


@dataclass
class ForecastMonth:
    month: int
    p_res: float          # средневзвешенное по фильтрам Рпл на начало месяца, атм
    q_oil: float          # т/сут (с перетоком)
    q_liq: float          # м³/сут (с перетоком)
    water_cut: float      # %
    cum_oil: float        # накопленная нефть, тыс. т
    cum_liq: float        # накопленная жидкость, тыс. м³
    sw: float             # средняя водонасыщенность у забоя в фильтрах
    working: bool = True
    q_oil_leak: float = 0.0   # из изолированных зон (пакеры и пласт), т/сут
    q_liq_leak: float = 0.0   # из изолированных зон, м³/сут
    leak: float = 0.0         # доля потенциала, проходящая через пакеры
    days: float = 0.0         # рабочих суток в месяце


@dataclass
class Forecast:
    months: list
    oip: float            # НГЗ дренируемого объёма, тыс. т
    stop_reason: str
    rho: float = 1.0
    # потенциалы работающих срезов по рабочим месяцам: (ствол, срез) → [(Qн, Qж, Bo, ε если закрыт), …]
    slice_q: dict = field(default_factory=dict)
    opened: set = field(default_factory=set)     # вскрытые срезы (ствол, срез)
    # по срезам: прорыв воды и газа (месяц), вертикальное вытеснение, предел Дитца, приток воды
    slice_info: dict = field(default_factory=dict)

    @property
    def cum_oil(self) -> float:
        return self.months[-1].cum_oil if self.months else 0.0

    @property
    def cum_liq(self) -> float:
        return self.months[-1].cum_liq if self.months else 0.0

    @property
    def cum_water(self) -> float:
        """Накопленная вода, тыс. м³."""
        return max(self.cum_liq - self.cum_oil / self.rho, 0.0)

    @property
    def cum_leak_liq(self) -> float:
        """Жидкость перетоком из изолированных зон, тыс. м³."""
        return sum(m.q_liq_leak * m.days for m in self.months if m.working) / 1000


def _inside(s, filters) -> bool:
    return any(f.top <= s.top and s.bottom <= f.bottom for f in filters)


def leak_at(month: int, leak: float, leak_growth: float) -> float:
    """Доля потенциала изолированных зон, уходящая в фильтры через пакеры, в месяце month (с 1)."""
    return min(1.0, max(0.0, leak + leak_growth * (month - 1) / 12))


@dataclass
class _St:
    """Состояние работающего среза в прогнозе."""
    li: int
    k: int
    pv: float             # поровый объём доли «стадиона», м³
    oip: float            # НГЗ, м³ ст.
    p0: float
    sw0: float
    sw_max: float
    bo0: float
    opened: bool
    sw: float             # текущая Sw у забоя
    sg: float = 0.0       # Sg у забоя от ГНК (0 — по матбалансу)
    w_in: float = 0.0     # пришедшая вода, м³ пластовых
    g_in: float = 0.0     # пришедший газ шапки, м³ пластовых
    bt_w: int | None = None
    bt_g: int | None = None


def forecast(cases, obj: FieldObject, pallets: JdSectionPallets, comps, l_total: float, months: int = 60,
             vrr: float = 0.0, k_oper: float = 1.0, q_min: float = 0.0, wc_max: float = 98.0,
             zones=None, leak: float = 0.0, leak_growth: float = 0.0, extra_voidage: float = 0.0,
             displacement: str = "piston", owc_tvd: float | None = None, goc_tvd: float | None = None,
             crossflow: bool = False, trans_mult: float = 1.0) -> Forecast:
    """Помесячный прогноз для компоновки (cases — стволы, comps — Completion по стволам).

    leak — доля потенциала изолированных срезов, приходящая в фильтры через пакеры
    (0 — пакеры герметичны); leak_growth — её прирост за год.
    extra_voidage — служебное: добавочный отбор без добычи, м³/сут нефтяного
    эквивалента (подбор lifetime так оценивает цену падения давления).
    displacement — «piston» (упрощённое) или «bl» (Баклей–Леверетт, конусы от
    owc_tvd / goc_tvd — абс. отметки, м); crossflow — перетоки по пласту вдоль
    ствола (trans_mult — множитель проводимости).
    """
    from .dynamics import (bl_table, crossflow_eps, dietz_critical_rate, gas_oil_kr, gravity_number,
                           water_oil_kr)
    if not isinstance(cases, (list, tuple)):
        cases, comps = [cases], [comps]
    zones = zones or [None] * len(cases)
    rho = obj.rho_oil
    prm = obj.params
    cfg = obj.pvt_cfg
    rho_w = cfg["gamma_wat"] * 1000
    l_tot = max(l_total, 1e-6)
    m_cap = prm.get("gas_cap_m", 0.0) or 0.0
    bl = displacement == "bl"
    st: list[_St] = []
    res0 = [compute(c, obj, pallets, z, l_total=l_tot) for c, z in zip(cases, zones)]
    for li, (c, comp, res) in enumerate(zip(cases, comps, res0)):
        for k, (s, r) in enumerate(zip(c.slices, res)):
            if not r.used:
                continue
            area = (2 * r.r_contour * l_tot + math.pi * r.r_contour ** 2) * s.h / l_tot
            pv = area * r.h_eff * s.phi
            bo = r.pvt.get("bo", 1.0)
            st.append(_St(li, k, pv, pv * (1 - s.sw) / bo, r.p_res, s.sw, 1 - max(r.kno, 0.0) - 1e-6, bo,
                          _inside(s, comp.filters), s.sw))
    opened = [x for x in st if x.opened]
    total_oip = sum(x.oip for x in opened)
    if not opened or total_oip <= 0:
        return Forecast([], 0.0, "нет работающих фильтров", rho)
    rows = mbe_table(prm)
    p_of_np = Curve([r.np_pct for r in rows], [r.p for r in rows])
    np_of_p = Curve([r.p for r in rows], [r.np_pct for r in rows])
    w = [x.pv for x in opened]
    p_ref0 = sum(x.p0 * wi for x, wi in zip(opened, w)) / sum(w)
    np0 = np_of_p(p_ref0)
    cum_np = {(x.li, x.k): 0.0 for x in st}         # отбор в нефтяном эквиваленте, м³ ст.
    extra = 0.0
    slice_q = {(x.li, x.k): [] for x in st}
    info: dict = {}
    by_lat = {li: [x for x in st if x.li == li] for li in range(len(cases))}
    out, cum_o, cum_l, stop, p_ref = [], 0.0, 0.0, "горизонт прогноза", p_ref0
    days = DAYS_IN_MONTH * k_oper
    for m in range(1, months + 1):
        p_ratio = p_ref / p_ref0
        eps = leak_at(m, leak, leak_growth)
        q_o = q_l = q_o_leak = q_l_leak = 0.0
        pot = {}
        for li, (c, z) in enumerate(zip(cases, zones)):
            mine = by_lat[li]
            if not mine:
                continue
            p_over = [0.0] * len(c.slices)
            sg_over = [0.0] * len(c.slices)
            slices = list(c.slices)
            for x in mine:
                p_over[x.k] = x.p0 * p_ratio
                sg_over[x.k] = x.sg
                slices[x.k] = replace(slices[x.k], sw=x.sw, so=max(0.0, 1 - x.sw))
            res = compute(replace(c, slices=slices), obj, pallets, z, l_total=l_tot, p_res_override=p_over,
                          sg_override=sg_over if bl else None)
            if crossflow:
                om = [False] * len(c.slices)
                for x in mine:
                    om[x.k] = x.opened
                e_cf = crossflow_eps(c.slices, res, om, c.defaults.kv_kh, trans_mult)
            else:
                e_cf = [0.0] * len(c.slices)
            for x in mine:
                r = res[x.k]
                qo, ql = max(r.q_oil, 0.0), max(r.q_liq, 0.0)
                e_closed = 1 - (1 - e_cf[x.k]) * (1 - eps)
                mult = 1.0 if x.opened else e_closed
                pot[(li, x.k)] = (qo, ql, mult, r.pvt.get("bo", x.bo0), r, e_closed)
                q_o += mult * qo
                q_l += mult * ql
                if not x.opened:
                    q_o_leak += mult * qo
                    q_l_leak += mult * ql
        wc = 0.0 if q_l <= 0 else max(0.0, 100 - q_o / rho / q_l * 100)
        sw_avg = sum(x.sw * x.pv for x in opened) / sum(w)
        if q_o <= 0 or q_o < q_min or wc > wc_max:
            stop = ("дебит нефти ниже минимального" if q_o < q_min or q_o <= 0 else "обводнённость выше предельной")
            out.append(ForecastMonth(m, p_ref, 0.0, 0.0, wc, cum_o / 1000, cum_l / 1000, sw_avg, working=False,
                                     leak=eps))
            break
        cum_o += q_o * days
        cum_l += q_l * days
        out.append(ForecastMonth(m, p_ref, q_o, q_l, wc, cum_o / 1000, cum_l / 1000, sw_avg, True,
                                 q_o_leak, q_l_leak, eps, days))
        # обновление состояния
        for x in st:
            key = (x.li, x.k)
            qo, ql, mult, bo, r, e_closed = pot[key]
            slice_q[key].append((qo, ql, bo, e_closed))
            d_np = mult * qo / rho * days              # м³ ст.
            d_wp = mult * max(ql - qo / rho, 0.0) * days
            cum_np[key] += d_np + d_wp * BW / bo
            if not bl:
                x.sw = min(x.sw + vrr * d_np * bo / x.pv, x.sw_max)
                continue
            _bl_step(x, m, cases[x.li], r, d_np * bo + d_wp * BW, days, vrr, owc_tvd, goc_tvd, m_cap, rho_w,
                     prm, cfg, info, bl_table, dietz_critical_rate, gas_oil_kr, gravity_number, water_oil_kr)
        extra += extra_voidage * days
        np_eff = np0 + (1 - vrr) * 100 * (sum(cum_np.values()) + extra) / total_oip
        p_ref = max(p_of_np(np_eff), 1.0)
    for x in st:
        d = info.setdefault((x.li, x.k), {})
        d.update(bt_w=x.bt_w, bt_g=x.bt_g, opened=x.opened)
    return Forecast(out, total_oip * rho / 1000, stop, rho, slice_q, {(x.li, x.k) for x in opened}, info)


def _bl_step(x: _St, m: int, c, r, void: float, days: float, vrr: float, owc_tvd, goc_tvd, m_cap: float,
             rho_w: float, prm: dict, cfg: dict, info: dict, bl_table, dietz_critical_rate, gas_oil_kr,
             gravity_number, water_oil_kr) -> None:
    """Шаг Баклея–Леверетта для среза: вода (снизу от ВНК или с латерали) и газ шапки (сверху от ГНК)."""
    s = c.slices[x.k]
    pt = r.pvt
    mid = (s.top_tvd + s.bottom_tvd) / 2 if s.bottom_tvd > 0 else 0.0
    area_v = s.h * 2 * max(r.r_contour, 1e-6)
    k_v = s.perm * c.defaults.kv_kh
    rho_o = (cfg["gamma_oil"] * 1000 + pt["rs"] * RHO_AIR * cfg["gamma_gas"]) / pt["bo"]
    # вода
    d_w = vrr * void
    x.w_in += d_w
    krw, kro = water_oil_kr(prm, r.kvo, r.kvcr, r.kno)
    vertical = owc_tvd is not None and 0 < mid < owc_tvd
    if vertical:
        pv_w = area_v * (owc_tvd - mid) * s.phi
        ng = gravity_number(k_v, area_v, rho_w - rho_o, pt["mu_o"], d_w / days)
    else:
        pv_w, ng = x.pv, 0.0
    key = (x.li, x.k)
    if key not in info:
        q_crit = (dietz_critical_rate(k_v, area_v, rho_w - rho_o, prm["end_water"], pt["mu_w"], float(kro(x.sw0)),
                                      pt["mu_o"]) if vertical else math.inf)
        info[key] = {"vertical": vertical, "pv_w": pv_w, "flux_w": d_w / days, "q_crit_w": q_crit,
                     "d_owc": (owc_tvd - mid) if vertical else None, "mid_tvd": mid,
                     "d_goc": (mid - goc_tvd) if (goc_tvd is not None and mid > goc_tvd) else None,
                     "front_w": [], "front_g": []}
    d = info[key]
    front = d["front_w"][-1] if d["front_w"] else 0.0
    if pv_w > 0 and x.w_in > 0:
        t = bl_table(krw, kro, pt["mu_w"], pt["mu_o"], x.sw0, 1 - r.kno, ng)
        qi = x.w_in / pv_w
        s_out = t.outlet(qi)
        if s_out > x.sw0 + 1e-6 and x.bt_w is None:
            x.bt_w = m
        x.sw = min(max(x.sw, s_out), x.sw_max)
        # доля пути, пройденного фронтом (1 — дошёл до забоя)
        front = max(front, 1.0 if x.bt_w else (min(qi / t.qi_bt, 1.0) if math.isfinite(t.qi_bt) else 0.0))
    d["front_w"].append(front)
    front_g = d["front_g"][-1] if d["front_g"] else 0.0
    _gas_step(x, m, c, r, s, pt, void, days, vrr, goc_tvd, m_cap, mid, area_v, k_v, rho_o, prm, cfg,
              bl_table, gas_oil_kr, gravity_number, d, front_g)


def _gas_step(x, m, c, r, s, pt, void, days, vrr, goc_tvd, m_cap, mid, area_v, k_v, rho_o, prm, cfg,
              bl_table, gas_oil_kr, gravity_number, d, front_g) -> None:
    """Газ шапки опускается от ГНК к срезу (Баклей–Леверетт с гравитацией)."""
    try:
        _gas_core(x, m, s, r, pt, void, days, vrr, goc_tvd, m_cap, mid, area_v, k_v, rho_o, prm, cfg,
                  bl_table, gas_oil_kr, gravity_number, d, front_g)
    finally:
        if len(d["front_g"]) < len(d["front_w"]):
            d["front_g"].append(front_g)


def _gas_core(x, m, s, r, pt, void, days, vrr, goc_tvd, m_cap, mid, area_v, k_v, rho_o, prm, cfg,
              bl_table, gas_oil_kr, gravity_number, d, front_g) -> None:
    if goc_tvd is None or m_cap <= 0 or not mid > goc_tvd:
        return
    d_g = (1 - vrr) * void * m_cap / (1 + m_cap)
    x.g_in += d_g
    pv_g = area_v * (mid - goc_tvd) * s.phi
    if pv_g <= 0 or x.g_in <= 0:
        return
    rho_g = RHO_AIR * cfg["gamma_gas"] / max(pt["bg"], 1e-9)
    ng_g = gravity_number(k_v, area_v, rho_o - rho_g, pt["mu_o"], d_g / days)
    krg, kro_g = gas_oil_kr(prm, r.kvo, x.sw)
    sg0 = max(r.sg, 0.0) if x.sg <= 0 else 0.0
    tg = bl_table(krg, kro_g, pt["mu_g"], pt["mu_o"], sg0, 1 - x.sw - prm["sorg_og"], ng_g)
    qi = x.g_in / pv_g
    g_out = tg.outlet(qi)
    if g_out > sg0 + 1e-6:
        if x.bt_g is None:
            x.bt_g = m
        x.sg = max(x.sg, g_out)
    d["front_g"].append(max(front_g, 1.0 if x.bt_g else (min(qi / tg.qi_bt, 1.0) if math.isfinite(tg.qi_bt) else 0.0)))
