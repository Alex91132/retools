# -*- coding: utf-8 -*-
"""Экономика компоновки: стоимость хвостовика и NPV добычи по прогнозу.

Стоимость компоновки — по раскладке хвостовика (completion.liner) на одном и
том же интервале ствола (от первого до последнего работающего среза), чтобы
варианты сравнивались честно: фильтр и глухая труба — за метр, пакеры-
эластомеры — за штуку, плюс постоянная часть.

Денежный поток месяца — выручка за нефть по нетбэку минус затраты на подъём
жидкости и на подготовку/утилизацию воды; дисконтирование помесячное, на
середину месяца. Все цены — входные данные пользователя; значения по
умолчанию условные.
"""
from __future__ import annotations

from dataclasses import dataclass

from .completion import liner


@dataclass
class Economics:
    oil_price: float = 15000.0     # нетбэк нефти (за вычетом налогов и транспорта), руб./т
    liquid_cost: float = 150.0     # подъём жидкости, руб./м³
    water_cost: float = 80.0       # подготовка и утилизация (закачка) попутной воды, руб./м³
    filter_m: float = 30.0         # фильтр, тыс. руб./м
    blank_m: float = 10.0          # глухая труба, тыс. руб./м
    packer: float = 250.0          # пакер-эластомер, тыс. руб./шт
    fixed: float = 0.0             # прочее на компоновку (спуск, подвеска), тыс. руб.
    discount: float = 15.0         # ставка дисконтирования, %/год


@dataclass
class Capex:
    filter_len: float
    blank_len: float
    packers: int
    total: float                   # млн руб.


def liner_span(c):
    """Интервал хвостовика ствола: от первого до последнего работающего среза."""
    used = [k for k, r in enumerate(c.slices) if r.used]
    return used[0], used[-1]


def capex(cases, wcomp, econ: Economics) -> Capex:
    """Стоимость компоновки скважины (все стволы), млн руб."""
    fl = bl = 0.0
    n = 0
    for case, c in zip(cases, wcomp.laterals):
        if not c.filters or not any(r.used for r in c.slices):
            continue
        a, b = liner_span(c)
        top = min(case.slices[a].top, c.filters[0].top)
        bottom = max(case.slices[b].bottom, c.filters[-1].bottom)
        for e in liner(c, case.rules, top, bottom):
            if e.kind == "фильтр":
                fl += e.length
            elif e.kind == "эластомер":
                n += 1
            else:
                bl += e.length
    if fl == 0:
        return Capex(0.0, 0.0, 0, 0.0)
    total = (fl * econ.filter_m + bl * econ.blank_m + n * econ.packer + econ.fixed) / 1000
    return Capex(fl, bl, n, total)


def daily_value(q_oil: float, q_liq: float, rho: float, econ: Economics) -> float:
    """Денежный поток суток, руб.: нефть по нетбэку − подъём жидкости − подготовка воды."""
    water = max(q_liq - q_oil / rho, 0.0)
    return q_oil * econ.oil_price - q_liq * econ.liquid_cost - water * econ.water_cost


def discount_factor(month: int, rate: float) -> float:
    return (1 + rate / 100) ** (-(month - 0.5) / 12)


def cash_flow(fc, econ: Economics) -> list[dict]:
    """Помесячный денежный поток по прогнозу, млн руб."""
    out, acc = [], 0.0
    for m in fc.months:
        if not m.working:
            continue
        cf = daily_value(m.q_oil, m.q_liq, fc.rho, econ) * m.days / 1e6
        dcf = cf * discount_factor(m.month, econ.discount)
        acc += dcf
        out.append(dict(month=m.month, cf=cf, dcf=dcf, npv=acc))
    return out


def npv(fc, econ: Economics, capex_total: float = 0.0) -> float:
    """NPV за горизонт прогноза, млн руб. (компоновка — в момент 0)."""
    return sum(r["dcf"] for r in cash_flow(fc, econ)) - capex_total
