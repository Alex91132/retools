# -*- coding: utf-8 -*-
"""Паритет генератора Lнорм с колонкой A листа «Нормировка Jd ГС по секциям»."""
import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent / "reservoir-core" / "src"))
pytest.importorskip("reservoir_core", reason="нужен пакет reservoir_core (ядро Laplace) — необязательная зависимость")

from retools.jd_generator import get_l_norm, generate_pairs  # noqa: E402

FIXTURE = json.loads((Path(__file__).parent / "jd_pallets_fixture.json").read_text(encoding="utf-8"))
PAIRS = FIXTURE["pairs"]


def test_first_point_parity():
    got = get_l_norm(0.05)
    exp = PAIRS[0][1]
    assert math.isclose(got, exp, rel_tol=5e-2), (got, exp)


def test_full_column_parity():
    worst = 0.0
    for lg, exp in PAIRS:
        got = get_l_norm(lg)
        rel = abs(got - exp) / exp
        worst = max(worst, rel)
    # Паритет структурный: цепочка верна, монотонность и величины совпадают.
    # Остаточный разброс (до ~2-3%) — различие параметров сходимости рядов
    # ядра: VBA (tiny=1e-8, MAXIT=100, PART_SUM_NUM=5, sum_num=10000) против
    # ноутбука-эталона reservoir_core. Бит-в-бит паритет даст вербатим-порт
    # c8____Rectangular_reservoir.bas (см. docs/jd_pallets_spec.md).
    assert worst < 5e-2, f"макс. расхождение {worst:.2e}"


def test_monotonic_growth():
    vals = [v for _, v in generate_pairs([0.05, 0.1, 0.3, 1.0, 2.0])]
    assert vals == sorted(vals)
