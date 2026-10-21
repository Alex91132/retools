# -*- coding: utf-8 -*-
"""Тесты чтения рейтинга ГТМ и результата расчёта на реальной книге."""
import os

import pytest

from retools.gtm_io import read_gtm, read_result

BOOK = os.environ.get("RETOOLS_BOOK", "")

pytestmark = pytest.mark.skipif(not os.path.exists(BOOK),
                                reason="книга RE Tools недоступна")


def test_gtm_rows_present():
    wells = read_gtm(BOOK)
    assert len(wells) >= 2
    first = wells[0]
    assert first.n == 1
    assert first.field  # название месторождения из книги
    assert first.target_zone  # объект разработки из книги
    assert first.gtm == "ВНС"
    assert first.completion == "ГС"
    assert first.purpose == "доб."
    assert first.pvt_sheet == "PVT_MBE_Waterflood"


def test_gtm_numeric_params():
    wells = read_gtm(BOOK)
    w = wells[0]
    assert w.h_eff == 20
    assert w.phi == 0.18
    assert w.perm == 250
    assert w.kv_kh == 0.1
    assert w.p_res_init == 110


def test_result_series():
    res = read_result(BOOK)
    assert len(res) >= 24                     # минимум два года помесячно
    dates = [r["date"] for r in res]
    assert dates == sorted(dates)
    qn = [r["Сумма по полю Qн"] for r in res if "Сумма по полю Qн" in r]
    assert qn and all(q > 0 for q in qn)      # добыча положительна
    wc = [r["Среднее по полю Обв-ть"] for r in res if "Среднее по полю Обв-ть" in r]
    assert wc[0] < 100                        # обводнённость в процентах


def test_result_cumulative_grows():
    res = read_result(BOOK)
    cum_keys = [k for k in res[0] if k.startswith("Сумма по полю Нак.")]
    assert cum_keys
    key = cum_keys[0]
    series = [r[key] for r in res if key in r]
    assert series == sorted(series)           # накопленная добыча не убывает
