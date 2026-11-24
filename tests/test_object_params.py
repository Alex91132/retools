# -*- coding: utf-8 -*-
"""Согласованность параметров объекта: начальное давление и сетка матбаланса."""

from __future__ import annotations

import pytest

from retools.object_builder import build_object, p_init_warnings
from retools.resources import data_path
from retools.rigis_io import load_project


@pytest.fixture(scope="module")
def params():
    _, obj, _ = load_project(data_path("rigis_4210H_project.json"))
    return dict(obj.params)


def test_consistent_params_have_no_warnings(params):
    p = {**params, "depth": 1605.0, "p_init": 410.5}
    assert p_init_warnings(p) == []


def test_low_initial_pressure_is_reported(params):
    p = {**params, "depth": 1605.0, "p_init": 159.0}
    messages = p_init_warnings(p)
    assert len(messages) == 1
    assert "ниже верхней точки" in messages[0]
    assert "410.5" in messages[0]


def test_high_initial_pressure_is_reported(params):
    p = {**params, "depth": 1605.0, "p_init": 500.0}
    messages = p_init_warnings(p)
    assert len(messages) == 1
    assert "выше верхней точки" in messages[0]


def test_build_object_warns_but_keeps_table(params):
    """Предупреждение не меняет расчёт: паритет с книгой сохраняется."""
    p = {**params, "depth": 1605.0, "p_init": 159.0}
    with pytest.warns(UserWarning, match="ниже верхней точки"):
        obj = build_object(p, name="проверка")
    assert len(obj.p_curve) == 36                    # сетка книги: 15 + 21 точек
    assert obj.p_curve[0] > obj.p_curve[-1]          # давление падает
