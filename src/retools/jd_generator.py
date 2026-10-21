# -*- coding: utf-8 -*-
"""Генератор нормированных длин Lнорм(Lгс) для палетки Jd.

Порт детерминированной цепочки VBA (c__Productivity.bas → c11____WellTest_func.bas)
для случая палетки листа «Нормировка Jd ГС по секциям»:
ГС без ГРП, скин 0, границы пласта — постоянное давление (cccc), кровля/подошва —
непроницаемые, расчёт дебита при постоянном забойном давлении (Штехфест N=10).

Лапласово ядро (pd_lapl_rect + члены f/F_b) переиспользуется из пакета
reservoir_core (портировано из родственного ноутбука с parity-тестами):
horizontal_rect_lapl реализует путь Calc_Option=1 (точка 0.68, Rosa-Carvalho).

Спецификация аргументов и эталоны: docs/jd_pallets_spec.md,
tests/jd_pallets_fixture.json.
"""
from __future__ import annotations

import math

PI = math.pi

# Параметры контрольного примера книги (кэш листа «Нормировка Jd ГС по секциям»)
DEFAULTS = dict(
    kv_kh=0.1,                 # GF1: kz/kh
    phi=0.18,                  # FI1: пористость
    t_p=60.0,                  # FT1: время, сут
    r_e=350.0,                 # FX1: радиус дренирования, м
    r_w=0.07,                  # радиус скважины, м
    h=1.0,                     # CY5: мощность в нормировке
    k_h=26.0,                  # FE1: проницаемость, мД
    mu=13.699249282013303,     # ES1: вязкость, сПз
    c_t=1.4315427414884497e-4, # FM1: сжимаемость, 1/атм
    b=1.0755417140124952,      # EW1: объёмный коэффициент
    kh_total=650.0,            # FE1*FA1 = 26*25 для Get_Jd
    n_stehfest=10,             # number_of_lapl_coeff
)


def _kernel():
    try:
        from reservoir_core.laplace.kernels import horizontal_rect_lapl
        from reservoir_core.laplace.stehfest import stefest_coefficients
    except ImportError as e:  # pragma: no cover
        raise ImportError(
            "Генератор требует пакет reservoir_core (ядро Laplace из родственного "
            "проекта): pip install -e ../reservoir-core"
        ) from e
    return horizontal_rect_lapl, stefest_coefficients


def get_l_norm(l_gc: float, **kw) -> float:
    """Lнорм для заданной эффективной длины ГС (сетка колонки B листа).

    Полная цепочка: Батлер (соотношение сторон) → прямоугольник дренирования →
    DefineGeometry/DimensionlessGeometry (ГС) → Штехфест-цикл дебита → Get_Jd.
    Возвращает Jd = q_D (нормированная безразмерная продуктивность).
    """
    p = {**DEFAULTS, **kw}
    horizontal_rect_lapl, stefest_coefficients = _kernel()

    # --- Get_J: оптимальное соотношение сторон по Батлеру.
    # ВАЖНО (порядок VBA): аспект считается по ИСХОДНОЙ длине l_hor = B5/GJ1
    # ДО подстановки l_hor = l_hor_effective (замена выполняется позже в Get_J).
    l_hor = l_gc / 0.7
    s_drainage = PI * p["r_e"] ** 2
    aspect = 1 + l_hor ** 2 / s_drainage
    w = p["r_e"] * math.sqrt(aspect * PI)   # ширина прямоугольника дренирования
    l = p["r_e"] * math.sqrt(PI / aspect)   # длина

    # --- подстановка эффективной длины (для ГС: l_hor = l_hor_effective)
    l_hor = l_gc

    # --- DefineGeometry (compl_type="horizontal", wf=lf=0.5, zw_h=0.5)
    unit_length = l_hor / 2
    xw0, yw0 = w * 0.5, l * 0.5
    xe, ye, ze = w, l, p["h"]
    zw0 = ze * 0.5
    x_pt, y_pt, z_pt = xw0, yw0, zw0          # r = 0 для ГС

    # --- DimensionlessVariables (t в часах)
    t = p["t_p"] * 24
    multq = p["k_h"] * p["h"] / (18.42 * p["b"] * p["mu"])
    mult_t = p["c_t"] * p["phi"] * p["mu"] * unit_length ** 2 / 0.00036 / p["k_h"]
    td = t / mult_t

    # --- DimensionlessGeometry (s_kv = sqrt(kv/kh))
    s_kv = math.sqrt(p["kv_kh"])
    xd = x_pt / unit_length
    yd = y_pt / unit_length
    zd = z_pt / unit_length / s_kv
    xwd = xw0 / unit_length
    ywd = yw0 / unit_length
    zwd = zw0 / unit_length / s_kv
    xed = xe / unit_length
    yed = ye / unit_length
    zed = ze / unit_length / s_kv
    rwd = p["r_w"] * (1 + 1 / s_kv) / 2 / unit_length

    # --- PD_QD_QTD_U: Штехфест-цикл, дебит при постоянном забойном (mode=1)
    v = stefest_coefficients(p["n_stehfest"])
    ln2 = math.log(2.0)
    sum_r1 = 0.0
    for j in range(1, p["n_stehfest"] + 1):
        sj = j * ln2 / td
        pd = horizontal_rect_lapl(sj, xd, yd, zd, xwd, ywd, zwd, xed, yed, zed, rwd)
        sum_r1 += (v[j - 1] / j) / (pd * (2 * PI / sj) * sj)   # q_d·s = 2π
    q_d = sum_r1                                                # avg_flag = 0

    # --- Get_J → Get_Jd (скин 0, член skin/(2π)·zed/2 выпадает)
    j_real = multq * q_d
    return 18.42 * p["mu"] * p["b"] * j_real / p["kh_total"]


def generate_pairs(l_grid=None, **kw) -> list[tuple[float, float]]:
    """Прогнать сетку длин ГС → пары (Lгс, Lнорм) для палетки."""
    if l_grid is None:
        l_grid = [round(0.05 * i, 10) for i in range(1, 41)]     # 0.05 … 2.0
    return [(lg, get_l_norm(lg, **kw)) for lg in l_grid]
