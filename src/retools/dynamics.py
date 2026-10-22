# -*- coding: utf-8 -*-
"""Динамика вытеснения по срезам и перетоки по пласту вдоль ствола (расширение, в книге нет).

1. **Вытеснение Баклея–Леверетта** в объёме среза. Вытесняющая фаза (вода или
   газ) приходит фронтом: до прорыва на забой идёт начальная насыщенность
   среза, после прорыва насыщенность на выходе S₂ — по Велджу: 1/f'(S₂) = Qi,
   средняя насыщенность объёма S̄ = S₂ + (1 − f(S₂))·Qi, где Qi — закачанные
   (пришедшие) поровые объёмы. Доля вытесняющей фазы в потоке (в пластовых
   объёмах) с гравитацией для вертикального вытеснения:

       f = (1 − Ng·kro) / (1 + kro·μd / (krd·μo)),   Ng = k_v·A·Δρ·g / (μo·q_t),

   q_t — поток через сечение A; Ng = 0 — вытеснение по латерали. Лёгкая фаза
   сверху, тяжёлая снизу — гравитация тормозит фронт в обоих случаях.

2. **Конусы к ВНК и ГНК**: вода поднимается от ВНК (газ опускается от ГНК) через
   столб пласта между контактом и стволом площадью A = L среза × ширина
   дренирования; предел устойчивости фронта — критический дебит Дитца:

       q_кр = k_v·krw'·A·Δρ·g / (μw·(M − 1)),   M = (krw'/μw)/(kro'/μo) > 1

   (Dake, Fundamentals of Reservoir Engineering); при M ≤ 1 фронт устойчив при
   любом дебите.

3. **Перетоки вдоль ствола.** Изолированный срез отдаёт к ближайшему фильтру
   долю своего потенциала ε = 1/(1 + J·R): J — продуктивность среза, R —
   сопротивление пути по пласту через промежуточные срезы (последовательно,
   к фильтрам с двух сторон — параллельно):

       R = μ·B·Σ L_j / (0,00864·k_j·A),   A = h_эфф·W,   L_j = √(Δx² + (Δz·√(kh/kv))²),

   0,00864 — Дарси в единицах м³/сут, мД, м², атм, сП, м (как 1/18,42·2π в
   Get_KhMu книги). Неколлектор с малой проницаемостью — барьер (ε → 0).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

DARCY = 86400 * 9.869233e-16 * 101325 / 1e-3        # 0,00864 м³/сут на мД·м²·атм/(сП·м)
GRAV_RATE = 86400 * 9.869233e-16 * 9.80665 / 1e-3   # м³/сут на мД·м²·(кг/м³)/сП
N_GRID = 400
K_BARRIER = 1e-6                                    # мД — «нулевая» проницаемость


# --- Баклей–Леверетт -------------------------------------------------------------------

@dataclass
class BLTable:
    """Функция доли вытесняющей фазы и построение Велджа для одного среза."""
    s: np.ndarray           # насыщенность вытесняющей фазой
    f: np.ndarray           # её доля в потоке (пластовые объёмы)
    s_i: float              # начальная насыщенность
    f_i: float
    s_f: float              # насыщенность на фронте
    f_f: float
    qi_bt: float            # поровые объёмы до прорыва (inf — фронт не дойдёт)
    s_max: float

    def outlet(self, qi: float) -> float:
        """Насыщенность на выходе (у забоя) после Qi поровых объёмов."""
        if not qi > 0 or qi < self.qi_bt or not math.isfinite(self.qi_bt):
            return self.s_i
        m = self.s >= self.s_f
        s, f = self.s[m], self.f[m]
        if len(s) < 2:
            return self.s_f
        df = np.gradient(f, s)
        with np.errstate(divide="ignore"):
            inv = np.where(df > 1e-12, 1.0 / df, np.inf)
        inv = np.maximum.accumulate(inv)          # 1/f' не убывает за фронтом
        if qi >= inv[-1]:
            return float(s[-1])
        return float(np.interp(qi, inv, s))

    def average(self, qi: float) -> float:
        """Средняя насыщенность объёма после Qi поровых объёмов (Велдж)."""
        if not qi > 0:
            return self.s_i
        if qi < self.qi_bt:
            return self.s_i + qi * (1 - self.f_i)
        s2 = self.outlet(qi)
        return min(s2 + (1 - float(np.interp(s2, self.s, self.f))) * qi, self.s_max)

    def frac(self, s: float) -> float:
        return float(np.interp(s, self.s, self.f))


def bl_table(kr_d, kr_o, mu_d: float, mu_o: float, s_i: float, s_max: float, ng: float = 0.0,
             n: int = N_GRID) -> BLTable:
    """Таблица Баклея–Леверетта: kr_d, kr_o — функции насыщенности вытесняющей фазой (numpy)."""
    s_i = float(s_i)
    if s_max <= s_i + 1e-9:
        s = np.array([s_i, s_i + 1e-9])
        return BLTable(s, np.zeros(2), s_i, 0.0, s_i, 0.0, math.inf, s_i)
    s = np.linspace(s_i, s_max, n)
    krd = np.clip(kr_d(s), 0.0, None)
    kro = np.clip(kr_o(s), 0.0, None)
    with np.errstate(divide="ignore", invalid="ignore"):
        f = np.where(krd > 0, (1 - ng * kro) / (1 + kro * mu_d / np.where(krd > 0, krd, 1.0) / mu_o), 0.0)
    f = np.clip(np.nan_to_num(f), 0.0, 1.0)
    f_i = float(f[0])
    with np.errstate(divide="ignore", invalid="ignore"):
        slope = np.where(s > s_i, (f - f_i) / (s - s_i), -np.inf)
    j = int(np.argmax(slope))
    if not slope[j] > 1e-12:
        return BLTable(s, f, s_i, f_i, s_i, f_i, math.inf, s_max)
    return BLTable(s, f, s_i, f_i, float(s[j]), float(f[j]), 1.0 / float(slope[j]), s_max)


def corey(end: float, exp: float, s_low: float, s_high: float):
    """kr = end·((s − s_low)/(s_high − s_low))^exp, 0 ниже s_low (векторно)."""
    span = max(s_high - s_low, 1e-12)
    return lambda s: end * np.clip((np.asarray(s) - s_low) / span, 0.0, 1.0) ** exp


def water_oil_kr(prm: dict, swl: float, swc: float, sorw: float):
    """ОФП Бейкера при Sg = 0 (как в rigis.compute): (krw(Sw), kro(Sw))."""
    krw = corey(prm["end_water"], prm["exw_ow"], swc, 1 - sorw)
    span = max(1 - sorw - swl, 1e-12)
    kro = lambda s: prm["end_oil"] * np.clip(1 - (np.asarray(s) - swl) / span, 0.0, 1.0) ** prm["exo_ow"]  # noqa: E731
    return krw, kro


def gas_oil_kr(prm: dict, swl: float, sw: float):
    """ОФП нефть–газ при связанной воде Sw: (krg(Sg), kro(Sg))."""
    span_g = max(1 - prm["sorg_og"] - prm["sgcr_og"] - swl, 1e-12)
    krg = lambda g: prm["end_gas"] * np.clip((np.asarray(g) - prm["sgcr_og"]) / span_g, 0.0, 1.0) ** prm["exg_og"]  # noqa: E731
    span_o = max(1 - prm["sorg_og"] - swl, 1e-12)
    kro = lambda g: prm["end_oil"] * np.clip(1 - (np.asarray(g) + sw - swl) / span_o, 0.0, 1.0) ** prm["exo_og"]  # noqa: E731
    return krg, kro


def gravity_number(k_v: float, area: float, d_rho: float, mu_o: float, q_t: float) -> float:
    """Ng = k_v·A·Δρ·g/(μo·q_t): k_v, мД; A, м²; Δρ, кг/м³; μ, сП; q_t, м³/сут пластовых."""
    if q_t <= 0:
        return 0.0
    return GRAV_RATE * k_v * area * d_rho / (mu_o * q_t)


def dietz_critical_rate(k_v: float, area: float, d_rho: float, kr_d_end: float, mu_d: float,
                        kr_o_end: float, mu_o: float) -> float:
    """Предел устойчивости вертикального фронта (Дитц), м³/сут пластовых; inf при M ≤ 1."""
    m = (kr_d_end / mu_d) / (kr_o_end / mu_o) if kr_o_end > 0 else math.inf
    if m <= 1:
        return math.inf
    return GRAV_RATE * k_v * kr_d_end * area * d_rho / (mu_d * (m - 1))


# --- перетоки вдоль ствола ----------------------------------------------------------------

def crossflow_eps(slices, res, open_mask, kv_kh: float, trans_mult: float = 1.0) -> list:
    """Доля потенциала среза, приходящая к ближайшему фильтру по пласту, если срез закрыт.

    Считается для всех работающих срезов (для вскрытых — «если бы закрыли»: путь к
    ближайшему другому вскрытому срезу). open_mask — вскрыт ли срез; trans_mult —
    множитель проводимости пласта вдоль ствола (калибровка, 0 — перетоков нет).
    """
    n = len(slices)
    out = [0.0] * n
    if trans_mult <= 0:
        return out
    aniso = math.sqrt(1 / kv_kh) if kv_kh > 0 else 1.0

    def seg_len(j, frac=1.0):
        s = slices[j]
        dz = (s.bottom_tvd - s.top_tvd) if s.bottom_tvd > s.top_tvd else 0.0
        return frac * math.sqrt(s.h ** 2 + (dz * aniso) ** 2)

    for i, (s, r) in enumerate(zip(slices, res)):
        if not r.used or r.pi <= 0:
            continue
        area = max(r.h_eff, 1e-6) * 2 * max(r.r_contour, 1e-6)
        mu_b = max(r.mu, 1e-9) * max(r.b, 1e-9)
        cond = 0.0
        for step in (-1, 1):
            j, rsum = i + step, seg_len(i, 0.5) / max(s.perm, K_BARRIER)
            while 0 <= j < n and not open_mask[j]:
                rsum += seg_len(j) / max(slices[j].perm, K_BARRIER)
                j += step
            if 0 <= j < n:
                rsum += seg_len(j, 0.5) / max(slices[j].perm, K_BARRIER)
                cond += 1.0 / (mu_b * rsum / (DARCY * area * trans_mult))
        if cond > 0:
            out[i] = 1.0 / (1.0 + r.pi / cond)
    return out
