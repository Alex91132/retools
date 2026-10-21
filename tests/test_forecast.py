# -*- coding: utf-8 -*-
"""Прогноз добычи для подобранной компоновки."""
from pathlib import Path

import pytest

from retools.completion import plan
from retools.forecast import DAYS_IN_MONTH, forecast
from retools.rigis_io import load_project

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def setup():
    case, obj, pal = load_project(FIX / "rigis_4210H_project.json")
    comp = plan(case, obj, pal, max_wc=5)
    return case, obj, pal, comp


def test_first_month_equals_completion_rate(setup):
    case, obj, pal, comp = setup
    f = forecast(case, obj, pal, comp, comp.l_total, months=3)
    assert f.months[0].q_oil == pytest.approx(comp.q_oil, rel=1e-9)
    assert f.months[0].p_res == pytest.approx(sum(r.p_res * s.h * s.phi for s, r in zip(case.slices, comp.slices)
                                                  if r.used and any(x.top <= s.top and s.bottom <= x.bottom
                                                                    for x in comp.filters)) /
                                              sum(s.h * s.phi for s, r in zip(case.slices, comp.slices)
                                                  if r.used and any(x.top <= s.top and s.bottom <= x.bottom
                                                                    for x in comp.filters)), rel=0.05)


def test_full_compensation_keeps_pressure(setup):
    case, obj, pal, comp = setup
    f = forecast(case, obj, pal, comp, comp.l_total, months=24, vrr=1.0)
    p = [m.p_res for m in f.months]
    assert max(p) - min(p) < 1e-9
    wc = [m.water_cut for m in f.months]
    assert wc[-1] > wc[0] + 10, "вода замещает отобранную нефть — обводнённость растёт"


def test_depletion_drops_pressure_without_water(setup):
    case, obj, pal, comp = setup
    f = forecast(case, obj, pal, comp, comp.l_total, months=12, vrr=0.0)
    p = [m.p_res for m in f.months]
    assert all(b <= a + 1e-9 for a, b in zip(p, p[1:])) and p[-1] < p[0]
    assert f.months[-1].sw == pytest.approx(f.months[0].sw, rel=1e-12)


def test_cumulative_is_sum_of_rates(setup):
    case, obj, pal, comp = setup
    f = forecast(case, obj, pal, comp, comp.l_total, months=12, vrr=0.5, k_oper=0.9)
    worked = [m for m in f.months if m.working]
    assert f.cum_oil == pytest.approx(sum(m.q_oil for m in worked) * DAYS_IN_MONTH * 0.9 / 1000, rel=1e-9)


def test_stops_at_minimum_rate(setup):
    case, obj, pal, comp = setup
    f = forecast(case, obj, pal, comp, comp.l_total, months=60, vrr=0.0, q_min=50)
    assert f.stop_reason == "дебит нефти ниже минимального"
    assert not f.months[-1].working and all(m.q_oil >= 50 for m in f.months if m.working)


def test_lower_bottomhole_pressure_extends_life(setup):
    from dataclasses import replace
    case, obj, pal, comp = setup
    low = replace(case, defaults=replace(case.defaults, p_wf=40.0))
    base = forecast(case, obj, pal, comp, comp.l_total, months=36, q_min=5)
    deep = forecast(low, obj, pal, comp, comp.l_total, months=36, q_min=5)
    assert deep.cum_oil > base.cum_oil


def test_no_leak_means_no_inflow_from_isolated_zones(setup):
    case, obj, pal, comp = setup
    f = forecast(case, obj, pal, comp, comp.l_total, months=6, vrr=0.5)
    assert all(m.q_liq_leak == 0 and m.q_oil_leak == 0 for m in f.months)
    assert f.cum_leak_liq == 0


def test_full_leak_equals_all_slices_potential(setup):
    """ε = 1: изолированные срезы отдают весь потенциал — первый месяц = сумма всех работающих срезов."""
    from retools.rigis import compute
    case, obj, pal, comp = setup
    f = forecast(case, obj, pal, comp, comp.l_total, months=1, leak=1.0)
    res = compute(case, obj, pal, l_total=comp.l_total)
    assert f.months[0].q_liq == pytest.approx(sum(r.q_liq for r in res if r.used), rel=1e-9)
    assert f.months[0].q_liq_leak == pytest.approx(f.months[0].q_liq - comp.q_liq, rel=1e-9)


def test_leak_grows_with_time_and_waters_out(setup):
    case, obj, pal, comp = setup
    tight = forecast(case, obj, pal, comp, comp.l_total, months=24, vrr=0.8)
    leaky = forecast(case, obj, pal, comp, comp.l_total, months=24, vrr=0.8, leak=0.05, leak_growth=0.1)
    eps = [m.leak for m in leaky.months]
    assert eps[0] == pytest.approx(0.05) and eps[12] == pytest.approx(0.15)
    assert leaky.cum_water > tight.cum_water and leaky.cum_leak_liq > 0
    assert leaky.months[0].water_cut > tight.months[0].water_cut


def test_water_withdrawal_lowers_pressure(setup):
    """Отбор воды тоже снимает пластовый объём: добавочный отбор быстрее сажает давление."""
    case, obj, pal, comp = setup
    a = forecast(case, obj, pal, comp, comp.l_total, months=12, vrr=0.0)
    b = forecast(case, obj, pal, comp, comp.l_total, months=12, vrr=0.0, extra_voidage=200.0)
    assert b.months[-1].p_res < a.months[-1].p_res
    assert len(a.slice_q) == sum(1 for r in comp.slices if r.used)
