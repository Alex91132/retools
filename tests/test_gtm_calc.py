# -*- coding: utf-8 -*-
"""Рейтинг ГТМ и «Расчёт добычи» — против кэша книги (13 скважин рейтинга, 72 строки расчёта)."""
import datetime as dt
import json
from pathlib import Path

import pytest

import retools.gtm_calc as G
from retools.gtm_calc import ObjectSheet, production_rows, rating_row, result_by_month

FIX = Path(__file__).parent / "fixtures"
BOOK = json.loads((FIX / "production_book.json").read_text(encoding="utf-8"))
OBJ = ObjectSheet.from_book(json.loads((FIX / "pvt_mbe_book.json").read_text(encoding="utf-8")))
# Get_J ГС-семейства плохо обусловлен (см. test_productivity) — допуск по типу заканчивания
J_TOL = {"ННС": 1e-10, "ННС+ГРП": 1e-8, "ГС": 1e-4, "ГС+ГРП": 3e-5, "МЗС": 1e-5}
J_COLS = {"BC", "BE", "CF", "DF", "AO"}


@pytest.fixture(scope="module")
def rating():
    # в строках 8 и ниже книги CJ = доля·(CH + CI) — вариант воспроизводится флагом
    return [rating_row(ref, OBJ, cj_with_ci=i > 0) for i, ref in enumerate(BOOK["rating"])]


def _rel(a, b):
    return abs(a - b) / max(abs(b), 1e-9)


def test_rating_matches_book(rating):
    cols = ("AZ BA BB BC BD BE BF BG BH BI BJ BK BM BN BO BP CA CB CC CD CE CF CG CH CI CJ CK CL CM CN CO CP CQ CR CS "
            "CT CU CV CW CX CY CZ DA DB DC DD DE DF DG").split()
    for r, ref in zip(rating, BOOK["rating"]):
        for c in cols:
            tol = J_TOL[ref["K"]] if c in J_COLS else 1e-9
            assert _rel(r[c], ref[c]) < tol, (ref["A"], c, r[c], ref[c])
        assert r["K"] == ref["K"]


def test_cj_row7_formula_excludes_injection_gain(rating):
    """Строка 7 книги: CJ от CH; ППД добавляется в расчёте добычи отдельно (CK)."""
    r = rating_row(BOOK["rating"][0], OBJ)
    assert r["CJ"] == pytest.approx(BOOK["rating"][0]["CJ"], rel=1e-12)
    both = rating_row(BOOK["rating"][0], OBJ, cj_with_ci=True)
    assert both["CJ"] > r["CJ"]


@pytest.fixture(scope="module")
def rows_book_j(rating):
    """Расчёт с Get_J из книги — проверка формул листа без шума продуктивности."""
    calc = BOOK["calc"]
    state = {"i": 0}
    orig = G._get_j_row

    def fake(r, mu, ct, b):
        i = state["i"]
        if i < len(calc) and abs(calc[i]["FC"] - mu) <= 1e-6 * abs(calc[i]["FC"]):
            state["i"] += 1
            return calc[i]["FF"] / (calc[i]["S"] * calc[i]["AW"])
        return orig(r, mu, ct, b)

    G._get_j_row = fake
    try:
        rating_b = [dict(r, **{k: v for k, v in ref.items() if k != "K"}) for r, ref in zip(rating, BOOK["rating"])]
        return production_rows(rating_b, OBJ)[:len(calc)]
    finally:
        G._get_j_row = orig


def test_production_rows_match_book_exactly(rows_book_j):
    """72 строки × все столбцы листа «Расчёт добычи»: до 1e-10 (даты и шаги — точно)."""
    worst = 0.0
    for a, e in zip(rows_book_j, BOOK["calc"]):
        for c, ev in e.items():
            av = a.get(c)
            if c == "FL":
                assert av.isoformat() == ev[:10]
            elif isinstance(ev, (int, float)) and isinstance(av, (int, float)):
                worst = max(worst, _rel(av, ev))
    assert worst < 1e-10


def test_ten_day_step_as_book(rows_book_j):
    """При разбросе давления (DX > 5 %) шаг — 10 суток: август 2024 у скважины 1 разбит на 10 + 21."""
    aug = [r for r in rows_book_j if r["A"] == 1 and r["FL"].month == 8 and r["FL"].year == 2024]
    assert [r["FN"] for r in aug] == [10, 21] and aug[0]["DX"] > 0.05


def test_production_with_own_get_j(rating):
    """С собственным Get_J дебиты и накопленные — в пределах шума продуктивности (3e-4)."""
    rows = production_rows(rating, OBJ)[:len(BOOK["calc"])]
    for a, e in zip(rows, BOOK["calc"]):
        for c in ("BE", "BC", "FV", "FZ", "CL", "DY"):
            assert _rel(a[c], e[c]) < 1e-3, (e["A"], e["FM"], c)
    assert len(production_rows(rating, OBJ)) == 73        # в книге X = 72 строки, 13-я скважина не вошла


def test_result_by_month(rows_book_j):
    res = result_by_month(rows_book_j)
    assert res[0]["date"] == dt.date(2024, 1, 1) and res[0]["n_wells"] == 12
    assert res[0]["q_oil"] == pytest.approx(sum(r["BE"] for r in rows_book_j if r["FL"].month == 1
                                                 and r["FL"].year == 2024), rel=1e-12)
    aug = next(m for m in res if m["date"] == dt.date(2024, 8, 1))
    a = [r for r in rows_book_j if r["FL"].year == 2024 and r["FL"].month == 8]
    assert aug["q_oil"] == pytest.approx(sum(r["BE"] * r["FN"] for r in a) / 31, rel=1e-12)
    assert aug["oil_t"] == pytest.approx(sum(r["FO"] for r in a), rel=1e-12)
    # накопленная у скважин 2–12 (1 месяц) переносится на следующие месяцы
    assert res[-1]["cum_oil_t"] == pytest.approx(sum(r["FV"] for r in rows_book_j
                                                     if r is max((x for x in rows_book_j if x["A"] == r["A"]),
                                                                 key=lambda x: x["FL"])), rel=1e-12)


def test_object_from_parameters_runs(rating):
    """Лист объекта из параметров (матбаланс заново, палетки FDP_Functions) — расчёт идёт.

    Стартовый Qн ниже книжного на ~5 %: Рпл 110 атм — в зоне, где «Подбор параметра»
    книги не сошёлся (ниже ~124 атм), и Sg, Ct там другие (как и в РИГИС, см. object_builder).
    """
    obj = ObjectSheet.from_params(OBJ.params)
    r1 = rating_row(BOOK["rating"][0], obj)
    rows = production_rows([r1], obj)
    assert len(rows) >= 60
    assert rows[0]["BE"] == pytest.approx(BOOK["calc"][0]["BE"], rel=0.07)
