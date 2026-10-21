# -*- coding: utf-8 -*-
"""Объект разработки и палетки для расчёта РИГИС.

В RE Tools расчёт срезов РИГИС берёт данные с двух листов:
- лист объекта (по умолчанию «PVT_MBE_Waterflood», имя — ячейка РИГИС!AB17):
  параметры D2:D38 (PVT, ОФП Бейкера, Swl/Swi, Pb…), кривые по давлению
  (E — P, G — Bo, I — Ct, T — So, U — Sg; решение матбаланса) и палетка
  «доля НПЗ при предельной обводнённости» AF108:AQ144;
- «Нормировка Jd ГС по секциям»: коэффициенты секции ГС от (L общ. эфф., L секции)
  для мощностей 1, 5, 15, 50 м (блоки DA:GW, используются в Get_J_obsolete).

Здесь эти данные читаются из книги как готовые таблицы. Генерация их без
Excel (матбаланс — pvt_mbe, палетки Jd — jd_generator) — следующий шаг.
"""
from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, field
from pathlib import Path

from .cpvt import CPVT
from .interp import Curve, Grid2D, interp1

# строки параметров листа объекта (колонка D)
PARAM_ROWS = dict(p_init=2, swl=3, swi=4, gas_cap_m=5, depth=6, t_C=7, rock_density=8, c_f=9, pvt_json=18,
                  heff_fu1=11, heff_fu2=12, k_fu1=13, k_fu2=14, phi_fu1=15, phi_fu2=16,
                  corr_set=19, gamma_gas=20, rho_oil=21, gamma_wat=22, pb=23, rsi=24, bob=25, muob=26,
                  sorw_ow=28, sorg_og=29, swcr_ow=30, sgcr_og=31, end_oil=32, end_water=33, end_gas=34,
                  exo_ow=35, exw_ow=36, exo_og=37, exg_og=38)
JD_BLOCKS = ((4, 5, 104), (107, 108, 207), (210, 211, 310), (313, 314, 413))  # строка оси x, строки y
JD_THICKNESS = (1.0, 5.0, 15.0, 50.0)


@dataclass
class FieldObject:
    """Объект разработки: параметры, PVT, кривые матбаланса, палетка НПЗ."""
    name: str
    params: dict
    p_curve: list = field(default_factory=list)       # E3:E38, атм
    bo_curve: list = field(default_factory=list)      # G
    ct_curve: list = field(default_factory=list)      # I
    so_curve: list = field(default_factory=list)      # T
    sg_curve: list = field(default_factory=list)      # U
    npz_pallet: Grid2D | None = None                  # (Sw, %обв) -> доля НПЗ

    def __post_init__(self):
        pvt = self.params["pvt_json"]
        cfg = json.loads(pvt) if isinstance(pvt, str) else pvt
        self.pvt_cfg = cfg
        self.pvt = CPVT(gamma_gas=cfg["gamma_gas"], gamma_oil=cfg["gamma_oil"], gamma_wat=cfg["gamma_wat"],
                        rsb_m3m3=cfg["rsb_m3m3"], pb_atma=cfg["pb_atma"], bob_m3m3=cfg["bob_m3m3"],
                        muob_cP=cfg["muob_cP"], corr=cfg.get("PVT_corr_set", 1), t_res_C=cfg["t_res_C"])
        self._ct = Curve(self.p_curve, self.ct_curve)
        self._so = Curve(self.p_curve, self.so_curve)
        self._sg = Curve(self.p_curve, self.sg_curve)
        self._bo = Curve(self.p_curve, self.bo_curve)

    # параметры, на которые ссылаются формулы листа РИГИС (Y22:AN22)
    @property
    def rho_oil(self) -> float:
        return self.params["rho_oil"]

    def ct(self, p: float) -> float:
        return self._ct(p)

    def so(self, p: float) -> float:
        return self._so(p)

    def sg(self, p: float) -> float:
        return self._sg(p)

    def bo_curve_at(self, p: float) -> float:
        return self._bo(p)


@dataclass
class JdSectionPallets:
    """Коэффициенты секции ГС (Get_J_obsolete) для мощностей 1, 5, 15, 50 м."""
    grids: tuple                     # Grid2D(x = L общ. эфф., y = L секции)
    thickness: tuple = JD_THICKNESS

    def coefficient(self, l_total: float, l_section: float, h_eff: float) -> float:
        """CA = интерполяция по мощности значений палеток в точке (L общ., L секции)."""
        vals = [g(l_total, l_section) for g in self.grids]
        return interp1(self.thickness, vals, h_eff)


def _load(path):
    import openpyxl
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return openpyxl.load_workbook(path, read_only=True, data_only=True)


def _rows(ws, r1, r2, c1, c2):
    return [list(r) for r in ws.iter_rows(min_row=r1, max_row=r2, min_col=c1, max_col=c2, values_only=True)]


def read_field_object(book: str | Path, sheet: str = "PVT_MBE_Waterflood", wb=None) -> FieldObject:
    wb = wb or _load(book)
    ws = wb[sheet]
    col_d = {i + 1: r[0] for i, r in enumerate(_rows(ws, 1, 40, 4, 4))}
    params = {k: col_d[r] for k, r in PARAM_ROWS.items()}
    curves = _rows(ws, 3, 38, 5, 21)        # E..U
    pal = _rows(ws, 108, 144, 31, 43)       # AE..AQ
    xs = pal[0][1:]
    ys = [r[0] for r in pal[1:]]
    f = [r[1:] for r in pal[1:]]
    return FieldObject(
        name=sheet, params=params,
        p_curve=[r[0] for r in curves], bo_curve=[r[2] for r in curves], ct_curve=[r[4] for r in curves],
        so_curve=[r[15] for r in curves], sg_curve=[r[16] for r in curves],
        npz_pallet=Grid2D(xs, ys, f),
    )


def read_jd_pallets(book: str | Path, sheet: str = "Нормировка Jd ГС по секциям", wb=None) -> JdSectionPallets:
    wb = wb or _load(book)
    ws = wb[sheet]
    grids = []
    for x_row, y1, y2 in JD_BLOCKS:
        xs = _rows(ws, x_row, x_row, 106, 205)[0]           # DB..GW
        block = _rows(ws, y1, y2, 105, 205)                  # DA..GW
        grids.append(Grid2D(xs, [r[0] for r in block], [r[1:] for r in block]))
    return JdSectionPallets(grids=tuple(grids))
