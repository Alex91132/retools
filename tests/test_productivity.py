# -*- coding: utf-8 -*-
"""Get_J — порт продуктивности RE Tools против кэша листа «Рейтинг ГТМ» (столбец DF).

Решения для ГС, МГРП и МЗС численно плохо обусловлены: ряд fast_ik0 у границы
x = 18 теряет до 8 цифр, а сумма слагаемых усиливает это в тысячи раз. Сама
книга меняет Get_J на 2e-6 при изменении вязкости на 2 ulp (рейтинг и лист
«Расчёт добычи» для одной скважины). Поэтому допуск — по типу заканчивания.
"""
import json
from pathlib import Path

import pytest

from retools.productivity import fast_ik0, get_completion, get_j, stehfest_coef

FIX = Path(__file__).parent / "fixtures"
ROWS = json.loads((FIX / "production_book.json").read_text(encoding="utf-8"))["rating"]
TOL = {"ННС": 1e-10, "ННС+ГРП": 1e-8, "ГС": 1e-4, "ГС+ГРП": 3e-5, "МЗС": 1e-5}
ARGS = ("P", "N", "T", "U", "AJ", "AF", "AG", "M", "O", "AH", "DC", "DD", "DE", "Y", "AB", "AC", "AA", "W", "X", "V")


def _j(r):
    g = [r.get(c) or 0 for c in ARGS]
    return get_j(*g, frac_dir=r.get("AE") or "") * (r.get("AW") or 0)


@pytest.mark.parametrize("r", ROWS, ids=[f"{r['A']}-{r['K']}" for r in ROWS])
def test_get_j_matches_book(r):
    assert _j(r) == pytest.approx(r["DF"], rel=TOL[r["K"]])


def test_completion_types_as_book():
    for r in ROWS:
        assert get_completion(r.get("T") or 0, r.get("Y") or 0, r.get("V") or 0) == r["K"]


def test_stehfest_coefficients_sum_to_zero():
    v = stehfest_coef(10)
    assert abs(sum(v[1:])) < 1e-9 and v[1] == pytest.approx(1 / 12)


def test_fast_ik0_limits():
    import math
    assert fast_ik0(0) == 0 and fast_ik0(20) == pytest.approx(math.pi / 2)
    assert fast_ik0(1) == pytest.approx(1.2425098486237776, rel=1e-14)


def test_invalid_geometry_returns_minus_one():
    r = dict(ROWS[0])
    r["U"] = r["T"] * 2          # эффективная длина больше общей
    assert _j(r) == -1
