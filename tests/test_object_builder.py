# -*- coding: utf-8 -*-
"""Объект разработки и палетки секций ГС из параметров — против кэша книги."""
import json
from pathlib import Path

import pytest

from retools.object_builder import (JdPalletSettings, build_jd_pallets, build_object, jd_settings_from_object,
                                    mbe_table, pressure_grid)
from retools.rigis import Regressions, compute
from retools.rigis_io import load_project

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def project():
    return load_project(FIX / "rigis_4210H_project.json")


@pytest.fixture(scope="module")
def book():
    return json.loads((FIX / "rigis_4210H_expected.json").read_text(encoding="utf-8"))


def test_pressure_grid_as_book(project, book):
    _, obj, _ = project
    grid = pressure_grid(obj.params["depth"], obj.params["pb"])
    assert grid == pytest.approx([r[0] for r in book["mbe_book"]["rows"]], rel=1e-14)


def test_mbe_matches_book_where_goalseek_converged(project, book):
    """Строки 3–20 (P ≥ 137 атм): невязка книги ~0 — совпадение с решением до 1e-9."""
    _, obj, _ = project
    rows = mbe_table(obj.params)
    cols = dict(rs=1, bo=2, bg=3, ct=4, np_pct=8, gor=14, so=15, sg=16)
    for r, ref in zip(rows, book["mbe_book"]["rows"]):
        if abs(ref[9]) > 1e-9:          # столбец N — невязка «Подбора параметра» в книге
            continue
        for k, j in cols.items():
            assert getattr(r, k) == pytest.approx(ref[j], rel=1e-9, abs=1e-12), (k, r.p)


def test_book_goalseek_did_not_converge_below_124_atm(book):
    """Находка: ниже ~124 атм книга хранит несошедшийся «Подбор параметра»."""
    resid = {round(r[0], 1): r[9] for r in book["mbe_book"]["rows"]}
    assert abs(resid[10.0]) > 100 and abs(resid[123.5]) > 0.5


def test_mbe_solution_has_zero_residual_everywhere(project):
    _, obj, _ = project
    for r in mbe_table(obj.params):
        assert 0 <= r.sg < 1 and 0 < r.so < 1
    ps = [r.np_pct for r in mbe_table(obj.params)]
    assert all(b >= a for a, b in zip(ps, ps[1:])), "отбор растёт при падении давления"


def test_jd_pallets_from_book_settings_match_book(project, book):
    _, _, pal = project
    s = JdPalletSettings(**book["jd_settings_book"])
    built = build_jd_pallets(s, pal.grids[0].xs)
    for g0, g1 in zip(pal.grids, built.grids):
        worst = max(abs(a - b) for r0, r1 in zip(g0.f, g1.f) for a, b in zip(r0, r1))
        assert worst < 1e-12


def test_jd_pallets_from_object_close_to_book(project):
    """Без книги (вязкость — смесь по Бейкеру при Swi) коэффициенты отличаются ≤ 0,002."""
    _, obj, pal = project
    s = jd_settings_from_object(obj)
    assert s.k == pytest.approx(26) and s.phi == pytest.approx(0.18)
    built = build_jd_pallets(s, pal.grids[0].xs)
    worst = max(abs(a - b) for g0, g1 in zip(pal.grids, built.grids) for r0, r1 in zip(g0.f, g1.f) for a, b in zip(r0, r1))
    assert worst < 2e-3


def test_object_from_parameters_runs_rigis(project):
    case, obj, pal = project
    built = build_object(obj.params, obj.npz_pallet, name="из параметров")
    case.regressions = Regressions()
    res = compute(case, built, pal)
    q = sum(r.q_oil for r in res)
    assert 0 < q < 2000
    # выше давления насыщения кривые совпадают с книгой — срезы при Рпл ≥ Pb не меняются
    assert built.ct(150) == pytest.approx(obj.ct(150), rel=1e-6)
