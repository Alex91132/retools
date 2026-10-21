# -*- coding: utf-8 -*-
"""Тесты палетки нормировки Jd на золотых числах листа «Нормировка Jd ГС по секциям»."""
import json
import math
from pathlib import Path

from retools.jd_pallets import Pallet, default_pallet

FIXTURE = Path(__file__).parent / "jd_pallets_fixture.json"


def golden_rows():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["rows"]


def test_pallet_fixture_loaded():
    p = default_pallet()
    assert len(p.pairs) == 55
    assert math.isclose(p.pairs[0][0], 0.05)
    assert len(p.jd_grid) == len(p.l_norm_targets) == 17


def test_ratio_matches_sheet_rows():
    """Строки матрицы для Lгс=0.05 и Lгс=0.10 совпадают с листом бит-в-бит."""
    p = default_pallet()
    rows = golden_rows()
    for l_gc, key in ((0.05, "5"), (0.10, "6")):
        got = p.row(l_gc)
        exp = rows[key]
        assert len(got) == len(exp)
        for g, e in zip(got, exp):
            assert math.isclose(g, e, rel_tol=1e-12), (l_gc, g, e)


def test_short_section_caps_at_one():
    """Секция длиннее целевого Jd — доля равна 1 (ограничение не требуется)."""
    p = default_pallet()
    assert p.ratio(0.30, 0.004, 0.10, 0.0027) == 1.0


def test_matrix_full():
    p = default_pallet()
    m = p.matrix()
    assert set(m) == {round(lg, 6) for lg, _ in p.pairs}
    assert all(math.isclose(v, 1.0) for v in m[3.7])  # длинные секции не режутся
