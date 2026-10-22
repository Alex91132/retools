# -*- coding: utf-8 -*-
"""Баклей–Леверетт, предел Дитца, перетоки вдоль ствола и их работа в подборе и прогнозе."""
import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from retools.completion import manual_plan, plan_multi
from retools.dynamics import bl_table, crossflow_eps, dietz_critical_rate, gravity_number
from retools.forecast import forecast
from retools.rigis import compute
from retools.rigis_io import load_project

FIX = Path(__file__).parent / "fixtures"
COREY_W = lambda s: np.asarray(s) ** 2           # noqa: E731
COREY_O = lambda s: (1 - np.asarray(s)) ** 2     # noqa: E731


def test_bl_front_matches_analytic_corey():
    """Кори n = 2, M = 1: фронт Sf = 1/√2, прорыв при Qi = 2√2 − 2."""
    t = bl_table(COREY_W, COREY_O, 1.0, 1.0, 0.0, 1.0, n=4001)
    assert t.s_f == pytest.approx(1 / math.sqrt(2), abs=5e-4)
    assert t.qi_bt == pytest.approx(2 * math.sqrt(2) - 2, rel=1e-5)
    assert t.outlet(0.5) == 0.0 and t.outlet(2.0) > t.s_f


def test_welge_average_equals_produced_oil():
    """Средняя насыщенность по Велджу = интеграл добычи нефти (1 − f на выходе) по Qi."""
    t = bl_table(COREY_W, COREY_O, 1.0, 1.0, 0.0, 1.0, n=4001)
    qs = np.linspace(0, 2.0, 20001)
    fo = [1 - t.frac(t.outlet(q)) if q >= t.qi_bt else 1.0 for q in qs]
    assert np.trapz(fo, qs) == pytest.approx(t.average(2.0) - t.s_i, rel=1e-3)


def test_gravity_delays_breakthrough():
    q = [bl_table(COREY_W, COREY_O, 1.0, 1.0, 0.0, 1.0, ng=ng).qi_bt for ng in (0, 0.5, 2, 5)]
    assert all(b > a for a, b in zip(q, q[1:]))


def test_dietz_critical_rate():
    assert dietz_critical_rate(10, 1000, 200, 0.4, 0.5, 0.8, 10) == pytest.approx(
        gravity_number(10, 1000, 200, 1.0, 1.0) * 0.4 / 0.5 / ((0.4 / 0.5) / (0.8 / 10) - 1), rel=1e-12)
    assert math.isinf(dietz_critical_rate(10, 1000, 200, 0.1, 1.0, 0.8, 1.0))   # M ≤ 1 — устойчиво


@pytest.fixture(scope="module")
def well():
    case, obj, pal = load_project(FIX / "rigis_4210H_project.json")
    wc = plan_multi([case], obj, pal, max_wc=5)
    return case, obj, pal, wc


def _open_mask(case, comp):
    return [any(f.top <= s.top and s.bottom <= f.bottom for f in comp.filters) for s in case.slices]


def test_crossflow_barrier_distance_and_switch(well):
    case, obj, pal, wc = well
    res = compute(case, obj, pal, l_total=wc.l_total)
    om = _open_mask(case, wc.laterals[0])
    eps = crossflow_eps(case.slices, res, om, case.defaults.kv_kh)
    closed = [i for i, r in enumerate(res) if r.used and not om[i]]
    assert any(eps[i] > 0.9 for i in closed) and any(eps[i] < 1e-3 for i in closed)
    assert all(e == 0 for e in crossflow_eps(case.slices, res, om, case.defaults.kv_kh, trans_mult=0))
    # барьер: проницаемость соседних срезов → 0 — переток пропадает
    i = max(closed, key=lambda j: eps[j])
    sl = [replace(s, perm=0.0) if abs(k - i) == 1 else s for k, s in enumerate(case.slices)]
    assert crossflow_eps(sl, res, om, case.defaults.kv_kh)[i] < 1e-3
    # слабая проводимость — переток меньше
    assert crossflow_eps(case.slices, res, om, case.defaults.kv_kh, trans_mult=1e-4)[i] < eps[i]


def test_plan_with_crossflow_not_worse_than_old_completion(well):
    """С перетоками подбор не хуже прежней компоновки, пересчитанной с перетоками."""
    case, obj, pal, wc = well
    old, _ = manual_plan([case], obj, pal, [[(f.top, f.bottom) for f in wc.laterals[0].filters]], max_wc=5,
                         crossflow=True)
    new = plan_multi([case], obj, pal, max_wc=5, crossflow=True)
    assert new.q_oil >= old.q_oil - 1e-9 and old.cross_liq > 0
    assert sum(i.cross_liq for i in old.laterals[0].isolations) == pytest.approx(old.cross_liq, rel=1e-12)
    strict = plan_multi([case], obj, pal, max_wc=0, crossflow=True)
    assert strict.q_oil > plan_multi([case], obj, pal, max_wc=0).q_oil       # изолированная нефть идёт перетоком


KW = dict(months=48, vrr=0.8, k_oper=0.95, q_min=5)


def _bt(f):
    return sorted(v["bt_w"] for v in f.slice_info.values() if v.get("opened") and v.get("bt_w"))


def test_bl_forecast_delays_watering(well):
    case, obj, pal, wc = well
    pist = forecast(case, obj, pal, wc.laterals[0], wc.l_total, **KW)
    bl = forecast(case, obj, pal, wc.laterals[0], wc.l_total, displacement="bl", **KW)
    assert _bt(bl) and min(_bt(bl)) > 6                     # фронт с латерали приходит не сразу
    assert bl.months[5].water_cut < pist.months[5].water_cut
    assert bl.cum_water < pist.cum_water
    dep = forecast(case, obj, pal, wc.laterals[0], wc.l_total, displacement="bl", **dict(KW, vrr=0.0))
    assert not _bt(dep)                                      # без притока воды фронта нет


def test_owc_cone_depends_on_distance(well):
    case, obj, pal, wc = well
    near = forecast(case, obj, pal, wc.laterals[0], wc.l_total, displacement="bl", owc_tvd=1612, **KW)
    far = forecast(case, obj, pal, wc.laterals[0], wc.l_total, displacement="bl", owc_tvd=1650, **KW)
    assert _bt(near) and min(_bt(near)) <= 6 and not _bt(far)
    assert near.cum_water > far.cum_water
    v = [x for x in near.slice_info.values() if x.get("vertical") and x.get("opened")]
    assert v and all(x["q_crit_w"] > 0 for x in v)


def test_gas_cap_breakthrough_near_goc(well):
    case, obj, pal, wc = well
    kw = dict(KW, vrr=0.0, months=24)
    f = forecast(case, obj, pal, wc.laterals[0], wc.l_total, displacement="bl", goc_tvd=1606, **kw)
    assert any(v.get("bt_g") for v in f.slice_info.values() if v.get("opened"))
    g = forecast(case, obj, pal, wc.laterals[0], wc.l_total, displacement="bl", goc_tvd=1500, **kw)
    assert not any(v.get("bt_g") for v in g.slice_info.values())
