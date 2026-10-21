# -*- coding: utf-8 -*-
"""Тесты чтения и агрегации листа РИГИС.

Реальная книга — шаблон без данных (НГЗ срезов = 0), поэтому числовой паритет
проверяем на синтетике, а на книге — структуру и контрольный интервал-пример.
"""
import os
import math
import pytest

from retools.intervals_io import IntervalChoice, RigisData, read_rigis

BOOK = os.environ.get("RETOOLS_BOOK", "")


def synthetic() -> RigisData:
    """Два интервала, восемь срезов: известные суммы и средние."""
    def sl(depth, code, h, oip, pres, qliq=0.0, coll="К"):
        return {"depth": depth, "collector": coll, "thick_to_interval": h,
                "code": code, "ues": 11.0, "qliq": qliq, "fw": 0.0,
                "qoil": qliq * 0.9, "gor": 0.0, "oip": oip, "rec_oip": oip * 0.35,
                "h_eff": h, "p_res": pres}
    d = RigisData(intervals=[
        IntervalChoice(n=1, top=3000, bottom=3010, h_eff=6, p_res=250),
        IntervalChoice(n=2, top=3100, bottom=3110, h_eff=4, p_res=260),
    ], slices=[
        sl(3000, 1, 2.0, 100, 250, 50), sl(3002, 1, 2.0, 150, 252, 60),
        sl(3004, 1, 2.0, 200, 254, 70),
        sl(3006, 0, 2.0, 999, 999, 0, coll="н"),        # вне интервалов расчёта
        sl(3100, 2, 2.0, 40, 260, 20), sl(3102, 2, 2.0, 60, 262, 30),
    ])
    return d


def test_aggregate_sums_and_weighted():
    a1 = synthetic().aggregate(1)
    assert math.isclose(a1["oip"], 450.0)
    assert math.isclose(a1["h_eff"], 6.0)
    # Рпл средневзвешенное по мощности: (250*2 + 252*2 + 254*2)/6 = 252
    assert math.isclose(a1["p_res"], 252.0)
    assert math.isclose(a1["qliq"], 180.0)
    assert a1["n_slices"] == 3


def test_aggregate_absent_code():
    a99 = synthetic().aggregate(99)
    assert a99["oip"] == 0.0 and a99["n_slices"] == 0


def test_totals_skip_inactive_intervals():
    d = synthetic()
    d.intervals[1].h_eff = 0                      # интервал 2 «выключен»
    t = d.totals()
    assert t["n_intervals"] == 1
    assert math.isclose(t["oip"], 450.0)


def test_equal_weights_when_zero_thickness():
    d = synthetic()
    for s in d.slices_of(2):
        s["h_eff"] = 0.0
    a2 = d.aggregate(2)
    # равные веса: (260 + 262)/2 = 261
    assert math.isclose(a2["p_res"], 261.0)


@pytest.mark.skipif(not __import__("os").path.exists(BOOK),
                    reason="книга RE Tools недоступна")
def test_real_book_structure():
    d = read_rigis(BOOK)
    assert len(d.intervals) == 10
    first = d.intervals[0]
    assert first.n == 1
    assert math.isclose(first.top, 2938) and math.isclose(first.bottom, 3248)
    assert math.isclose(first.h_eff, 13.2)
    assert math.isclose(first.p_res, 96)
    assert len(d.slices) > 200                    # таблица срезов прочитана (219)
    # шаблон пустой: НГЗ срезов нулевые → итог по скважине 0
    assert d.totals()["oip"] == 0.0
    assert d.defaults.get("r_well") is not None
