# -*- coding: utf-8 -*-
"""Модель вытеснения и палетки листа PVT_MBE_Waterflood (FDP_Functions) против кэша книги."""
import json
from pathlib import Path

import pytest

from retools.field_object import PARAM_ROWS
from retools.object_builder import build_object
from retools.rigis_io import load_project
from retools.waterflood import (DP_SCHEDULE, NPZ_GRID, WC_GRID, depletion_rows, fdp_pallets, flood_rows,
                                initial_pvt, pvt_rows, sw_axis, xl_round)

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def book():
    return json.loads((FIX / "pvt_mbe_book.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def params(book):
    return {k: book["D"][str(r)] for k, r in PARAM_ROWS.items() if k != "pvt_json"}


def _rel(a, b):
    return max(abs(x - y) / max(abs(y), 1e-12) for x, y in zip(a, b))


def test_axes_as_book(book, params):
    assert DP_SCHEDULE == book["table"]["AY"]
    assert sw_axis(params) == book["pallets"]["mu"]["x"]
    assert NPZ_GRID == book["pallets"]["kro_mix"]["y"]
    assert WC_GRID == book["pallets"]["npz"]["y"]


def test_initial_pvt(book, params):
    i = initial_pvt(params)
    a = book["aux"]
    for got, ref in ((i.boi, "BA20"), (i.bwi, "BA21"), (i.bgi, "BA22"), (i.muoi, "BA24"), (i.muwi, "BA25"), (i.cwi, "BA27")):
        assert got == pytest.approx(a[ref], rel=1e-12)


def test_flood_model_columns(book, params):
    """Z:AX — две единицы потока при базовом Swi: до 1e-12."""
    fl = flood_rows(params, params["swi"], initial_pvt(params))
    t = book["table"]
    for name, col in (("npz", "AC"), ("ngz", "AD"), ("sw", "AE"), ("kro_mix", "AF"), ("krw_mix", "AG"), ("wc", "AH"),
                      ("sw1", "AN"), ("np1", "AO"), ("sw2", "AV"), ("np2", "AW")):
        assert _rel([getattr(r, name) for r in fl], t[col]) < 1e-12, name


def test_depletion_columns(book, params):
    """T, U, W, X, BG, BH при столбце Np книги: до 1e-12."""
    t = book["table"]
    dep = depletion_rows(params, params["swi"], t["M"], pvt_rows(params), initial_pvt(params))
    for name, col in (("so", "T"), ("sg", "U"), ("kro", "W"), ("krw", "X"), ("mu", "BG"), ("wc", "BH")):
        assert _rel([getattr(r, name) for r in dep], t[col]) < 1e-12, name


@pytest.mark.parametrize("name", ["mu", "sg", "wc", "kro_mix", "krw_mix", "wc_mix", "npz"])
def test_fdp_pallets_match_book(book, params, name):
    """Все семь палеток макроса FDP_Functions: до 1e-12 (Np — столбец M книги)."""
    fp = fdp_pallets(params, book["table"]["M"])
    got, ref = getattr(fp, name), book["pallets"][name]["f"]
    assert max(abs(a - b) for rg, rr in zip(got, ref) for a, b in zip(rg, rr)) < 1e-12


def test_built_object_npz_pallet_equals_project(book):
    """Объект 4210H из параметров: палетка НПЗ (для НИЗ от ППД в РИГИС) — как в книге."""
    _, obj, _ = load_project(FIX / "rigis_4210H_project.json")
    built = build_object(obj.params)
    g, ref = built.npz_pallet, obj.npz_pallet
    assert max(abs(g(x, y) - ref(x, y)) for x in ref.xs for y in ref.ys) < 1e-12


def test_xl_round_half_away_from_zero():
    assert xl_round(0.3005, 3) == 0.301 and xl_round(-0.0025, 3) == -0.003 and xl_round(0.30049, 3) == 0.3
