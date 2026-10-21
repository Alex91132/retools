# -*- coding: utf-8 -*-
"""Табличная интерполяция в поведении RE Tools (alglib через Unifloc).

- ``interp1`` — порт ``crv_interpolation(..., type=0)``: CInterpolation.AddPoint
  (для повторяющегося аргумента остаётся последнее значение) →
  Spline1DBuildLinear (точки сортируются по x) → Spline1DCalc: линейно внутри,
  за краями — продолжение крайнего отрезка (линейная экстраполяция).
- ``interp2`` — порт ``crv_interpolation_2D(..., type=0)`` → Spline2DBuildBilinear /
  Spline2DCalc: билинейно по ячейке, за краями сетки — продолжение крайней ячейки.

Отличие от ``pallets.Grid.value``: там вне сетки значение прижимается к краю;
здесь — как в книге (это важно для сверки расчёта РИГИС срез за срезом).
"""
from __future__ import annotations

from bisect import bisect_right
from typing import Sequence


def _segment(xs: Sequence[float], x: float) -> int:
    """Индекс левой точки отрезка для x (за краями — крайний отрезок)."""
    i = bisect_right(xs, x) - 1
    return min(max(i, 0), len(xs) - 2)


class Curve:
    """Кусочно-линейная функция по таблице (x, y)."""

    def __init__(self, xs: Sequence[float], ys: Sequence[float]):
        pts: dict[float, float] = {}
        for x, y in zip(xs, ys):
            if x is None or y is None:
                continue
            pts[float(x)] = float(y)          # повторный аргумент — последнее значение
        if not pts:
            raise ValueError("пустая таблица для интерполяции")
        self.xs = sorted(pts)
        self.ys = [pts[x] for x in self.xs]

    def __call__(self, x: float) -> float:
        xs, ys = self.xs, self.ys
        if len(xs) == 1:
            return ys[0]
        i = _segment(xs, x)
        x0, x1 = xs[i], xs[i + 1]
        return ys[i] + (ys[i + 1] - ys[i]) * (x - x0) / (x1 - x0)


def interp1(xs: Sequence[float], ys: Sequence[float], x: float) -> float:
    return Curve(xs, ys)(x)


class Grid2D:
    """Билинейная интерполяция по регулярной сетке: f[iy][ix] при осях x, y."""

    def __init__(self, xs: Sequence[float], ys: Sequence[float], f: Sequence[Sequence[float]]):
        xi = sorted(range(len(xs)), key=lambda i: xs[i])
        yi = sorted(range(len(ys)), key=lambda i: ys[i])
        self.xs = [float(xs[i]) for i in xi]
        self.ys = [float(ys[i]) for i in yi]
        self.f = [[float(f[j][i] or 0.0) for i in xi] for j in yi]

    def __call__(self, x: float, y: float) -> float:
        ix, iy = _segment(self.xs, x), _segment(self.ys, y)
        x0, x1 = self.xs[ix], self.xs[ix + 1]
        y0, y1 = self.ys[iy], self.ys[iy + 1]
        tx = (x - x0) / (x1 - x0)
        ty = (y - y0) / (y1 - y0)
        f = self.f
        return ((1 - tx) * (1 - ty) * f[iy][ix] + tx * (1 - ty) * f[iy][ix + 1]
                + (1 - tx) * ty * f[iy + 1][ix] + tx * ty * f[iy + 1][ix + 1])
