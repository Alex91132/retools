# -*- coding: utf-8 -*-
"""Загрузка РИГИС из выгрузки в Excel и файл проекта (JSON).

Выгрузка РИГИС — таблица срезов: строка заголовков где-то в первых строках
листа, дальше по строке на срез. Столбцы распознаются по названиям (синонимы
ниже, регистр и пробелы не важны); сопоставление можно задать явно — словарь
{поле Slice: название столбца}.

Файл проекта хранит всё для расчёта без книги RE Tools: срезы и настройки
скважины, объект разработки (PVT, ОФП, кривые матбаланса, палетка НПЗ) и
палетки секций ГС.
"""
from __future__ import annotations

import json
import re
import warnings
from dataclasses import asdict
from pathlib import Path

from .field_object import FieldObject, JdSectionPallets
from .interp import Grid2D
from .rigis import CompletionRules, Defaults, IntervalParams, Regressions, RigisCase, Slice

# поле Slice -> варианты названий столбца (нижний регистр, без лишних пробелов)
SYNONYMS = {
    "well": ["no скважины", "№ скважины", "скважина", "скв", "скв.", "well"],
    "formation": ["свита / пласт", "свита/пласт", "пласт", "свита", "объект", "formation"],
    "top": ["кровля, иг", "кровля иг", "кровля", "кровля md", "кровля, м", "top", "md top"],
    "bottom": ["подошва, иг", "подошва иг", "подошва", "подошва md", "подошва, м", "bottom", "md bottom"],
    "top_tvd": ["кровля, ао", "кровля ао", "кровля абс", "кровля, абс", "tvd top", "tvdss top"],
    "bottom_tvd": ["подошва, ао", "подошва ао", "подошва абс", "подошва, абс", "tvd bottom", "tvdss bottom"],
    "h": ["мощность", "толщина", "h", "мощность, м", "толщина, м"],
    "res": ["уэс, омм", "уэс", "rt", "сопротивление", "уэс, ом*м"],
    "phit": ["кп общ (phit)", "кп общ", "phit", "кп общ.", "кп_общ"],
    "phi": ["кп для расчёта", "кп для расчета", "кп", "кп эфф", "phie", "пористость"],
    "vsh": ["кгл", "vsh", "глинистость"],
    "perm": ["кпр для расчёта", "кпр для расчета", "кпр", "perm", "проницаемость"],
    "sw": ["кв для расчёта", "кв для расчета", "кв", "sw", "водонасыщенность"],
    "so": ["кн", "so", "кнг", "нефтенасыщенность"],
    "saturation": ["характер насыщения", "насыщение", "характер"],
    "collector": ["коллектор *", "коллектор", "коллектор*", "кол", "collector"],
}
REQUIRED = ("top", "bottom", "h", "phi", "perm", "sw")


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s or "").replace("ё", "е").replace("Ё", "Е")).strip().lower()


def detect_columns(header: list) -> dict:
    """Сопоставить поля Slice столбцам по заголовку: {поле: индекс столбца}."""
    names = [_norm(h) for h in header]
    out = {}
    for fld, syn in SYNONYMS.items():
        syn_n = [_norm(x) for x in syn]
        for idx, n in enumerate(names):          # точное совпадение
            if n in syn_n and idx not in out.values():
                out[fld] = idx
                break
    for fld, syn in SYNONYMS.items():            # начало строки — для «Кп общ (PHIT), д.ед.» и т. п.
        if fld in out:
            continue
        syn_n = [_norm(x) for x in syn]
        for idx, n in enumerate(names):
            if idx in out.values():
                continue
            if any(n.startswith(x + ",") or n.startswith(x + " ") for x in syn_n):
                out[fld] = idx
                break
    return out


def _num(v, default=0.0) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", ".").strip())
    except (TypeError, ValueError):
        return default


def read_rigis_table(path, sheet: str | None = None, mapping: dict | None = None,
                     header_search_rows: int = 80) -> tuple[list[Slice], dict]:
    """Прочитать срезы из выгрузки Excel. Возвращает (срезы, найденное сопоставление).

    mapping — {поле: название столбца} поверх автоопределения.
    Если толщина не задана, берётся подошва − кровля; Кн — 1 − Кв; коллектор —
    «К», если Кпр > 0 и Кв < 1; нет столбца Кп общ (PHIT) — берётся Кп.
    """
    import openpyxl
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet] if sheet else wb.worksheets[0]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    best, best_row = {}, -1
    for i, row in enumerate(rows[:header_search_rows]):
        cols = detect_columns(row)
        if len(cols) > len(best):
            best, best_row = cols, i
    if mapping:
        header = [_norm(h) for h in rows[best_row]] if best_row >= 0 else []
        for fld, name in mapping.items():
            if _norm(name) in header:
                best[fld] = header.index(_norm(name))
    missing = [f for f in REQUIRED if f not in best and not (f == "h" and "top" in best and "bottom" in best)]
    if best_row < 0 or missing:
        raise ValueError(f"не найдены столбцы: {', '.join(missing) or 'заголовок'}. Задайте сопоставление вручную")
    get = lambda row, f, d=None: row[best[f]] if f in best and best[f] < len(row) else d   # noqa: E731
    slices = []
    for row in rows[best_row + 1:]:
        top, bottom = get(row, "top"), get(row, "bottom")
        if not isinstance(top, (int, float)) and _num(top, None) is None:
            continue
        top, bottom = _num(top), _num(bottom)
        if bottom <= top:
            continue
        sw = _num(get(row, "sw"))
        perm = _num(get(row, "perm"))
        so = get(row, "so")
        coll = get(row, "collector")
        slices.append(Slice(
            well=str(get(row, "well", "") or ""), formation=str(get(row, "formation", "") or ""),
            top=top, bottom=bottom, top_tvd=_num(get(row, "top_tvd")), bottom_tvd=_num(get(row, "bottom_tvd")),
            h=_num(get(row, "h"), bottom - top) or (bottom - top), res=_num(get(row, "res")),
            # PHIT: пустая ячейка — 0, как в книге (запасы на истощение тогда 0);
            # если столбца нет вовсе — берётся Кп для расчёта
            phit=_num(get(row, "phit")) if "phit" in best else _num(get(row, "phi")),
            phi=_num(get(row, "phi")), vsh=_num(get(row, "vsh")), perm=perm, sw=sw,
            so=_num(so) if so is not None else max(0.0, 1 - sw),
            saturation=str(get(row, "saturation", "") or ""),
            collector=str(coll) if coll is not None else ("К" if perm > 0 and sw < 1 else "НК"),
        ))
    names = {f: (rows[best_row][i] if best_row >= 0 else None) for f, i in best.items()}
    return slices, names


# --- Файл проекта ---------------------------------------------------------------

def _grid_to(g: Grid2D) -> dict:
    return {"x": g.xs, "y": g.ys, "f": g.f}


def _grid_from(d: dict) -> Grid2D:
    return Grid2D(d["x"], d["y"], d["f"])


def case_to_dict(case: RigisCase) -> dict:
    return {"slices": [asdict(s) for s in case.slices], "intervals": [asdict(i) for i in case.intervals],
            "defaults": asdict(case.defaults), "regressions": asdict(case.regressions),
            "rules": asdict(case.rules), "k_success": case.k_success, "object_name": case.object_name,
            "well_type": getattr(case, "well_type", "horizontal")}


def case_from_dict(d: dict) -> RigisCase:
    c = RigisCase(slices=[Slice(**s) for s in d["slices"]], intervals=[IntervalParams(**i) for i in d["intervals"]],
                  defaults=Defaults(**d["defaults"]), regressions=Regressions(**d["regressions"]),
                  rules=CompletionRules(**d["rules"]), k_success=d.get("k_success", 1.0),
                  object_name=d.get("object_name", "PVT_MBE_Waterflood"))
    if "well_type" in d:
        c.well_type = d["well_type"]
    return c


def object_to_dict(obj: FieldObject) -> dict:
    return {"name": obj.name, "params": obj.params, "p": obj.p_curve, "bo": obj.bo_curve, "ct": obj.ct_curve,
            "so": obj.so_curve, "sg": obj.sg_curve, "npz_pallet": _grid_to(obj.npz_pallet)}


def object_from_dict(d: dict) -> FieldObject:
    return FieldObject(name=d["name"], params=d["params"], p_curve=d["p"], bo_curve=d["bo"], ct_curve=d["ct"],
                       so_curve=d["so"], sg_curve=d["sg"], npz_pallet=_grid_from(d["npz_pallet"]))


def pallets_to_dict(p: JdSectionPallets) -> dict:
    return {"thickness": list(p.thickness), "grids": [_grid_to(g) for g in p.grids]}


def pallets_from_dict(d: dict) -> JdSectionPallets:
    return JdSectionPallets(grids=tuple(_grid_from(g) for g in d["grids"]), thickness=tuple(d["thickness"]))


def save_project(path, case: RigisCase, obj: FieldObject, pallets: JdSectionPallets) -> None:
    data = {"format": "retools-rigis/1", "case": case_to_dict(case), "object": object_to_dict(obj),
            "jd_pallets": pallets_to_dict(pallets)}
    Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def load_project(path) -> tuple[RigisCase, FieldObject, JdSectionPallets]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return case_from_dict(data["case"]), object_from_dict(data["object"]), pallets_from_dict(data["jd_pallets"])
