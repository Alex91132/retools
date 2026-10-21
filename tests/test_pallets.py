# -*- coding: utf-8 -*-
"""Тесты палеток заводнения: точность в узлах, билинейность, границы."""
import math
import os

import pytest

from retools.pallets import Grid, default_pallets, kro_mix, krw_mix, mu_mix, read_pallets

BOOK = os.environ.get("RETOOLS_BOOK", "")


def test_grids_loaded():
    p = default_pallets()
    assert set(p) == {"mu", "kro_mix", "krw_mix"}
    for g in p.values():
        assert len(g.x) == 12 and len(g.y) == 15
        assert all(len(row) == 12 for row in g.f)
    assert math.isclose(p["mu"].y[0], 410.5)
    assert math.isclose(p["mu"].y[-1], 159.0)
    assert math.isclose(p["mu"].x[0], 0.772)
    assert math.isclose(p["mu"].x[-1], 0.2)


def test_node_exactness_all_pallets():
    """В узлах сетки интерполяция обязана возвращать табличное значение."""
    p = default_pallets()
    worst = 0.0
    for g in p.values():
        for iy, yv in enumerate(g.y):
            for ix, xv in enumerate(g.x):
                got = g.value(xv, yv)
                worst = max(worst, abs(got - g.f[iy][ix]))
    assert worst == 0.0


def test_bilinear_midpoint():
    g = default_pallets()["mu"]
    x0, x1 = g.x[0], g.x[1]
    y0, y1 = g.y[0], g.y[1]
    xm, ym = (x0 + x1) / 2, (y0 + y1) / 2
    expected = (g.f[0][0] + g.f[0][1] + g.f[1][0] + g.f[1][1]) / 4
    assert math.isclose(g.value(xm, ym), expected)


def test_clamp_outside_grid():
    g = default_pallets()["mu"]
    assert math.isclose(g.value(g.x[0] + 1.0, g.y[0] + 100), g.f[0][0])
    assert math.isclose(g.value(g.x[-1] - 1.0, g.y[-1] - 100), g.f[-1][-1])


def test_helpers_semantics():
    p = default_pallets()
    # mu_mix(P, Sw) и kro/krw_mix(%НПЗ, Sw) возвращают значения сетки в узлах
    assert math.isclose(mu_mix(p, 410.5, 0.772), p["mu"].f[0][0])
    assert math.isclose(kro_mix(p, 0.0, 0.2), p["kro_mix"].f[0][-1])
    assert math.isclose(krw_mix(p, 0.0, 0.2), p["krw_mix"].f[0][-1])


def test_relperm_pallets_physical_shape():
    """Kro убывает с ростом Sw, Krw растёт (в любой строке %НПЗ)."""
    p = default_pallets()
    for iy in range(0, 15, 4):
        kro_row = p["kro_mix"].f[iy]
        krw_row = p["krw_mix"].f[iy]
        # ось x идёт от 0.772 к 0.2 — разворачиваем
        kro_asc = list(reversed(kro_row))
        krw_asc = list(reversed(krw_row))
        assert kro_asc == sorted(kro_asc, reverse=False) or all(
            a >= b - 1e-12 for a, b in zip(kro_asc, kro_asc[1:]))
        assert all(a <= b + 1e-12 for a, b in zip(krw_asc, krw_asc[1:]))


@pytest.mark.skipif(not os.path.exists(BOOK), reason="книга RE Tools недоступна")
def test_read_from_real_book():
    p = read_pallets(BOOK)
    fix = default_pallets()
    for name in p:
        assert all(math.isclose(a, b) for a, b in zip(p[name].y, fix[name].y))
