# -*- coding: utf-8 -*-
"""Загрузка РИГИС из выгрузки Excel и файл проекта."""
from pathlib import Path

import openpyxl
import pytest

from retools.rigis import Regressions, compute
from retools.rigis_io import detect_columns, load_project, read_rigis_table, save_project

FIX = Path(__file__).parent / "fixtures"
HEADER = ["No скважины", "свита / пласт", "Кровля,  ИГ", "Подошва, ИГ", "Кровля, АО", "Подошва, АО", "Мощность",
          "УЭС, Омм", "Кп общ (PHIT)", "Кп для расчёта", "Кгл", "Кпр для расчёта", "Кв для расчёта", "Кн",
          "Характер\nнасыщения", "Коллектор *"]


def test_detect_columns_on_book_header():
    cols = detect_columns(HEADER)
    assert cols["top"] == 2 and cols["bottom"] == 3 and cols["h"] == 6
    assert cols["phit"] == 8 and cols["phi"] == 9 and cols["perm"] == 11 and cols["sw"] == 12
    assert cols["saturation"] == 14 and cols["collector"] == 15


def _write_export(path, slices, header=HEADER, junk_rows=3):
    wb = openpyxl.Workbook()
    ws = wb.active
    for i in range(junk_rows):
        ws.append([f"Выгрузка РИГИС, лист {i}"])
    ws.append(header)
    for s in slices:
        ws.append([s.well, s.formation, s.top, s.bottom, s.top_tvd, s.bottom_tvd, s.h, s.res, s.phit, s.phi,
                   s.vsh, s.perm, s.sw, s.so, s.saturation, s.collector])
    wb.save(path)


def test_export_roundtrip_gives_same_rates(tmp_path):
    """Срезы, выгруженные в Excel и прочитанные обратно, дают те же дебиты."""
    case, obj, pal = load_project(FIX / "rigis_4210H_project.json")
    case.regressions = Regressions()
    xlsx = tmp_path / "rigis.xlsx"
    _write_export(xlsx, case.slices)
    slices, names = read_rigis_table(xlsx)
    assert len(slices) == len(case.slices)
    case2 = type(case)(**{**case.__dict__, "slices": slices})
    a = sum(r.q_oil for r in compute(case, obj, pal))
    b = sum(r.q_oil for r in compute(case2, obj, pal))
    # Excel хранит 15 значащих цифр — последние разряды чисел округляются
    assert b == pytest.approx(a, rel=1e-9)
    assert [s.phit for s in slices] == [s.phit for s in case.slices]


def test_export_with_other_names_and_derived_columns(tmp_path):
    xlsx = tmp_path / "other.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Скважина", "Пласт", "Кровля", "Подошва", "УЭС", "Кп", "Кпр", "Кв", "Характер насыщения"])
    ws.append(["1", "АВ1", 2000.0, 2004.0, 12.0, 0.2, 50.0, 0.4, "нефть"])
    ws.append(["1", "АВ1", 2004.0, 2010.5, 3.0, 0.22, 80.0, 0.9, "вода"])
    wb.save(xlsx)
    slices, _ = read_rigis_table(xlsx)
    assert [s.h for s in slices] == [4.0, 6.5]
    assert slices[0].so == pytest.approx(0.6) and slices[0].collector == "К"


def test_missing_columns_reported(tmp_path):
    xlsx = tmp_path / "bad.xlsx"
    wb = openpyxl.Workbook()
    wb.active.append(["Глубина", "Что-то"])
    wb.save(xlsx)
    with pytest.raises(ValueError, match="не найдены столбцы"):
        read_rigis_table(xlsx)


def test_project_roundtrip(tmp_path):
    case, obj, pal = load_project(FIX / "rigis_4210H_project.json")
    save_project(tmp_path / "p.json", case, obj, pal)
    c2, o2, p2 = load_project(tmp_path / "p.json")
    assert sum(r.q_oil for r in compute(c2, o2, p2)) == pytest.approx(sum(r.q_oil for r in compute(case, obj, pal)))
