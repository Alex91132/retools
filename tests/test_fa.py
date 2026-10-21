# -*- coding: utf-8 -*-
"""Тесты факторного анализа на эталонных числах листа «ФА» исходной книги.

Контрольный пример (ячейки C8:E25): Qж 200→210, обв 10→0 %, Qн 150→170 т/сут,
Рзаб 80→90 атм, Рпл 120→110 атм.
"""
import math

from retools import Scenario, decompose, factors_sorted


def make_pair():
    base = Scenario(q_liq=200, water_cut=10, q_oil=150, p_wf=80, p_res=120)
    new = Scenario(q_liq=210, water_cut=0, q_oil=170, p_wf=90, p_res=110)
    return base, new


def test_factor_values_match_sheet():
    """Вклады факторов совпадают с кэшированными значениями листа ФА."""
    res = decompose(*make_pair())
    assert math.isclose(res.water_cut, 12.202380952380954, rel_tol=1e-12)
    assert math.isclose(res.p_res, -60.43154761904762, rel_tol=1e-12)
    assert math.isclose(res.p_wf, -60.43154761904762, rel_tol=1e-12)
    assert math.isclose(res.pi, 128.66071428571428, rel_tol=1e-12)


def test_balance_is_exact():
    """Сумма факторов равна итоговой дельте Qн (баланс сходится в ноль)."""
    res = decompose(*make_pair())
    assert math.isclose(res.total, 20.0, rel_tol=1e-12)
    assert math.isclose(res.delta_q_oil, 20.0, rel_tol=1e-12)
    assert math.isclose(res.balance_error, 0.0, abs_tol=1e-12)


def test_sorted_factors_desc():
    """Сортировка по модулю вклада: Кпр > Рпл ≈ Рзаб > обводнённость."""
    res = decompose(*make_pair())
    order = [name for name, _ in factors_sorted(res)]
    assert order == ["Кпр", "Рпл", "Рзаб", "Обводнённость"]


def test_identical_scenarios_zero():
    base, _ = make_pair()
    res = decompose(base, base)
    assert all(math.isclose(v, 0.0, abs_tol=1e-12)
               for v in (res.water_cut, res.p_res, res.p_wf, res.pi, res.total))
