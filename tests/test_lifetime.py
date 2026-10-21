# -*- coding: utf-8 -*-
"""Экономика компоновки и подбор на накопленную нефть / NPV."""
from pathlib import Path

import pytest

from retools.completion import evaluate_multi, liner, plan_multi
from retools.economics import Economics, capex, cash_flow, discount_factor, npv
from retools.forecast import forecast
from retools.lifetime import plan_lifetime, slice_weights
from retools.rigis import compute
from retools.rigis_io import load_project

FIX = Path(__file__).parent / "fixtures"
FKW = dict(months=60, vrr=0.8, k_oper=0.95, q_min=5)


@pytest.fixture(scope="module")
def setup():
    return load_project(FIX / "rigis_4210H_project.json")


def test_capex_counts_liner_on_full_span(setup):
    case, obj, pal = setup
    wc = plan_multi([case], obj, pal, max_wc=5)
    e = Economics(filter_m=1, blank_m=1, packer=0, fixed=0)
    used = [s for s, r in zip(case.slices, wc.laterals[0].slices) if r.used]
    cap = capex([case], wc, e)
    assert cap.filter_len + cap.blank_len + cap.packers * case.rules.elastomer == pytest.approx(
        used[-1].bottom - used[0].top, rel=1e-9)
    n_el = sum(len(i.packers) for i in wc.laterals[0].isolations)
    assert cap.packers == n_el
    e2 = Economics(filter_m=30, blank_m=10, packer=250, fixed=100)
    assert capex([case], wc, e2).total == pytest.approx(
        (cap.filter_len * 30 + cap.blank_len * 10 + n_el * 250 + 100) / 1000, rel=1e-12)


def test_all_open_capex_is_filter_only(setup):
    case, obj, pal = setup
    used = [(s.top, s.bottom) for s, r in zip(case.slices, compute(case, obj, pal)) if r.used]
    ao = evaluate_multi([case], obj, pal, [[(used[0][0], used[-1][1])]])
    cap = capex([case], ao, Economics())
    assert cap.packers == 0 and cap.blank_len == 0
    assert cap.filter_len == pytest.approx(used[-1][1] - used[0][0])


def test_npv_cash_flow(setup):
    case, obj, pal = setup
    wc = plan_multi([case], obj, pal, max_wc=5)
    fc = forecast(case, obj, pal, wc.laterals[0], wc.l_total, months=12, vrr=0.8)
    zero = Economics(oil_price=0, liquid_cost=0, water_cost=0)
    assert npv(fc, zero, 7.0) == pytest.approx(-7.0)
    e = Economics(oil_price=10000, liquid_cost=0, water_cost=0, discount=0)
    assert npv(fc, e) == pytest.approx(fc.cum_oil * 1000 * 10000 / 1e6, rel=1e-9)
    assert discount_factor(6.5, 10) == pytest.approx(1.1 ** -0.5)
    cf = cash_flow(fc, Economics())
    assert cf[-1]["npv"] == pytest.approx(npv(fc, Economics()), rel=1e-12)


def test_weights_sum_matches_forecast_without_leak(setup):
    """Без перетока и цены отбора сумма ценностей вскрытых срезов = накопленной нефти."""
    case, obj, pal = setup
    wc = plan_multi([case], obj, pal, max_wc=5)
    fc = forecast(case, obj, pal, wc.laterals[0], wc.l_total, **FKW)
    w = slice_weights([case], fc, "cum_oil", Economics())
    assert sum(w[0][k] for _, k in fc.opened) == pytest.approx(fc.cum_oil, rel=1e-9)


@pytest.mark.parametrize("objective", ["cum_oil", "npv"])
@pytest.mark.parametrize("max_wc", [5, 100])
def test_lifetime_not_worse_than_rate_plan(setup, objective, max_wc):
    case, obj, pal = setup
    lp = plan_lifetime([case], obj, pal, objective, Economics(), FKW, max_wc=max_wc)
    assert lp.score >= lp.base_score - 1e-9
    # ограничение по обводнённости фильтров — по начальным дебитам, как в подборе
    assert all(f.water_cut <= max_wc + 1e-6 for c in lp.wcomp.laterals for f in c.filters)


def test_lifetime_cuts_water_on_4210H(setup):
    """4210H, компенсация 0,8, 5 лет, без предела: меньше воды и больше нефти, чем «всё открыто»."""
    case, obj, pal = setup
    lp = plan_lifetime([case], obj, pal, "cum_oil", Economics(), FKW, max_wc=100)
    assert lp.forecast.cum_oil > lp.base_forecast.cum_oil + 1
    assert lp.forecast.cum_water < 0.9 * lp.base_forecast.cum_water
    assert lp.wcomp.q_oil < lp.base.q_oil      # ценой начального дебита
    assert len(lp.history) >= 2


def test_rate_objective_returns_rate_plan(setup):
    case, obj, pal = setup
    lp = plan_lifetime([case], obj, pal, "rate", Economics(), FKW, max_wc=5)
    assert lp.wcomp is lp.base and len(lp.history) == 1


def test_weights_param_reproduces_rate_plan(setup):
    case, obj, pal = setup
    a = plan_multi([case], obj, pal, max_wc=5)
    qo = [r.q_oil for r in compute(case, obj, pal, l_total=a.l_total)]
    b = plan_multi([case], obj, pal, max_wc=5, weights=[qo])
    assert [(f.top, f.bottom) for f in a.laterals[0].filters] == [(f.top, f.bottom) for f in b.laterals[0].filters]
