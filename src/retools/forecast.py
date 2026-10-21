# -*- coding: utf-8 -*-
"""Прогноз добычи во времени для подобранной компоновки (помесячно).

Модель — на той же физике срезов, что и подбор (rigis.compute): каждый месяц
пересчитываются дебиты срезов при текущих пластовом давлении и
водонасыщенности. Между месяцами меняются:

- пластовое давление — по таблице матбаланса объекта (object_builder.mbe_table):
  начальному давлению соответствует уже отобранная доля Np₀ (% НГЗ); текущая —
  Np₀ + (1 − VRR)·(Np + Wp·Bw/Bo) / НГЗ дренируемого объёма: попутная вода
  тоже отбирает пластовый объём (в нефтяном эквиваленте, Bw ≈ 1); компенсация
  VRR (закачка, законтурная вода) — доля отобранного объёма, которая замещается
  водой (VRR = 1 — давление держится);
- водонасыщенность среза — замещённый водой объём: ΔSw = VRR·ΔNp·Bo / Vпор
  среза (не выше 1 − Sor);
- дренируемый объём ствола — «стадион» вокруг фильтров: площадь 2·R·L + π·R²
  (R — радиус контура зоны, L — длина фильтров), делится между срезами
  пропорционально длине; мощность — h эфф зоны, пористость — Кп среза.

Перетоки из изолированных зон (заколонный переток вдоль ствола через пакеры,
негерметичность эластомеров): изолированный коллектор отдаёт в фильтры долю ε
своего потенциала (Qн и Qж среза, как если бы он был вскрыт); ε растёт со
временем на leak_growth в год (износ эластомеров), не выше 1. Добыча перетоком
участвует в матбалансе и обводняет изолированные срезы так же, как вскрытые.

Ограничения работы: минимальный дебит нефти и предельная обводнённость —
после их достижения скважина останавливается. Коэффициент эксплуатации
уменьшает число рабочих суток в месяце.

Прогноз хранит помесячные потенциалы всех работающих срезов (вскрытых и
изолированных) — по ним подбор на накопленную добычу (lifetime) оценивает,
что даст вскрытие каждого среза.

Это не перенос листа «Расчёт добычи» книги (там палетки заводнения и
рейтинг ГТМ), а прозрачная модель для сравнения вариантов компоновки.
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


@dataclass
class ForecastMonth:
    month: int
    p_res: float          # средневзвешенное по фильтрам Рпл на начало месяца, атм
    q_oil: float          # т/сут (с перетоком)
    q_liq: float          # м³/сут (с перетоком)
    water_cut: float      # %
    cum_oil: float        # накопленная нефть, тыс. т
    cum_liq: float        # накопленная жидкость, тыс. м³
    sw: float             # средняя водонасыщенность в фильтрах
    working: bool = True
    q_oil_leak: float = 0.0   # из изолированных зон, т/сут
    q_liq_leak: float = 0.0   # из изолированных зон, м³/сут
    leak: float = 0.0         # доля потенциала изолированных зон ε
    days: float = 0.0         # рабочих суток в месяце


@dataclass
class Forecast:
    months: list
    oip: float            # НГЗ дренируемого объёма, тыс. т
    stop_reason: str
    rho: float = 1.0
    # потенциалы работающих срезов по рабочим месяцам: (ствол, срез) → [(Qн, Qж, Bo), …]
    slice_q: dict = field(default_factory=dict)
    opened: set = field(default_factory=set)     # вскрытые срезы (ствол, срез)

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
    """Доля потенциала изолированных зон, уходящая в фильтры, в месяце month (с 1)."""
    return min(1.0, max(0.0, leak + leak_growth * (month - 1) / 12))


def forecast(cases, obj: FieldObject, pallets: JdSectionPallets, comps, l_total: float, months: int = 60,
             vrr: float = 0.0, k_oper: float = 1.0, q_min: float = 0.0, wc_max: float = 98.0,
             zones=None, leak: float = 0.0, leak_growth: float = 0.0, extra_voidage: float = 0.0) -> Forecast:
    """Помесячный прогноз для компоновки (cases — стволы, comps — Completion по стволам).

    leak — доля потенциала изолированных срезов, приходящая в фильтры перетоком
    (0 — пакеры герметичны); leak_growth — её прирост за год.
    extra_voidage — служебное: добавочный отбор без добычи, м³/сут нефтяного
    эквивалента (подбор lifetime так оценивает цену падения давления).
    """
    if not isinstance(cases, (list, tuple)):
        cases, comps = [cases], [comps]
    zones = zones or [None] * len(cases)
    rho = obj.rho_oil
    l_tot = max(l_total, 1e-6)
    # работающие срезы: [ствол, срез, Vпор, НГЗ м³, p0, Sw0, Sw max, Bo0, вскрыт]
    st = []
    res0 = [compute(c, obj, pallets, z, l_total=l_tot) for c, z in zip(cases, zones)]
    for li, (c, comp, res) in enumerate(zip(cases, comps, res0)):
        for k, (s, r) in enumerate(zip(c.slices, res)):
            if not r.used:
                continue
            area = (2 * r.r_contour * l_tot + math.pi * r.r_contour ** 2) * s.h / l_tot
            pv = area * r.h_eff * s.phi
            bo = r.pvt.get("bo", 1.0)
            st.append([li, k, pv, pv * (1 - s.sw) / bo, r.p_res, s.sw, 1 - max(r.kno, 0.0) - 1e-6, bo,
                       _inside(s, comp.filters)])
    opened = [x for x in st if x[8]]
    total_oip = sum(x[3] for x in opened)
    if not opened or total_oip <= 0:
        return Forecast([], 0.0, "нет работающих фильтров", rho)
    rows = mbe_table(obj.params)
    p_of_np = Curve([r.np_pct for r in rows], [r.p for r in rows])
    np_of_p = Curve([r.p for r in rows], [r.np_pct for r in rows])
    w = [x[2] for x in opened]
    p_ref0 = sum(x[4] * wi for x, wi in zip(opened, w)) / sum(w)
    np0 = np_of_p(p_ref0)
    sw = {(x[0], x[1]): x[5] for x in st}
    cum_np = {(x[0], x[1]): 0.0 for x in st}         # отбор в нефтяном эквиваленте, м³ ст.
    extra = 0.0
    slice_q = {(x[0], x[1]): [] for x in st}
    out, cum_o, cum_l, stop, p_ref = [], 0.0, 0.0, "горизонт прогноза", p_ref0
    days = DAYS_IN_MONTH * k_oper
    for m in range(1, months + 1):
        p_ratio = p_ref / p_ref0
        eps = leak_at(m, leak, leak_growth)
        q_o = q_l = q_o_leak = q_l_leak = 0.0
        pot = {}
        for li, (c, z) in enumerate(zip(cases, zones)):
            mine = [x for x in st if x[0] == li]
            if not mine:
                continue
            p_over = [0.0] * len(c.slices)
            slices = list(c.slices)
            for x in mine:
                p_over[x[1]] = x[4] * p_ratio
                slices[x[1]] = replace(slices[x[1]], sw=sw[(li, x[1])], so=max(0.0, 1 - sw[(li, x[1])]))
            res = compute(replace(c, slices=slices), obj, pallets, z, l_total=l_tot, p_res_override=p_over)
            for x in mine:
                r = res[x[1]]
                qo, ql = max(r.q_oil, 0.0), max(r.q_liq, 0.0)
                mult = 1.0 if x[8] else eps
                pot[(li, x[1])] = (qo, ql, mult, r.pvt.get("bo", x[7]))
                q_o += mult * qo
                q_l += mult * ql
                if not x[8]:
                    q_o_leak += mult * qo
                    q_l_leak += mult * ql
        wc = 0.0 if q_l <= 0 else max(0.0, 100 - q_o / rho / q_l * 100)
        sw_avg = sum(sw[(x[0], x[1])] * x[2] for x in opened) / sum(w)
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
            key = (x[0], x[1])
            qo, ql, mult, bo = pot[key]
            slice_q[key].append((qo, ql, bo))
            d_np = mult * qo / rho * days              # м³ ст.
            d_wp = mult * max(ql - qo / rho, 0.0) * days
            cum_np[key] += d_np + d_wp * BW / bo
            sw[key] = min(sw[key] + vrr * d_np * bo / x[2], x[6])
        extra += extra_voidage * days
        np_eff = np0 + (1 - vrr) * 100 * (sum(cum_np.values()) + extra) / total_oip
        p_ref = max(p_of_np(np_eff), 1.0)
    return Forecast(out, total_oip * rho / 1000, stop, rho, slice_q, {(x[0], x[1]) for x in opened})
