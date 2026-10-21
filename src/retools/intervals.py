# -*- coding: utf-8 -*-
"""Интервалы РИГИС: модель данных листа «РИГИС» (строки 3-14).

Каждый интервал перфорации/обработки характеризуется геометрией (кровля/подошва),
эффективной мощностью, пластовым давлением, долей заводняемых толщин и параметрами
сетки (R контура, соотношение ППД/доб). Итоговая строка «По скважине» — суммы по
интервалам (НГЗ, запасы) и параметры по умолчанию.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Interval:
    """Один интервал (строка листа «РИГИС», колонки B-K)."""
    top: float = 0.0          # кровля (выбор), м
    bottom: float = 0.0       # подошва (выбор), м
    h_eff: float = 0.0        # эффективная мощность, м
    p_res: float = 0.0        # начальное Рпл, атм
    flood_share: float = 0.0  # доля заводняемых толщин, д.ед.
    r_contour: float = 0.0    # R контура (половина шага сетки), м
    inj_prod_ratio: float = 0.0  # соотношение скважин ППД/доб., д.ед.
    oip: float = 0.0          # НГЗ интервала, тыс. т (тянется из петрофизики)


@dataclass
class WellIntervals:
    """Набор интервалов скважины + параметры по умолчанию (строка 14-15 листа)."""
    intervals: list[Interval] = field(default_factory=list)
    kv_kh: float = 0.1        # вертикальная анизотропия
    r_well: float = 0.1       # радиус скважины, м
    t_pss: float = 5.0        # время выхода на псевдостационар, сут
    p_wf_target: float = 82.0  # целевое Рзаб, атм

    def active(self) -> list[Interval]:
        """Интервалы с ненулевой эффективной мощностью."""
        return [i for i in self.intervals if i.h_eff > 0]

    def totals(self) -> dict[str, float]:
        """Итоги по скважине: суммы НГЗ и средневзвешенные параметры."""
        act = self.active()
        if not act:
            return {"oip": 0.0, "h_eff": 0.0,
                    "p_res_avg": 0.0, "flood_share_avg": 0.0}
        h = sum(i.h_eff for i in act)
        return {
            "oip": sum(i.oip for i in act),
            "h_eff": h,
            "p_res_avg": sum(i.p_res * i.h_eff for i in act) / h,
            "flood_share_avg": sum(i.flood_share * i.h_eff for i in act) / h,
        }
