# -*- coding: utf-8 -*-
"""Расчёт РИГИС по срезам: сверка с кэшем книги RE Tools (скважина 4210H).

Кэш формул R:CE листа РИГИС заморожен макросом CalculateRIGIS при выключенных
регрессиях петрофизики — поэтому в сверке они выключены.
"""
import json
from dataclasses import replace
from pathlib import Path

import pytest

from retools import rigis_physics as ph
from retools.rigis import Regressions, Slice, assign_intervals, compute
from retools.rigis_io import load_project

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def project():
    case, obj, pal = load_project(FIX / "rigis_4210H_project.json")
    case.regressions = Regressions()
    return case, obj, pal


@pytest.fixture(scope="module")
def expected():
    return json.loads((FIX / "rigis_4210H_expected.json").read_text(encoding="utf-8"))


def test_slices_loaded(project):
    case, _, _ = project
    assert len(case.slices) == 219
    assert case.slices[0].top == pytest.approx(2708.8)
    assert case.intervals[0].top == 2938 and case.intervals[0].bottom == 3248


@pytest.mark.parametrize("field", ["q_liq", "fw", "q_oil", "gor", "oip", "rec", "jd", "sg", "so", "kro", "krg", "krw",
                                   "mu", "ct", "b", "pi", "dp", "l_total", "k_section", "kvo", "kno", "kvcr",
                                   "h_eff", "p_res"])
def test_matches_book_slice_by_slice(project, expected, field):
    case, obj, pal = project
    res = compute(case, obj, pal)
    ref = expected["expected"][field]
    for i, (r, e) in enumerate(zip(res, ref)):
        assert getattr(r, field) == pytest.approx(e, rel=1e-9, abs=1e-12), f"срез {i} (D={case.slices[i].top})"


def test_totals_match_book(project, expected):
    case, obj, pal = project
    res = compute(case, obj, pal)
    assert sum(r.q_liq for r in res) == pytest.approx(expected["meta"]["sum_all"]["q_liq"], rel=1e-12)
    assert sum(r.q_oil for r in res) == pytest.approx(expected["meta"]["sum_all"]["q_oil"], rel=1e-12)


def test_regressions_change_petrophysics(project):
    """С регрессиями объекта (текущие настройки книги) Кво/Кно зависят от Кп/Кпр."""
    case, obj, pal = project
    with_regr = replace(case, regressions=Regressions(0.04857, 0.30843, 2.5833, 0.94383, 0.0174, 0.8691, 11))
    res = compute(with_regr, obj, pal)
    kvo = {round(r.kvo, 6) for r in res}
    assert len(kvo) > 10


def test_pgmc_zone_does_not_produce(project):
    case, obj, pal = project
    res = compute(case, obj, pal)
    for s, r in zip(case.slices, res):
        if s.bottom <= case.rules.pgmc_bottom:
            assert r.q_liq == 0 and not r.used


def test_assign_intervals():
    sl = [Slice("w", "p", 10, 11), Slice("w", "p", 20, 21), Slice("w", "p", 30, 31)]
    assert assign_intervals(sl, [(15, 25), (29, 40)]) == [0, 1, 2]


def test_vertical_well_option(project):
    case, obj, pal = project
    vert = replace(case, well_type="vertical")
    res = compute(vert, obj, pal)
    assert all(r.k_section in (0.0, 1.0) for r in res)
    assert sum(r.q_liq for r in res) > 0


# --- физика -------------------------------------------------------------------

def test_dp_above_bubble_point_is_simple_drawdown():
    assert ph.get_dp(pb=100, pwf=120, f_w=30, pr=200) == pytest.approx(80)


def test_dp_water_only():
    assert ph.get_dp(pb=150, pwf=50, f_w=100, pr=200) == pytest.approx(150)


def test_vertical_steady_state_pd():
    # установившийся режим: ln(re/rw) + s
    assert ph.pd_vertical(1000.0, 0.5, 1e9) == pytest.approx(__import__("math").log(1000.0) + 0.5)


def test_productivity_grows_with_length():
    j = [ph.get_j_obsolete(0.1, 0.2, l, 5, 300, 0.1, 15, 100, 0, 2.0, 1e-4, 1.1) for l in (10, 50, 200)]
    assert j[0] < j[1] < j[2]


def test_fw_bounds():
    assert ph.fw_from_kr(0.5, 5, 1.1, 1.0, 0.0, 0.5) == 0
    assert 0 < ph.fw_from_kr(0.5, 5, 1.1, 1.0, 0.2, 0.5) < 100
