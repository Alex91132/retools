# -*- coding: utf-8 -*-
"""Физика расчёта интервала РИГИС: продуктивность, депрессия, ОФП, запасы.

Дословный порт VBA-модулей RE Tools (константы и ветвления сохранены):
- d__Productivity_3_1.Get_J_obsolete + d2____Pd_hor_3_1 (ГС, Babu–Odeh) +
  d1____Pd_ver_3_1 (вертикальная, Чекалюк);
- e__dP.Get_dP — депрессия по Вогелю с учётом обводнённости;
- b_RG_3Ph_Model — ОФП Бейкера (нефть/газ/вода), Fw, вязкость и B смеси, ГФ;
- g__Misc.Get_N, Get_Jd — запасы на скважину, безразмерная продуктивность;
- u7_PVT — вязкость и объёмный коэффициент воды (McCain).
"""
from __future__ import annotations

from math import exp, log, pi

PI = 3.14159265358979          # константа модулей d1/d2 (не math.pi — как в VBA)
ATMA_MPA = 0.101325
T_K_MIN = 273                  # const_t_K_min Unifloc: °C -> К через 273, не 273.15


# --- Продуктивность ствола (Get_J_obsolete) ----------------------------------

def _x_d(x_i: float, x_n: float) -> float:
    return 0.0 if x_n == 0 else x_i / x_n


def _t_d(k: float, phi: float, mu: float, c_t: float, x_n: float, t: float) -> float:
    if phi * mu * c_t * x_n == 0:
        return 0.0
    return (k * t) / (115.75 * phi * mu * c_t * x_n ** 2)


def _f_sy(x: float) -> float:
    return -PI * x * log(PI * x) + PI * x + (PI * x) ** 3 / 72 + (PI * x) ** 5 / 14400


def _sx_h(a_d, h_d):
    return (PI * a_d) / (6 * h_d)


def _sxz_h(h_d, r_d_w):
    return log(h_d / r_d_w) - log(2 * PI)


def _sy_h(a_d, b_d, h_d, r_d_w):
    tail = (b_d - 1) * (-log(r_d_w * (1 / a_d ** 2 + 1 / h_d ** 2) ** 0.5) - 1.05)
    if a_d >= b_d:
        return 2 * b_d ** 2 * (_f_sy(1 / (2 * b_d)) - _f_sy(1 - 1 / (2 * b_d))) / (PI * h_d) + tail
    return (PI * b_d ** 2 * (1 + (1 / (2 * b_d)) * (1 / b_d - 3)) / (6 * a_d * h_d)
            + PI * a_d * (b_d - 1) / (6 * h_d) + tail)


def _pd_er_h(h_d, r_d_w, s, t_d):
    return 0.5 * h_d * (log(t_d / r_d_w ** 2) + 0.81 + 2 * s)


def _pd_el_h(h_d, r_d_w, s, t_d_el, t_d):
    return _pd_er_h(h_d, r_d_w, s, t_d_el) + 2 * PI ** 0.5 * (t_d ** 0.5 - t_d_el ** 0.5)


def pd_horizontal(a_d: float, b_d: float, h_d: float, r_d_w: float, s: float, t_d: float) -> float:
    """Get_Pd_h: безразмерный перепад ГС по режимам течения (Babu–Odeh)."""
    t_pss = 0.116 * a_d ** 2
    t_ll = 0.018 * (2 * b_d - 1) ** 2
    t_lpr = 0.116 * h_d ** 2 if 0.08 < 0.116 * h_d ** 2 else 0.08
    t_el = 0.116 * h_d ** 2
    if t_d >= t_pss:
        # в оригинале на псевдостационаре подставляется время выхода t_d_pss
        if a_d * b_d == 0:
            return 0.0
        return ((h_d / b_d) * (_sx_h(a_d, h_d) + _sxz_h(h_d, r_d_w) + _sy_h(a_d, b_d, h_d, r_d_w) + b_d * s)
                + 2 * PI * t_pss / (a_d * b_d))
    if t_d >= t_ll:
        if h_d * b_d == 0:
            return 0.0
        return (h_d / b_d) * (2 * PI ** 0.5 * (t_d / h_d ** 2) ** 0.5 + _sxz_h(h_d, r_d_w)
                              + _sy_h(a_d, b_d, h_d, r_d_w) + b_d * s)
    if t_d >= t_lpr:
        if t_d * t_lpr <= 0:
            return 0.0
        return _pd_el_h(h_d, r_d_w, s, t_el, t_lpr) + 0.5 * log(t_d / t_lpr)
    if t_d >= t_el:
        return _pd_el_h(h_d, r_d_w, s, t_el, t_d)
    if t_d > 0:
        return _pd_er_h(h_d, r_d_w, s, t_d)
    return 0.0


def pd_vertical(r_d_e: float, s: float, t_d: float) -> float:
    """Get_Pd_v: установившийся режим ln(r_e/r_w)+s, неустановившийся — Чекалюк."""
    t_ss = (1 / PI) * (r_d_e - exp(-s)) ** 2
    if t_d >= t_ss:
        return 0.0 if r_d_e <= 0 else log(r_d_e) + s
    if t_d > 0:
        arg = 1 + (PI * t_d / exp(-2 * s)) ** 0.5
        return 0.0 if arg <= 0 else log(arg)
    return 0.0


def _get_pd(l, r_e, h, i_k, r_w, k_h, phi, mu, c_t, s, t_p):
    if l > 0:
        if i_k == 0:
            return 0.0
        if (1.27 * h / i_k + 0.5 * l) < l:
            r_e_min = l / PI ** 0.5
        else:
            r_e_min = (1.27 * h / i_k + 0.5 * l) / PI ** 0.5
        r_e = max(r_e, r_e_min)
        a_d = _x_d(r_e * PI ** 0.5, l)
        b_d = _x_d(r_e * PI ** 0.5, l)
        h_d = _x_d(h, l * i_k)
        r_d_w = _x_d(r_w, l * i_k ** 0.5)
        t_d_p = _t_d(k_h, phi, mu, c_t, l, t_p)
        return pd_horizontal(a_d, b_d, h_d, r_d_w, s, t_d_p)
    if l == 0:
        return pd_vertical(_x_d(r_e, r_w), s, _t_d(k_h, phi, mu, c_t, r_w, t_p))
    return 0.0


def get_j_obsolete(i_k_2: float, phi: float, l: float, t_p: float, r_e: float, r_w: float,
                   h: float, k_h: float, s: float, mu: float, c_t: float, b: float,
                   r_f: float = 0.3, frac_count: int = 0, w_f: float = 0.0, k_f: float = 0.0) -> float:
    """Коэффициент продуктивности ствола, м³/сут/атм (Get_J_obsolete).

    i_k_2 — Kv/Kh; l — длина ГС (0 — вертикальная), м; t_p — время, сут;
    r_e — радиус контура, м; h — мощность, м; k_h — проницаемость, мД.
    Ветка ГРП (frac_count > 0) в расчёте РИГИС не используется и не перенесена.
    """
    if l > 0 and frac_count > 0:
        raise NotImplementedError("ветка ГРП Get_J_obsolete (Pw_Rect_Noflow) не перенесена")
    pd = _get_pd(l, r_e, h, i_k_2 ** 0.5, r_w, k_h, phi, mu, c_t, s, t_p)
    jd = 0.0 if pd == 0 else 1 / pd
    if b * mu == 0:
        return 0.0
    return (k_h * h) / (18.42 * b * mu) * jd


def get_jd(mu: float, b: float, k_h_h: float, j: float) -> float:
    """Get_Jd (g__Misc): Jd = 18.42·µ·B·J / (k·h)."""
    return 0.0 if k_h_h == 0 else 18.42 * mu * b * j / k_h_h


# --- Депрессия (Get_dP) ------------------------------------------------------

def get_dp(pb: float, pwf: float, f_w: float, pr: float) -> float:
    """Депрессия с учётом газа и обводнённости (Вогель), атм."""
    if pb > pr:
        pb = pr
    if f_w == 100:
        return pr - pwf
    pwf_g = (4 / 9) * (f_w / 100) * pb
    if pwf >= pb:
        return pr - pwf
    if pwf < pwf_g:
        tgb_r = (81 - 80 * (0.999 * pb - 0.0018 * (pr - pb)) / pb) ** 0.5
        tgb = f_w / 100 + (0.125 * (1 - f_w / 100) * pb * (-1 + tgb_r)) / (0.001 * (pr - (4 / 9) * pb))
        return (pwf_g + (pr - (4 / 9) * pb) * tgb - pwf) / tgb
    a = (pwf + 0.125 * (1 - f_w / 100) * pb - (f_w / 100) * pr) / (0.125 * (1 - f_w / 100) * pb)
    bb = (f_w / 100) / (0.125 * (1 - f_w / 100) * pb)
    c = 2 * a * bb + 144 / pb
    d = a ** 2 - 144 * (pr - pb) / pb - 81
    if bb == 0:
        return -d / c
    return (-c + (c ** 2 - 4 * bb ** 2 * d) ** 0.5) / (2 * bb ** 2)


# --- ОФП Бейкера и свойства смеси -------------------------------------------

def kro_baker(sw, swl, sg, sorg_og, sorw_ow, fo, exo_ow, exo_og) -> float:
    sd = 1.0 if (1 - sorw_ow - swl) == 0 else (sw - swl + sg) / (1 - sorw_ow - swl)
    kro_ow = fo * (1 - sd) ** exo_ow
    if sg == 0:
        return kro_ow
    kro_og = fo * (1 - (sg + sw - swl) / (1 - sorg_og - swl)) ** exo_og
    return (kro_ow * (sw - swl)) / (sg + (sw - swl)) + (kro_og * sg) / ((sw - swl) + sg)


def krg_baker(sw, swl, so, sg, sorg_og, final_gas, sgcr, exg_og, sorw_ow, swcr) -> float:
    if sg < sgcr:
        return 0.0
    krg_og = ((sg - sgcr) / (1 - sorg_og - sgcr - swl)) ** exg_og * final_gas
    krg_gw = ((sg - sgcr) / (1 - sgcr - swl)) ** exg_og * final_gas
    return (krg_gw * (sw - swl) + krg_og * (so - sorg_og)) / ((sw - swl) + (so - sorg_og))


def krw_baker(sw, swc, so, sg, sorg_og, final_water, sorw_ow, exw_ow, swl) -> float:
    if sw <= swc:
        return 0.0
    sd = (sw - swc) / (1 - sorw_ow - swc)
    sd_mod = sd if (sw - sg * sg / (1 - sw) - swc) <= 0 else ((sw - sg * sg / (1 - sw)) - swc) / (1 - sorw_ow - swc)
    krw_ow = final_water * sd ** exw_ow
    krw_gw = final_water * sd_mod ** exw_ow
    sgr = 1 - sorg_og - swl
    sor = 1 - sorw_ow - swl
    return (krw_ow * (so - sor) + krw_gw * (sg - sgr)) / ((so - sor) + (sg - sgr))


def fw_from_kr(mu_w, mu_o, bo, bw, k_rw, k_ro) -> float:
    """Get_Fw_from_Krealtive: обводнённость, %."""
    if k_rw * mu_o * bo == 0:
        return 0.0
    den = 1 + (k_ro * mu_w * bw) / (k_rw * mu_o * bo)
    return 0.0 if den == 0 else 100 / den


def mu_from_kr(mu_w, mu_o, k_rw, k_ro) -> float:
    den = k_ro * mu_w + k_rw * mu_o
    return 0.0 if den == 0 else (mu_w * mu_o) / den


def b_liq(bo, bw, f_w) -> float:
    if bw == 0:
        bw = 1.0
    return bo * (1 - f_w / 100) + bw * f_w / 100


def gor(rs, krg, kro, muo, bo, mug, bg) -> float:
    return rs + (krg / kro) * ((muo * bo) / (mug * bg))


def get_n(phi, bo, ro_o, r_e, sw, h) -> float:
    """Get_N: геологические запасы, тыс. т (при ro_o в т/м³ — как в книге)."""
    if bo == 0:
        return 0.0
    return (pi * r_e ** 2 * h * phi * (1 - sw) * ro_o) / (1000 * bo)


# --- Вода (McCain, Unifloc) -------------------------------------------------

def _sal_ppm(gamma_w: float) -> float:
    return ((624.711071129603 * gamma_w / 0.0160185 - 20192.9595437054) ** 0.5 - 137.000074965329) * 10000


def mu_water_cP(p_atma: float, t_C: float, gamma_w: float) -> float:
    t_k = t_C + T_K_MIN
    wp = _sal_ppm(gamma_w) / 10000
    a = 109.574 - 8.40564 * wp + 0.313314 * wp ** 2 + 0.00872213 * wp ** 3
    b = (-1.12166 + 0.0263951 * wp - 0.000679461 * wp ** 2 - 5.47119e-5 * wp ** 3 + 1.55586e-6 * wp ** 4)
    visc = a * (1.8 * t_k - 460) ** b
    psi = p_atma * ATMA_MPA * 145.04
    return visc * (0.9994 + 4.0295e-5 * psi + 3.1062e-9 * psi ** 2)


def bw_m3m3(p_atma: float, t_C: float) -> float:
    f = 1.8 * (t_C + T_K_MIN) - 460
    psi = p_atma * ATMA_MPA * 145.04
    dvwp = -1.95301e-9 * psi * f - 1.72834e-13 * psi ** 2 * f - 3.58922e-7 * psi - 2.25341e-10 * psi ** 2
    dvwt = -1.0001e-2 + 1.33391e-4 * f + 5.50654e-7 * f ** 2
    return (1 + dvwp) * (1 + dvwt)
