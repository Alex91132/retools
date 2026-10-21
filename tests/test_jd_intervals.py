# -*- coding: utf-8 -*-
"""Тесты Jd/трещины и модели интервалов."""
import math

from retools import Interval, WellIntervals, get_jd, get_x_f


def test_get_jd_basic():
    # 18.42 * 1 * 1 * J / (k*h): J=5, k*h=10 -> 9.21
    assert math.isclose(get_jd(1.0, 1.0, 2.0, 5.0, 5.0), 9.21, rel_tol=1e-12)


def test_get_jd_zero_kh():
    assert get_jd(1.0, 1.0, 0.0, 5.0, 5.0) == 0.0


def test_get_x_f_positive_skin_is_zero():
    # неотрицательный скин — не ГРП
    assert get_x_f(r_w=0.1, k_h=20.0, s=0.5, w_f=0.005, k_f=1e5) == 0.0


def test_get_x_f_negative_skin():
    xf = get_x_f(r_w=0.1, k_h=20.0, s=-3.0, w_f=0.005, k_f=1e5)
    assert xf > 0
    # для глубокого отрицательного скина длина растёт
    xf_deeper = get_x_f(r_w=0.1, k_h=20.0, s=-4.0, w_f=0.005, k_f=1e5)
    assert xf_deeper > xf


def test_intervals_totals():
    ws = WellIntervals(intervals=[
        Interval(h_eff=13.2, p_res=96, flood_share=0.7, r_contour=400,
                 inj_prod_ratio=0.5, oip=100.0),
        Interval(),  # пустой интервал не участвует
        Interval(h_eff=6.8, p_res=102, flood_share=0.5, r_contour=400,
                 inj_prod_ratio=0.5, oip=60.0),
    ])
    t = ws.totals()
    assert math.isclose(t["oip"], 160.0)
    assert math.isclose(t["h_eff"], 20.0)
    assert math.isclose(t["p_res_avg"], (96 * 13.2 + 102 * 6.8) / 20.0, rel_tol=1e-12)
    assert math.isclose(t["flood_share_avg"], (0.7 * 13.2 + 0.5 * 6.8) / 20.0, rel_tol=1e-12)


def test_intervals_empty():
    assert WellIntervals().totals()["oip"] == 0.0
