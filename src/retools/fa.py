# -*- coding: utf-8 -*-
"""Факторный анализ отклонений дебита нефти.

Порт формул листа «ФА» расчётника RE Tools: разложение отклонения Qн между
двумя состояниями скважины (базовый план / сетевой расчёт / факт / РИГИС)
на вклады четырёх факторов: обводнённость, пластовое давление, забойное
давление и коэффициент приёмистости-продуктивности (Кпр).

Формулы перенесены дословно из ячеек C20:C23 листа «ФА»; факторы в сумме
дают точную итоговую дельту Qн (баланс сходится в ноль).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    """Состояние скважины в одном расчёте (лист «ФА», строки 8-12)."""
    q_liq: float          # Qж, м3/сут
    water_cut: float      # обводнённость объёмная, %
    q_oil: float          # Qн (тренд), т/сут
    p_wf: float           # Рзаб, атм
    p_res: float          # Рпл на ВНК, атм

    @property
    def oil_fraction(self) -> float:
        """Доля нефти в жидкости Qн/Qж (плотность нефти при нулевой обводнённости
        учитывается в самом Qн, здесь — только отношение)."""
        return self.q_oil / self.q_liq

    @property
    def pi(self) -> float:
        """Кпр = Qж/(Рпл - Рзаб), м3/сут/атм."""
        return self.q_liq / (self.p_res - self.p_wf)

    @property
    def dp(self) -> float:
        """Перепад Рпл - Рзаб, атм."""
        return self.p_res - self.p_wf


@dataclass(frozen=True)
class FactorResult:
    """Результат разложения: вклады факторов, т/сут."""
    water_cut: float      # ∆Qн(Qwc)
    p_res: float          # ∆Qн(Рпл)
    p_wf: float           # ∆Qн(Рзаб)
    pi: float             # ∆Qн(Кпр)
    total: float          # сумма факторов
    delta_q_oil: float    # фактическая дельта Qн2 - Qн1
    balance_error: float  # невязка: total - delta_q_oil


def decompose(base: Scenario, new: Scenario) -> FactorResult:
    """Разложить отклонение Qн между двумя сценариями по четырём факторам.

    Формулы листа «ФА» (C20:C23):
      ∆Qн(Qwc) = (Qж2 + Qж1) · (f2 - f1) · 0.5
      ∆Qн(Рпл) = (Кпр2 + Кпр1)·0.5 · (Рпл2 - Рпл1) · (f2 + f1)·0.5
      ∆Qн(Рзаб) = -(Кпр2 + Кпр1)·0.5 · (Рзаб2 - Рзаб1) · (f2 + f1)·0.5
      ∆Qн(Кпр)  = ((Кпр2 - Кпр1)·(Рпл1 - Рзаб1)
                   + (Кпр2 - Кпр1)·((Рпл2 - Рзаб2) - (Рпл1 - Рзаб1))·0.5)
                  · (f2 + f1)·0.5
    где f = Qн/Qж — доля нефти.
    """
    f1, f2 = base.oil_fraction, new.oil_fraction
    pi1, pi2 = base.pi, new.pi

    d_wc = (new.q_liq + base.q_liq) * (f2 - f1) * 0.5
    d_pres = (pi2 + pi1) * 0.5 * (new.p_res - base.p_res) * (f2 + f1) * 0.5
    d_pwf = -((pi2 + pi1) * 0.5 * (new.p_wf - base.p_wf)) * (f2 + f1) * 0.5
    d_pi = ((pi2 - pi1) * base.dp
            + (pi2 - pi1) * (new.dp - base.dp) * 0.5) * (f2 + f1) * 0.5

    total = d_wc + d_pres + d_pwf + d_pi
    delta = new.q_oil - base.q_oil
    return FactorResult(d_wc, d_pres, d_pwf, d_pi, total, delta, total - delta)


def factors_sorted(res: FactorResult) -> list[tuple[str, float]]:
    """Факторы по убыванию модуля вклада (аналог сортировки F/G на листе)."""
    items = [("Обводнённость", res.water_cut), ("Рпл", res.p_res),
             ("Рзаб", res.p_wf), ("Кпр", res.pi)]
    return sorted(items, key=lambda kv: -abs(kv[1]))
