# -*- coding: utf-8 -*-
"""Палетки нормировки Jd для горизонтальных скважин по секциям.

Порт логики листа «Нормировка Jd ГС по секциям» расчётника RE Tools.

Исходная книга устроена так:
- колонка A — нормированная длина ГС L_норм = Get_Jd(...Get_J(L_гс...)) — генерируется
  цепочкой VBA-функций (см. docs/jd_pallets_spec.md — спецификация для переноса);
- колонка B — сетка длины ГС L_гс (0.05 ... 3.7);
- строка 3 — L_норм для каждого столбца, строка 4 — сетка целевых Jd (0.05 ... 0.85);
- ячейки матрицы — доля от целевого Jd, применимая для секции длиной L_гс:
  =IF(L_гс > Jd_цель; 1; L_норм_цель / ((Jd_цель / L_гс) · L_норм(L_гс)))
  (шаблон формулы A2 исходного листа, ссылка расшифрована и проверена на числах книги).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "jd_pallets_fixture.json"


@dataclass(frozen=True)
class Pallet:
    """Палетка: пары (L_гс, L_норм) и сетка целевых Jd."""
    pairs: list[tuple[float, float]]   # (L_гс, L_норм)
    jd_grid: list[float]
    l_norm_targets: list[float]        # L_норм для каждого столбца Jd

    def ratio(self, l_gc: float, l_norm: float, jd_target: float,
              l_norm_target: float) -> float:
        """Доля от целевого Jd для секции длиной l_gc (формула листа, дословно)."""
        if l_gc > jd_target:
            return 1.0
        return l_norm_target / ((jd_target / l_gc) * l_norm)

    def row(self, l_gc: float) -> list[float]:
        """Строка палетки для секции длиной l_gc по всей сетке Jd."""
        l_norm = next(ln for lg, ln in self.pairs
                      if math.isclose(lg, l_gc, rel_tol=1e-9, abs_tol=1e-12))
        return [self.ratio(l_gc, l_norm, jd, ln)
                for jd, ln in zip(self.jd_grid, self.l_norm_targets)]

    def matrix(self) -> dict[float, list[float]]:
        """Полная матрица: L_гс (округлённая до 1e-6) -> доли Jd по сетке целей."""
        return {round(lg, 6): self.row(lg) for lg, _ in self.pairs}


def default_pallet() -> Pallet:
    """Палетка из контрольного примера исходной книги (55 пар L_гс/L_норм)."""
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    pairs = [tuple(p) for p in data["pairs"]]
    return Pallet(pairs=pairs, jd_grid=data["jd_grid"],
                  l_norm_targets=data["ln_row3"])
