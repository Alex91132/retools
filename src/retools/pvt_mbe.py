# -*- coding: utf-8 -*-
"""PVT-таблица, материальный баланс (Хавлена–Оде) и заводнение (Кори, Бейкер).

Порт VBA-функций расчётника RE Tools:
- b__1Ph_Model.bas — ОФП Кори, обводнённость f_w (в %!), обратная задача
  Sw(f_w) делением пополам, эффективные вязкость/сжимаемость/объёмный к.;
- b_RG_3Ph_Model.bas — MBE_LHS / MBE_RHS (материальный баланс, см. Tarek
  Ahmed, Adv. Reservoir Engineering), накопленный ГФ по ОФП, ОФП нефти
  Бейкера для трёхфазной системы.

PVT-свойства (Rs/Bo/Bg/µ от давления) считаются корреляциями книги
(класс CPVT, набор Стендинга/Маккейна) и передаются сюда таблицей —
как это делает сам лист книги (колонки E–K).
"""
from __future__ import annotations

from dataclasses import dataclass


# ============ ОФП Кори и обводнённость (b__1Ph_Model.bas) ============

def corey_krw(sw: float, swc: float, sor: float, krw_end: float = 1.0, mw: float = 1.0) -> float:
    """ОФП воды: krw = krw_end · SD^M1, SD = (Sw − Swc)/(1 − Sor − Swc)."""
    if sw >= 1:
        return 1.0
    sd = 1.0 if (1 - sor - swc) == 0 else (sw - swc) / (1 - sor - swc)
    return krw_end * sd ** mw


def corey_kro(sw: float, swc: float, sor: float, kro_end: float = 1.0, mo: float = 1.0) -> float:
    """ОФП нефти: kro = kro_end · (1 − SD)^M2."""
    if sw >= 1:
        return 0.0
    sd = 1.0 if (1 - sor - swc) == 0 else (sw - swc) / (1 - sor - swc)
    return kro_end * (1 - sd) ** mo


def frac_flow(mu_w: float, mu_o: float, bo: float, bw: float, sw: float,
              swc: float = 0.2, sor: float = 0.3,
              krw_end: float = 1.0, kro_end: float = 1.0,
              mw: float = 1.0, mo: float = 1.0) -> float:
    """Обводнённость продукции f_w, % (дословно Get_f_w): 100/(1+...)."""
    if sw <= swc:
        return 0.0
    if sw >= 1 - sor:
        return 100.0
    krw = corey_krw(sw, swc, sor, krw_end, mw)
    kro = corey_kro(sw, swc, sor, kro_end, mo)
    if krw * mu_o * bo == 0:
        return 0.0
    return 100.0 / (1.0 + (kro * mu_w * bw) / (krw * mu_o * bo))


def sw_from_fw(fw_pct: float, mu_w: float, mu_o: float, bo: float, bw: float = 1.0,
               swc: float = 0.2, sor: float = 0.3,
               krw_end: float = 1.0, kro_end: float = 1.0,
               mw: float = 1.0, mo: float = 1.0,
               max_iter: int = 10000, tol: float = 0.001) -> float:
    """Обратная задача: Sw по заданной обводнённости (бисекция, как Get_Sw)."""
    lo, hi = swc, 1 - sor
    if fw_pct <= 0:
        return lo
    if fw_pct >= 100:
        return hi
    sw = (lo + hi) / 2
    for _ in range(max_iter):
        f = frac_flow(mu_w, mu_o, bo, bw, sw, swc, sor, krw_end, kro_end, mw, mo)
        if fw_pct > f:
            lo = sw
        else:
            hi = sw
        sw = (lo + hi) / 2
        if hi - lo <= tol:
            break
    return sw


def eff_mu(mu_w: float, mu_o: float, sw: float, swc: float = 0.2, sor: float = 0.3,
           krw_end: float = 1.0, kro_end: float = 1.0,
           mw: float = 1.0, mo: float = 1.0) -> float:
    """Эффективная вязкость жидкости: µw·µo/(kro·µw + krw·µo)."""
    krw = corey_krw(sw, swc, sor, krw_end, mw)
    kro = corey_kro(sw, swc, sor, kro_end, mo)
    den = kro * mu_w + krw * mu_o
    return 0.0 if den == 0 else mu_w * mu_o / den


def total_compressibility(c_r: float, c_o: float, c_w: float, sw: float) -> float:
    """Общая сжимаемость: ct = co·(1−Sw) + cw·Sw + cr."""
    return c_o * (1 - sw) + c_w * sw + c_r


def eff_fvf(bo: float, bw: float, fw_pct: float) -> float:
    """Эффективный объёмный коэффициент жидкости: B = Bo·(1−fw) + Bw·fw."""
    if bw == 0:
        bw = 1.0
    return bo * (1 - fw_pct / 100) + bw * fw_pct / 100


# ============ Материальный баланс (b_RG_3Ph_Model.bas) ============

def mbe_lhs(np_: float, bo: float, bg: float, rs: float, rp: float,
            we: float = 0.0, wp: float = 0.0, bw: float = 0.0,
            ginj: float = 0.0, bginj: float = 0.0,
            winj: float = 0.0, bwi: float = 0.0) -> float:
    """Левая часть MBE: добыча − приток воды − закачка (в единицах N·…)."""
    return (np_ * (bo + (rp - rs) * bg)
            - (we - wp * bw) - ginj * bginj - winj * bwi)


def mbe_rhs(bo: float, boi: float, rsi: float, rs: float, bg: float, bgi: float,
            sw: float, cw: float, cf: float, pi: float, p: float,
            m: float = 0.0) -> float:
    """Правая часть MBE: расширение системы (газ. шапка + связ. вода + порода)."""
    return ((bo - boi) + (rsi - rs) * bg + m * (bg / bgi - 1)
            + boi * (1 + m) * ((sw * cw + cf) / (1 - sw)) * (pi - p))


def rp_from_relperm(rsi: float, rs: float, krg: float, kro: float,
                    muo: float, bo: float, mug: float, bg: float) -> float:
    """Накопленный газонефтяной фактор по ОФП (Get_RP)."""
    return 0.5 * (rsi + rs + (krg / kro) * (muo * bo) / (mug * bg))


def kro_baker(sw: float, swl: float, sg: float, sorg_og: float, sorw_ow: float,
              fo: float, exo_ow: float, exo_og: float) -> float:
    """ОФП нефти в трёхфазной системе (линейная интерполяция Бейкера)."""
    den = 1 - sorw_ow - swl
    sd = 1.0 if den == 0 else (sw - swl + sg) / den
    kro_ow = fo * (1 - sd) ** exo_ow
    if sg == 0:
        return kro_ow
    kro_og = fo * (1 - (sg + sw - swl) / (1 - sorg_og - swl)) ** exo_og
    w = sw - swl
    return (kro_ow * w) / (sg + w) + (kro_og * sg) / (w + sg)


# ============ Контрольный флюид книги (лист PVT_MBE_Waterflood) ============

@dataclass(frozen=True)
class ControlFluid:
    """Параметры контрольного примера книги (используются в тестах паритета)."""
    pi: float = 159.0        # D2
    swl: float = 0.2         # D3
    m_cap: float = 0.3       # D5 — отношение объёма газовой шапки к нефти
    cf: float = 3e-05        # D9
    rsi: float = 60.0        # D24
    boi: float = 1.08        # BA20
    bgi: float = 0.004712503811235841   # BA22
    cw: float = 3.813437304098296e-05   # BA27
