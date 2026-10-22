# -*- coding: utf-8 -*-
"""Подбор компоновки на максимум накопленной нефти или NPV за горизонт прогноза.

Подбор по начальному Qн (completion.plan_multi) не видит, что вскрытый
водонасыщенный срез со временем обводняет скважину, а нефтяной — истощается.
Здесь цель по срезам берётся из прогноза (forecast):

  ценность среза = Σ по месяцам (1 − ε)·(вклад среза − λ·отбор пластового объёма),

где вклад — добыча нефти (тыс. т) или дисконтированный денежный поток
(млн руб.), ε — доля перетока из изолированных зон (если срез не вскрыт, он
всё равно отдаёт ε своего потенциала), λ — цена отбора: на сколько падает цель
у всей скважины на 1 м³ отобранного пластового объёма из-за падения давления
(оценивается прогнозом с малым добавочным отбором). Через λ обводнённый срез
платит за воду, которая сажает давление остальным. Для NPV из ценности вычитается
удорожание метра фильтра против глухой трубы, а «цена» фильтра в ДП — два
пакера.

Прогноз зависит от выбранной компоновки (давление, обводнение срезов), поэтому
ценности уточняются итерациями: компоновка → прогноз → ценности срезов →
точный подбор (то же ДП, те же ограничения) → новая компоновка. Каждая
компоновка оценивается полным прогнозом, возвращается лучшая — не хуже
подбора по начальному Qн по той же оценке.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .completion import WellCompletion, plan_multi
from .economics import Capex, Economics, capex, daily_value, discount_factor, npv
from .forecast import BW, Forecast, forecast

OBJECTIVES = {
    "rate": "максимум начального Qн",
    "cum_oil": "максимум накопленной нефти",
    "npv": "максимум NPV",
}


@dataclass
class LifetimePlan:
    objective: str
    wcomp: WellCompletion
    forecast: Forecast
    score: float               # тыс. т или млн руб.
    capex: Capex
    base: WellCompletion       # подбор на начальный Qн
    base_forecast: Forecast
    base_score: float
    base_capex: Capex
    history: list = field(default_factory=list)   # (шаг, цель, Qн нач., накопл. нефть)

    @property
    def unit(self) -> str:
        return "млн руб." if self.objective == "npv" else "тыс. т"


def _key(wc: WellCompletion):
    return tuple(tuple((round(f.top, 6), round(f.bottom, 6)) for f in c.filters) for c in wc.laterals)


def score(objective: str, fc: Forecast, cap: Capex, econ: Economics) -> float:
    """Оценка компоновки: NPV, млн руб., или накопленная нефть, тыс. т (и для «rate»)."""
    if objective == "npv":
        return npv(fc, econ, cap.total)
    return fc.cum_oil


def slice_weights(cases, fc: Forecast, objective: str, econ: Economics, lam: float = 0.0) -> list[np.ndarray]:
    """Ценность вскрытия каждого среза по прогнозу (тыс. т или млн руб.); lam — цена
    отбора 1 м³ пластового объёма (нефтяной эквивалент) в тех же единицах."""
    worked = [m for m in fc.months if m.working]
    out = []
    for li, c in enumerate(cases):
        w = np.zeros(len(c.slices))
        if objective == "npv":
            w -= np.array([s.h for s in c.slices]) * (econ.filter_m - econ.blank_m) / 1000
        out.append(w)
    for (li, k), series in fc.slice_q.items():
        v = 0.0
        for m, t in zip(worked, series):
            qo, ql, bo = t[:3]
            e_closed = t[3] if len(t) > 3 else m.leak   # доля, которую срез отдал бы закрытым (пакеры и пласт)
            gain = (1 - e_closed) * m.days
            void = qo / fc.rho + max(ql - qo / fc.rho, 0.0) * BW / bo
            if objective == "npv":
                v += gain * daily_value(qo, ql, fc.rho, econ) / 1e6 * discount_factor(m.month, econ.discount)
            else:
                v += gain * qo / 1000
            v -= gain * lam * void
        out[li][k] += v
    return out


def plan_lifetime(cases, obj, pallets, objective: str = "cum_oil", econ: Economics | None = None,
                  forecast_kw: dict | None = None, forecast_cases=None, iterations: int = 6,
                  **plan_kw) -> LifetimePlan:
    """Компоновка на максимум цели за горизонт прогноза.

    forecast_kw — параметры forecast (months, vrr, k_oper, q_min, wc_max, leak,
    leak_growth); forecast_cases — стволы для прогноза, если в нём другое Рзаб;
    plan_kw — параметры plan_multi (ограничения те же). filter_cost в plan_kw —
    минимальный прирост Qн на фильтр, т/сут: для накопленной нефти переводится
    в тыс. т за рабочие сутки горизонта, для NPV «цена» фильтра — два пакера.
    """
    econ = econ or Economics()
    fkw = dict(forecast_kw or {})
    fkw.setdefault("zones", plan_kw.get("zones"))
    fcases = forecast_cases or cases
    min_gain = plan_kw.pop("filter_cost", 0.0)

    def run(wc, extra=0.0):
        fc = forecast(fcases, obj, pallets, wc.laterals, wc.l_total, extra_voidage=extra, **fkw)
        cap = capex(cases, wc, econ)
        return fc, cap, score(objective, fc, cap, econ)

    def voidage_price(wc, fc, s):
        """λ: потеря цели на 1 м³ добавочного отбора (конечная разность по прогнозу)."""
        work = [m for m in fc.months if m.working]
        if not work:
            return 0.0
        d = max(0.1 * work[0].q_liq, 1.0)
        _, _, s2 = run(wc, d)
        return max(0.0, (s - s2) / (d * sum(m.days for m in work)))

    base = plan_multi(cases, obj, pallets, filter_cost=min_gain, **plan_kw)
    base_fc, base_cap, base_s = run(base)
    best = (base_s, base, base_fc, base_cap)
    history = [(0, base_s, base.q_oil, base_fc.cum_oil)]
    if objective != "rate":
        seen, cur, cur_wc, cur_s = {_key(base)}, base_fc, base, base_s
        for it in range(1, iterations + 1):
            weights = slice_weights(fcases, cur, objective, econ, voidage_price(cur_wc, cur, cur_s))
            if objective == "npv":
                cost = 2 * econ.packer / 1000
            else:
                cost = min_gain * sum(m.days for m in cur.months if m.working) / 1000
            cand = plan_multi(cases, obj, pallets, weights=weights, filter_cost=cost, **plan_kw)
            if _key(cand) in seen:
                break
            seen.add(_key(cand))
            fc, cap, s = run(cand)
            history.append((it, s, cand.q_oil, fc.cum_oil))
            if s > best[0] + 1e-9:
                best = (s, cand, fc, cap)
            if fc.months:
                cur, cur_wc, cur_s = fc, cand, s
    s, wc, fc, cap = best
    return LifetimePlan(objective, wc, fc, s, cap, base, base_fc, base_s, base_cap, history)
