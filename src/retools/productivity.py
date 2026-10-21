# -*- coding: utf-8 -*-
"""Коэффициент продуктивности скважины Get_J — порт VBA RE Tools (c__Productivity,
c11____WellTest_func, c8____Rectangular_reservoir, c2/c3/c4/c5/c6, c9/c10).

Модель книги: нестационарный приток при постоянном забойном давлении к скважине
в центре прямоугольной области дренирования площадью π·Rконт² (соотношение
сторон — оптимальное по Батлеру 1 + L²/S), боковые границы — постоянное
давление (пластовое), кровля и подошва непроницаемы. Решение в пространстве
Лапласа, обращение — Стефест (N = 10). Дебит на 1 атм за время t_p, сут:
    J = k·h/(18,42·B·μ) · qD(tD).
Типы заканчивания (Get_Completion): ННС, ННС+ГРП, ГС, ГС+ГРП (МГРП, трещины
вдоль или поперёк ствола), МЗС (боковые стволы под углом 30° — глобальная
константа psi_lateral модуля c6).

Порт дословный, включая константы модулей (tiny, MAXIT, PART_SUM_NUM разные в
c2 и c8) и π = 3,14159265358979; ветви, не используемые при настройках книги
(метод расчёта 1, коррекция низкой проводимости 2, границы «cccc»/«nn»),
не переносились — на них стоит NotImplementedError.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from scipy import special

PI_ = 3.14159265358979
GAMMA = 0.577215664901533
N_STEHFEST = 10                 # number_of_lapl_coeff
LOW_FCD = 0.6
MEDIUM_FCD = 1.0
CALC_OPTION = 1                 # defCalcOption
CORRECT_LOW_FCD = 2             # defCorrect_for_low_FcD
PSI_LATERAL = 30.0              # c6: Public Const psi_lateral
MULTILAT_FIRST_BRANCH_COEFF = 0.0
DEF_ETA_D = 1e7
DEF_WD = 0.00005


class C8:
    """Константы модуля c8____Rectangular_reservoir."""
    tiny = 0.00000001
    MAXIT = 100
    PART_SUM_NUM = 5
    small = 1e-300
    LARGE_S = 1e-300
    small_bessel_arg = 0.0001


class C2:
    """Константы модуля c2____Additives_hor_well."""
    tiny = 0.0000000001
    small = 1e-300
    MAXIT = 1000
    PART_SUM_NUM = 5
    PART_SUM_NUM_b2_1 = 10
    PART_SUM_NUM_b2_2 = 10
    PART_SUM_NUM_f_4 = 10000
    PART_SUM_NUM_f_3 = 5
    PART_SUM_NUM_b1 = 5
    PART_SUM_NUM_b3 = 5
    LARGE_S = 1e-300
    tiny1 = 0.00000001


def _exp(x: float) -> float:
    """Exp VBA: переполнение — ошибка, «исчезновение» — 0."""
    return math.exp(x)


# --- спецфункции ----------------------------------------------------------------

def bessel_k(x: float, n: int) -> float:
    """BesselK (IK01A) — K0/K1."""
    return float(special.k0(x) if n == 0 else special.k1(x))


def bessel_k_asympt_excl_exp(x: float, n: int) -> float:
    """BesselK_01_ASYMPT_EXCL_EXP: K_n(x)·e^x."""
    return float(special.k0e(x) if n == 0 else special.k1e(x))


def bessi0(x: float) -> float:
    """bessi0 (c9): полиномиальное приближение (Numerical Recipes)."""
    ax = abs(x)
    if ax < 3.75:
        y = x / 3.75
        y = y * y
        ans = 0.0360768 + y * 0.0045813
        ans = 0.2659732 + y * ans
        ans = 1.2067492 + y * ans
        ans = 3.0899424 + y * ans
        ans = 3.5156229 + y * ans
        return 1.0 + y * ans
    y = 3.75 / ax
    ans = (-0.01647633 + y * 0.00392377)
    ans = 0.02635537 + y * ans
    ans = -0.02057706 + y * ans
    ans = 0.00916281 + y * ans
    ans = -0.00157565 + y * ans
    ans = 0.00225319 + y * ans
    ans = 0.01328592 + y * ans
    ans = 0.39894228 + y * ans
    return (_exp(ax) / math.sqrt(ax)) * ans


def bessk0(x: float) -> float:
    """bessk0 (c9): полиномиальное приближение (Numerical Recipes)."""
    if x <= 2.0:
        y = x * x / 4.0
        bi = bessi0(x)
        ans = 0.0001075 + y * 0.0000074
        ans = 0.00262698 + y * ans
        ans = 0.0348859 + y * ans
        ans = 0.23069756 + y * ans
        ans = 0.4227842 + y * ans
        ans = -0.57721566 + y * ans
        return -math.log(x / 2.0) * bi + ans
    y = 2.0 / x
    ans = -0.0025154 + y * 0.00053208
    ans = 0.00587872 + y * ans
    ans = -0.01062446 + y * ans
    ans = 0.02189568 + y * ans
    ans = -0.07832358 + y * ans
    ans = 1.25331414 + y * ans
    return _exp(-x) / math.sqrt(x) * ans


def fast_ik0(x: float) -> float:
    """fast_ik0 (c9): интеграл K0 от 0 до x рядом; при x > 18 — π/2."""
    tiny = 1e-17
    if x <= 0.0:
        return 0.0
    if x > 18.0:
        return PI_ * 0.5
    x2 = x * 0.5
    x2_k = kfct = part1 = part2 = 1.0
    part3 = sum1n = 0.0
    k = 0.0
    while True:
        k += 1
        kfct = kfct * k
        x2_k = x2_k * x2
        inc = x2_k / kfct
        inc = inc * inc
        div2k = 1 / (k + k + 1.0)
        inc = inc * div2k
        part1 += inc
        part2 += inc * div2k
        sum1n += 1 / k
        part3 += inc * sum1n
        if not (30 * inc / part3) >= tiny:
            break
    ans = -(math.log(x2) + GAMMA) * part1 * x
    ans = ans + part2 * x
    return ans + part3 * x


def ki1(x: float) -> float:
    return PI_ / 2 - fast_ik0(x)


GAUSS8_X = (-0.96028986, -0.79666648, -0.52553242, -0.18343464, 0.18343464, 0.52553242, 0.79666648, 0.96028986)
GAUSS8_C = (0.10122854, 0.22238104, 0.31370664, 0.36268378, 0.36268378, 0.31370664, 0.22238104, 0.10122854)
INT_M = 5


def int_k0_gauss_dw_(u: float, x: float, y: float) -> float:
    """int_k0_gauss_DW_ (c9): интеграл K0(u·√((x−ξ)²+y²)) по ξ от −1 до 1, Гаусс 8 точек на 5 отрезках."""
    a, b, m = -1.0, 1.0, INT_M
    total = 0.0
    for j in range(m):
        for i in range(8):
            xi = (a + (b - a) / m * j + a + (b - a) / m * (j + 1)) / 2 + (b - a) / m / 2 * GAUSS8_X[i]
            total += GAUSS8_C[i] * bessk0(u * math.sqrt((x - xi) ** 2 + y ** 2))
    return (b - a) * total / 2 / m


def stehfest_coef(n: int = N_STEHFEST) -> list[float]:
    """Coef (c9): коэффициенты Стефеста V(1..n), индекс 0 не используется."""
    g = [0.0] * 161
    h = [0.0] * 81
    v = [0.0] * (n + 1)
    g[1] = 1.0
    nh = n // 2
    for i in range(2, n + 1):
        g[i] = g[i - 1] * i
    h[1] = 2.0 / g[nh - 1]
    for i in range(2, nh + 1):
        fi = float(i)
        if i != nh:
            h[i] = (fi ** nh) * g[2 * i] / (g[nh - i] * g[i] * g[i - 1])
        else:
            h[i] = (fi ** nh) * g[2 * i] / (g[i] * g[i - 1])
    sn = 2 * (nh - (nh // 2) * 2) - 1
    for i in range(1, n + 1):
        v[i] = 0.0
        k1 = (i + 1) // 2
        k2 = min(i, nh)
        for k in range(k1, k2 + 1):
            if 2 * k - i == 0:
                v[i] += h[k] / g[i - k]
            elif i == k:
                v[i] += h[k] / g[2 * k - i]
            else:
                v[i] += h[k] / (g[i - k] * g[2 * k - i])
        v[i] = sn * v[i]
        sn = -sn
    return v


def sumexp(arg: float, yed: float) -> float:
    """sumexp (c2): Σ exp(−2·m·yed·arg)."""
    total, m = 0.0, 0
    while True:
        m += 1
        inc = _exp(-2 * m * yed * arg)
        total += inc
        if not inc > C2.tiny * total:
            return total


# --- прямоугольный пласт (c8) -------------------------------------------------------

def unit_cylinder_source(s: float, r_d: float) -> float:
    r_d = abs(r_d)
    u = math.sqrt(s) if s > 0 else -1.0
    if (r_d * u / 2) > C8.small_bessel_arg:
        if u * r_d < 100:
            return 1 / (2 * PI_) * bessel_k(u * r_d, 0) / (u * bessel_k(u, 1))
        if r_d < 5:
            return (1 / (2 * PI_) * bessel_k_asympt_excl_exp(u * r_d, 0) / (u * bessel_k_asympt_excl_exp(u, 1))
                    * _exp(-u * (r_d - 1)))
        return 0.0
    if u < 0:
        u = 1.0
    return 1 / (2 * PI_) * (-math.log(r_d * u / 2) - GAMMA)


def pd_b1(s, yd, ywd, yed, xed, xbound, ybound, subtract_inf=True) -> float:
    if xbound == "c":
        return 0.0
    raise NotImplementedError("pd_b1: границы по x «n» в настройках книги не используются")


def pd_b2_k(k, s, xd, xwd, xed, yd, ywd, yed, xbound, ybound, compl_type, subtract_inf) -> float:
    if xbound == "n":
        part1 = 2 / xed * math.cos(k * PI_ * xd / xed) * math.cos(k * PI_ * xwd / xed)
    elif xbound == "c":
        part1 = 2 / xed * math.sin(k * PI_ * xd / xed) * math.sin(k * PI_ * xwd / xed)
    else:
        part1 = 0.0
    if compl_type == "frac":
        part1 = 2 / 2 * xed / PI_ / k * math.sin(k * PI_ / xed) * part1
    elif compl_type != "vert":
        return 0.0
    signum = -1.0 if ybound == "c" else 1.0
    sbtr_inf = 0.0 if subtract_inf else 1.0
    ek = math.sqrt(s + k ** 2 * PI_ ** 2 / xed ** 2)
    smexp = sumexp(ek, yed)
    part2 = (_exp(-ek * abs(yd - ywd)) * (sbtr_inf + smexp)
             + (signum * _exp(-ek * (yd + ywd)) + _exp(-ek * (2 * yed - abs(yd - ywd)))
                + signum * _exp(-ek * (2 * yed - (yd + ywd)))) * (1 + smexp))
    part2 = 1 / (2 * ek) * part2
    return part1 * part2


def pd_b2_2(s, xd, xwd, xed, yd, ywd, yed, xbound, ybound, compl_type, subtract_inf=True) -> float:
    total, k = 0.0, 1
    while True:
        psum = psumabs = 0.0
        for _ in range(C8.PART_SUM_NUM):
            add = pd_b2_k(k, s, xd, xwd, xed, yd, ywd, yed, xbound, ybound, compl_type, subtract_inf)
            psum += add
            psumabs += abs(add)
            k += 1
        total += psum
        if not (abs(psumabs) / C8.PART_SUM_NUM >= C8.tiny * (abs(total) + C8.tiny) and k < C8.MAXIT):
            return total


def pdb3_sub(k, s, xd, xwd, xed, yd, ywd, sgn1, sgn2, compl_type) -> float:
    xd1 = abs(xd + sgn1 * xwd + sgn2 * 2 * k * xed)
    yd1 = abs(yd - ywd)
    if compl_type == "frac":
        return unit_fracture_func(s, xd1, yd1)
    if compl_type == "vert":
        return unit_cylinder_source(s, math.sqrt(xd1 ** 2 + yd1 ** 2))
    return 0.0


def pd_b3(s, xd, xwd, xed, yd, ywd, xbound, ybound, compl_type) -> float:
    signum = -1.0 if xbound == "c" else 1.0
    total = (pdb3_sub(0, s, xd, xwd, xed, yd, ywd, -1, 1, compl_type)
             + signum * pdb3_sub(0, s, xd, xwd, xed, yd, ywd, 1, 1, compl_type))
    k = 1
    while True:
        add = (signum * pdb3_sub(k, s, xd, xwd, xed, yd, ywd, 1, 1, compl_type)
               + pdb3_sub(k, s, xd, xwd, xed, yd, ywd, -1, 1, compl_type)
               + signum * pdb3_sub(k, s, xd, xwd, xed, yd, ywd, 1, -1, compl_type)
               + pdb3_sub(k, s, xd, xwd, xed, yd, ywd, -1, -1, compl_type))
        total += add
        k += 1
        if not abs(add) >= C8.tiny * (abs(total) + C8.tiny):
            return total


def pd_lapl_rect(s, xd, xwd, xed, yd, ywd, yed, xbound, ybound, compl_type) -> float:
    if abs(xed - 2) < C8.tiny:
        return pd_b1(s, yd, ywd, yed, xed, xbound, ybound, False)
    if s > C8.LARGE_S * xed ** 2 and abs(yd - ywd) < C8.tiny:
        return (pd_b1(s, yd, ywd, yed, xed, xbound, ybound, True)
                + pd_b2_2(s, xd, xwd, xed, yd, ywd, yed, xbound, ybound, compl_type, True)
                + pd_b3(s, xd, xwd, xed, yd, ywd, xbound, ybound, compl_type))
    return (pd_b1(s, yd, ywd, yed, xed, xbound, ybound, False)
            + pd_b2_2(s, xd, xwd, xed, yd, ywd, yed, xbound, ybound, compl_type, False))


def pd_vert_rect_lapl(s, xd, yd, xwd, ywd, xed, yed, xbound, ybound, skin=0.0) -> float:
    rho = math.sqrt((xd - xwd) ** 2 + (yd - ywd) ** 2)
    in_wellbore = rho <= 1 + C8.tiny
    xd1, yd1 = (xwd + 1, ywd) if in_wellbore else (xd, yd)
    if not s > 0:
        raise NotImplementedError("pd_rect_BD: режим границ (s ≤ 0) не используется")
    pwd = pd_lapl_rect(s, xd1, xwd, xed, yd1, ywd, yed, xbound, ybound, "vert")
    if in_wellbore:
        pwd += skin / (2 * PI_)
    return pwd


def unit_fracture_func(s, xd, yd) -> float:
    """Единичная трещина [−1, 1] с равномерным притоком (c8)."""
    u = math.sqrt(s) if s > 0 else -1.0
    if (math.sqrt(xd ** 2 + yd ** 2) + 1) * u / 2 > C8.small_bessel_arg:
        if abs(yd) < C8.tiny:
            if abs(xd) <= 1:
                lim1, lim2, sign = u * (1 + xd), u * (1 - xd), 1
            else:
                lim1, lim2, sign = u * (1 + abs(xd)), u * (abs(xd) - 1), -1
            return 1 / 2 * 1 / (2 * PI_) * 1 / u * (fast_ik0(lim1) + sign * fast_ik0(lim2))
        return 1 / 2 * 1 / (2 * PI_) * int_k0_gauss_dw_(u, xd, yd)
    if u < 0:
        u = 1.0
    if abs(yd) > C8.tiny:
        dpd = (1 / 4 * ((xd - 1) * math.log((xd - 1) ** 2 + yd ** 2) - (xd + 1) * math.log((xd + 1) ** 2 + yd ** 2))
               + 1 / 2 * yd * (math.atan((xd - 1) / yd) - math.atan((xd + 1) / yd)) + 1)
    else:
        dpd = 1 / 4 * ((xd - 1) * math.log((xd - 1) ** 2) - (xd + 1) * math.log((xd + 1) ** 2)) + 1
    return 1 / (2 * PI_) * (dpd + math.log(2) - GAMMA - math.log(u))


# --- горизонтальная скважина: слагаемые модуля c2 -------------------------------------

def _zpart(n, zd, zwd, zed, zb_up, zb_down):
    if zb_up == "c" and zb_down == "c":
        return math.sin(n * PI_ * zd / zed) * math.sin(n * PI_ * zwd / zed)
    return math.cos(n * PI_ * zd / zed) * math.cos(n * PI_ * zwd / zed)


def _n_of(k, zb_up, zb_down):
    mixed = (zb_up == "c" and zb_down == "n") or (zb_up == "n" and zb_down == "c")
    return (2 * k - 1) / 2 if mixed else k


def f_2(s, zd, zwd, zed, ld, zb_up, zb_down) -> float:
    if not (zb_up == "n" and zb_down == "n"):
        raise NotImplementedError("f_2: кровля/подошва не nn")
    add1 = add2 = 1.0
    total = 0.0
    u = math.sqrt(s)
    n = 1
    sign1 = 1
    while add1 + add2 >= 1e-20:
        for sign in (-1, 1):
            arg1 = abs(zd / zed + zwd / zed + sign * 2 * n) * u / ld
            arg2 = abs(zd / zed - zwd / zed + sign * 2 * n) * u / ld
            add1 = bessk0(arg1)
            add2 = bessk0(arg2)
            total = total + sign1 * add1 + add2
        n += 1
    total = total + sign1 * bessk0(abs(zd / zed + zwd / zed) * u / ld) + bessk0(abs(zd / zed - zwd / zed) * u / ld)
    return 1 / ld * total


def f_3_k(k, s, xd, xwd, zd, zwd, zed, ld, zb_up, zb_down) -> float:
    n = _n_of(k, zb_up, zb_down)
    part1 = _zpart(n, zd, zwd, zed, zb_up, zb_down)
    e_n = math.sqrt(s + (n * PI_ * ld) ** 2)
    if abs(xd - xwd) <= 1:
        return part1 / e_n * (ki1(e_n * (1 + xd - xwd)) + ki1(e_n * (1 - xd + xwd)))
    return part1 / e_n * (ki1(e_n * (abs(xd - xwd) - 1)) - ki1(e_n * (1 + abs(xd - xwd))))


def _partial_series(term, part_num, tiny, maxit) -> float:
    """Цикл книги: блоки по part_num членов, пока средний модуль члена ≥ tiny·(|Σ| + tiny) и k < MAXIT."""
    total, k = 0.0, 1
    while True:
        psum = psumabs = 0.0
        for _ in range(part_num):
            add = term(k)
            psum += add
            psumabs += abs(add)
            k += 1
        total += psum
        if not (abs(psumabs) / part_num >= tiny * (abs(total) + tiny) and k < maxit):
            return total


def f_3_2(s, xd, xwd, zd, zwd, zed, ld, zb_up, zb_down) -> float:
    total = _partial_series(lambda k: f_3_k(k, s, xd, xwd, zd, zwd, zed, ld, zb_up, zb_down),
                            C2.PART_SUM_NUM_f_3, C2.tiny, C2.MAXIT)
    if (zb_up, zb_down) in (("c", "n"), ("n", "c"), ("c", "c")):
        return 2 * total
    if abs(xd - xwd) <= 1:
        return PI_ / math.sqrt(s) + 2 * total
    return 2 * total


def f_hor(s, xd, xwd, zd, zwd, zed, ld, yd, ywd, zb_up, zb_down) -> float:
    """f (c2)."""
    if s < 0:
        raise NotImplementedError("f_4_2: режим границ не используется")
    if abs(xd - xwd) <= 1:
        return 1 / 4 / PI_ * (f_2(s, zd, zwd, zed, ld, zb_up, zb_down)
                              - f_3_2(s, xd, xwd, zd, zwd, zed, ld, zb_up, zb_down))
    return 1 / 4 / PI_ * f_3_2(s, xd, xwd, zd, zwd, zed, ld, zb_up, zb_down)


def f_b1_2(s, xed, yd, ywd, yed, zd, zwd, zed, ld, zb_up, zb_down, xbound, ybound, subtract_inf) -> float:
    if xbound == "c":
        return 0.0
    raise NotImplementedError("F_b1_2: границы по x n")


def f_b2_k_1(p, m, s, yd, ywd, yed, xd, xwd, xed, zd, zwd, zed, ld, zb_up, zb_down, xbound, ybound,
             subtract_inf) -> float:
    sbtr_inf = 0.0 if subtract_inf else 1.0
    k = m
    n = _n_of(p, zb_up, zb_down)
    if xbound == "n":
        part1 = math.cos(k * PI_ * xd / xed) * math.cos(k * PI_ * xwd / xed)
    elif xbound == "c":
        part1 = math.sin(k * PI_ * xd / xed) * math.sin(k * PI_ * xwd / xed)
    else:
        part1 = 0.0
    sign = -1 if ybound == "c" else 1
    e = math.sqrt(s + (n * PI_ * ld) ** 2 + k ** 2 * PI_ ** 2 / xed ** 2)
    se = sumexp(e, yed)
    return (math.sin(PI_ * k / xed) * part1 / e / k
            * ((sign * _exp(-e * (yd + ywd)) + sign * _exp(-e * (2 * yed - yd - ywd))
                + _exp(-e * (2 * yed - abs(yd - ywd)))) * (1 + se) + _exp(-e * abs(yd - ywd)) * (sbtr_inf + se)))


def f_b2_k_2(p, s, yd, ywd, yed, xd, xwd, xed, zd, zwd, zed, ld, zb_up, zb_down, xbound, ybound, subtract_inf):
    return _partial_series(lambda k: f_b2_k_1(p, k, s, yd, ywd, yed, xd, xwd, xed, zd, zwd, zed, ld, zb_up, zb_down,
                                              xbound, ybound, subtract_inf),
                           C2.PART_SUM_NUM_b2_1, C2.tiny1, C2.MAXIT)


def f_b2_2(s, yd, ywd, yed, xd, xwd, xed, zd, zwd, zed, ld, zb_up, zb_down, xbound, ybound, subtract_inf) -> float:
    def term(p):
        n = _n_of(p, zb_up, zb_down)
        return _zpart(n, zd, zwd, zed, zb_up, zb_down) * f_b2_k_2(p, s, yd, ywd, yed, xd, xwd, xed, zd, zwd, zed, ld,
                                                                   zb_up, zb_down, xbound, ybound, subtract_inf)
    return 2 / PI_ * _partial_series(term, C2.PART_SUM_NUM_b2_2, C2.tiny1, C2.MAXIT)


def _integrals(p, xd, xwd, xed, e_n, a) -> float:
    if a == 1:
        v = xd - xwd - 2 * p * xed
        if abs(v) <= 1:
            return PI_ - ki1(e_n * (xd - xwd - 2 * p * xed + 1)) - ki1(e_n * (1 - xd + xwd + 2 * p * xed))
        return ki1(e_n * (abs(v) - 1)) - ki1(e_n * (abs(v) + 1))
    v = xd + xwd - 2 * p * xed
    if abs(v) <= 1:
        return PI_ - ki1(e_n * (xd + xwd - 2 * p * xed + 1)) - ki1(e_n * (1 - xd - xwd + 2 * p * xed))
    return ki1(e_n * (abs(v) - 1)) - ki1(e_n * (abs(v) + 1))


def f_b3_k(k, s, xd, xwd, xed, zd, zwd, zed, yd, ywd, ld, zb_up, zb_down, xbound) -> float:
    add1 = add2 = add3 = 1.0
    total = 0.0
    p = 1
    n = _n_of(k, zb_up, zb_down)
    part1 = _zpart(n, zd, zwd, zed, zb_up, zb_down)
    sign = -1 if xbound == "c" else 1
    e_n = math.sqrt(s + (n * PI_ * ld) ** 2)

    def one(p):
        return (-_integrals(p, xd, xwd, xed, e_n, 1) + ki1(e_n * (2 * p * xed + xd - xwd + 1))
                - ki1(e_n * (2 * p * xed + xd - xwd - 1)) - sign * _integrals(p, xd, xwd, xed, e_n, 2)
                + sign * ki1(e_n * (2 * p * xed + xd + xwd + 1)) - sign * ki1(e_n * (2 * p * xed + xd + xwd - 1)))

    while abs(add1) + abs(add2) + abs(add3) >= 1e-20:
        add1 = one(p)
        p += 1
        add2 = one(p)
        p += 1
        add3 = one(p)
        p += 1
        total = total + add1 + add2 + add3
    return part1 / e_n * (sign * ki1(e_n * (xd + xwd + 1)) - sign * ki1(e_n * (xd + xwd - 1)) + total)


def f_b3_2(s, xd, xwd, xed, zd, zwd, zed, yd, ywd, ld, zb_up, zb_down, xbound) -> float:
    total = _partial_series(lambda k: f_b3_k(k, s, xd, xwd, xed, zd, zwd, zed, yd, ywd, ld, zb_up, zb_down, xbound),
                            C2.PART_SUM_NUM_b3, C2.tiny, C2.MAXIT)
    return 1 / 2 / PI_ * total


def horizontal_well_for_cinco(s, xd, yd, zd, xwd, ywd, zwd, xed, yed, zed, xbound, ybound, zb_up, zb_down) -> float:
    ld = 1 / zed
    if not s > 0:
        raise NotImplementedError("режим границ (s ≤ 0) не используется")
    nn = zb_up == "n" and zb_down == "n"
    if abs(yd - ywd) < C8.tiny:
        # порядок сложения — как в формуле книги
        pwd = pd_lapl_rect(s, xd, xwd, xed, yd, ywd, yed, xbound, ybound, "frac") if nn else 0.0
        pwd = pwd + f_hor(s, xd, xwd, zd, zwd, zed, ld, yd, ywd, zb_up, zb_down)
        pwd = pwd + f_b1_2(s, xed, yd, ywd, yed, zd, zwd, zed, ld, zb_up, zb_down, xbound, ybound, True)
        pwd = pwd + f_b2_2(s, yd, ywd, yed, xd, xwd, xed, zd, zwd, zed, ld, zb_up, zb_down, xbound, ybound, True)
        return pwd - f_b3_2(s, xd, xwd, xed, zd, zwd, zed, yd, ywd, ld, zb_up, zb_down, xbound)
    tail = (f_b1_2(s, xed, yd, ywd, yed, zd, zwd, zed, ld, zb_up, zb_down, xbound, ybound, False)
            + f_b2_2(s, yd, ywd, yed, xd, xwd, xed, zd, zwd, zed, ld, zb_up, zb_down, xbound, ybound, False))
    if nn:
        return pd_lapl_rect(s, xd, xwd, xed, yd, ywd, yed, xbound, ybound, "frac") + tail
    return tail


def horizontal_rect_lapl(s, xd, yd, zd, xwd, ywd, zwd, xed, yed, zed, rwd, xbound, ybound, zb_up, zb_down,
                         skin) -> float:
    """horizontal_rect_lapl (c8), метод расчёта 1: точка 0,68 (Rosa, Carvalho)."""
    yd = ywd
    zd = zwd + rwd
    xd = xwd + 0.68
    pwd = horizontal_well_for_cinco(s, xd, yd, zd, xwd, ywd, zwd, xed, yed, zed, xbound, ybound, zb_up, zb_down)
    return pwd + skin / (2 * PI_) * zed / 2


# --- трещина ГРП (c8) -------------------------------------------------------------------

def _sh(x: float) -> float:
    if x >= 700:
        return 5.0711602737e303
    if x <= -700:
        return -5.0711602737e303
    return (_exp(x) - _exp(-x)) / 2


def _ch(x: float) -> float:
    if abs(x) >= 700:
        return 5.0711602737e303
    return (_exp(x) + _exp(-x)) / 2


def _tanh(x: float) -> float:
    if x >= 50:
        return 1 - 2 * _exp(-2 * x)
    if x <= -50:
        return -1 + 2 * _exp(2 * x)
    return _sh(x) / _ch(x)


def calcxd(cfd: float) -> float:
    """calcxd (c8): точка, где давление в трещине конечной проводимости равно давлению на забое."""
    if cfd < C8.tiny:
        return 0.0
    a0, a1, a2, a3, a4 = 0.759919, 0.465301, 0.562754, 0.363093, 0.0298881
    b0, b1, b2, b3, b4 = 1, 0.99477, 0.896679, 0.430707, 0.0467339
    v = math.log(cfd)
    return (a0 + a1 * v + a2 * v ** 2 + a3 * v ** 3 + a4 * v ** 4) / (b0 + b1 * v + b2 * v ** 2 + b3 * v ** 3 + b4 * v ** 4)


def p_tril_infinit_res(s, cfd, s_f, eta, xwd=0.0, xd=0.0) -> float:
    """Трилинейная модель трещины в бесконечном пласте (c8)."""
    u = (s + s ** 0.5) ** 0.5
    psi = (1 * (s / eta) + 2 / cfd * u / (1 + 2 / PI_ * s_f * u)) ** 0.5
    return 1 / (2 * cfd) / (psi * _tanh(psi)) * _ch(psi * (1 - abs(xwd - xd))) / _ch(psi)


def dpd_fincond_sf(s, cfd, sf, eta, uniform_flux) -> float:
    if uniform_flux:
        return sf / (2 * PI_)
    mult = 100000
    return p_tril_infinit_res(s, cfd, sf, eta) - p_tril_infinit_res(s, mult * cfd, 0 * sf, mult * eta)


def dpd_dxd(s, dxd) -> float:
    """dpd_dxd (c8) с необязательными аргументами по умолчанию — равномерный приток."""
    return unit_fracture_func(s, dxd, 0) - unit_fracture_func(s, 0, 0)


def pd_frac_rect_lapl(s, xd, yd, xwd, ywd, xed, yed, xbound, ybound, cfd, r_eff_xf, etad, sf, s_choke) -> float:
    """PD_Frac_Rect_Lapl (c8), метод расчёта 1 (десуперпозиция)."""
    uniform_flux = cfd < C8.tiny
    dxd = 0.0 if uniform_flux else calcxd(cfd)
    if abs(yd - ywd) < C8.tiny and abs(xd - xwd) < 1:
        pwd = (pd_lapl_rect(s, xwd + dxd, xwd, xed, yd, ywd, yed, xbound, ybound, "frac")
               + dpd_fincond_sf(s, cfd, sf, etad, uniform_flux) + dpd_dxd(s, abs(xd - xwd)))
        if abs(xd - xwd) < C8.tiny:
            pwd = pwd + s_choke / (2 * PI_)
        return pwd
    return pd_lapl_rect(s, xd, xwd, xed, yd, ywd, yed, xbound, ybound, "frac")


# --- наклонный сегмент бокового ствола МЗС (c1____Additives_dev_well) -------------------

class C1:
    """Константы модуля c1____Additives_dev_well."""
    tiny = 0.00000001
    MAXIT = 2000
    PART_SUM_NUM = 5


def _ie12_1(k, u, yd, ywd, yed, xwd, xed, th):
    c, sn = math.cos(th), math.sin(th)
    return (-_exp(-u * (yd + ywd + sn)) * xed * (u * xed * math.sin(k * PI_ * (xwd + c) / xed) * sn
                                                  + k * PI_ * c * math.cos(k * PI_ * (xwd + c) / xed))
            + _exp(-u * (yd + ywd - sn)) * xed * (u * xed * math.sin(k * PI_ * (xwd - c) / xed) * sn
                                                  + k * PI_ * c * math.cos(k * PI_ * (xwd - c) / xed)))


def _ie22_1(k, u, yd, ywd, yed, xwd, xed, th):
    c, sn = math.cos(th), math.sin(th)
    return (-_exp(-u * (2 * yed + yd - ywd + sn)) * xed * (u * xed * math.sin(k * PI_ * (xwd - c) / xed) * sn
                                                            - k * PI_ * c * math.cos(k * PI_ * (xwd - c) / xed))
            + xed * _exp(-u * (2 * yed + yd - ywd - sn)) * (u * xed * math.sin(k * PI_ * (xwd + c) / xed) * sn
                                                            - k * PI_ * c * math.cos(k * PI_ * (xwd + c) / xed)))


def _ie32_1(k, u, yd, ywd, yed, xwd, xed, th):
    c, sn = math.cos(th), math.sin(th)
    return (-_exp(-u * (2 * yed - yd - ywd + sn)) * xed * (u * xed * math.sin(k * PI_ * (xwd - c) / xed) * sn
                                                            - k * PI_ * c * math.cos(k * PI_ * (xwd - c) / xed))
            + xed * _exp(-u * (2 * yed - yd - ywd - sn)) * (u * xed * math.sin(k * PI_ * (xwd + c) / xed) * sn
                                                            - k * PI_ * c * math.cos(k * PI_ * (xwd + c) / xed)))


def _ie42_1(k, u, yd, ywd, yed, xwd, xed, th):
    c, sn = math.cos(th), math.sin(th)
    return (-_exp(-u * (2 * yed - yd + ywd + sn)) * xed * (u * xed * math.sin(k * PI_ * (xwd + c) / xed) * sn
                                                            + k * PI_ * c * math.cos(k * PI_ * (xwd + c) / xed))
            + xed * _exp(-u * (2 * yed - yd + ywd - sn)) * (u * xed * math.sin(k * PI_ * (xwd - c) / xed) * sn
                                                            + k * PI_ * c * math.cos(k * PI_ * (xwd - c) / xed)))


def _series_c1(term) -> float:
    return _partial_series(term, C1.PART_SUM_NUM, C1.tiny, C1.MAXIT)


def pd_b2_dw(s, xd, xwd, xed, yd, ywd, yed, theta, xbound, ybound, subtract_inf) -> float:
    """pd_b2_DW (c1); угол — уже приведённый к [0, 2π) (в VBA меняется по ссылке)."""
    if xbound != "c" or not subtract_inf:
        raise NotImplementedError("pd_b2_DW: используется только при границах «c» и subtract_inf")
    signum = -1.0 if ybound == "c" else 1.0

    def term(k):
        ek = math.sqrt(s + k ** 2 * PI_ ** 2 / xed ** 2)
        smexp = sumexp(ek, yed)
        part1 = math.sin(k * PI_ * xd / xed)
        part2 = (signum * _ie12_1(k, ek, yd, ywd, yed, xwd, xed, theta) + _ie22_1(k, ek, yd, ywd, yed, xwd, xed, theta)
                 + signum * _ie32_1(k, ek, yd, ywd, yed, xwd, xed, theta)
                 + _ie42_1(k, ek, yd, ywd, yed, xwd, xed, theta)) * (1 + smexp)
        part2 = part2 / (k ** 2 * PI_ ** 2 * math.cos(theta) ** 2 + ek ** 2 * xed ** 2 * math.sin(theta) ** 2)
        return part1 * part2 * 1 / 2 / xed / ek
    return _series_c1(term)


def int_k0_gauss_dw(m, u, xd, xwd, yd, ywd) -> float:
    """int_k0_gauss_DW (c1): Гаусс 8 точек на m отрезках."""
    a, b = -1.0, 1.0
    total = 0.0
    for j in range(m):
        for i in range(8):
            xi = (a + (b - a) / m * j + a + (b - a) / m * (j + 1)) / 2 + (b - a) / m / 2 * GAUSS8_X[i]
            total += GAUSS8_C[i] * bessk0(u * math.sqrt((xd - xwd - xi) ** 2 + (yd - ywd) ** 2))
    return (b - a) * total / 2 / m


def _on_line(xd, xwd, yd, ywd, theta) -> bool:
    return ((math.cos(theta) < 10 ** -5 and abs(xd - xwd) < 10 ** -5)
            or abs((yd - ywd) / (xd - xwd + 0.00000001) - math.tan(theta)) < 10 ** -5)


def _images_dw(u, xd, xwd, xed, yd, ywd, th, signum, own) -> float:
    """Сумма интегралов K0 по наклонному сегменту и его отражениям (общая часть pd_b3_DW и F_b3_DW_k)."""
    c, sn = math.cos(th), math.sin(th)
    m = 5
    dy = yd - ywd
    imgs = (signum * int_k0_gauss_dw(m, u, (xd - (-xwd)) * c - dy * sn, 0, (xd - (-xwd)) * sn + dy * c, 0)
            + signum * int_k0_gauss_dw(m, u, (xd - (2 * xed - xwd)) * c - dy * sn, 0,
                                       (xd - (2 * xed - xwd)) * sn + dy * c, 0)
            + int_k0_gauss_dw(m, u, (xd - (xwd - 2 * xed)) * c + dy * sn, 0, -(xd - (xwd - 2 * xed)) * sn + dy * c, 0)
            + int_k0_gauss_dw(m, u, (xd - (xwd + 2 * xed)) * c + dy * sn, 0, -(xd - (xwd + 2 * xed)) * sn + dy * c, 0)
            + signum * int_k0_gauss_dw(m, u, (xd - (-xwd - 2 * xed)) * c - dy * sn, 0,
                                       (xd - (-xwd - 2 * xed)) * sn + dy * c, 0))
    if own:
        return 1 / 4 / PI_ * imgs
    return (1 / 4 / PI_ * int_k0_gauss_dw(m, u, (xd - xwd) * c + dy * sn, 0, -(xd - xwd) * sn + dy * c, 0)
            + 1 / 4 / PI_ * imgs)


def _vert_tail(s_arg, xd, xwd, xed, yd, ywd, signum, start, total) -> float:
    k = start
    while True:
        add = (signum * pdb3_sub(k, s_arg, xd, xwd, xed, yd, ywd, 1, 1, "vert")
               + pdb3_sub(k, s_arg, xd, xwd, xed, yd, ywd, -1, 1, "vert")
               + signum * pdb3_sub(k, s_arg, xd, xwd, xed, yd, ywd, 1, -1, "vert")
               + pdb3_sub(k, s_arg, xd, xwd, xed, yd, ywd, -1, -1, "vert"))
        total += add
        k += 1
        if not abs(add) >= C1.tiny * (abs(total) + C1.tiny):
            return total


def pd_b3_dw(s, xd, xwd, xed, yd, ywd, theta, xbound, ybound) -> float:
    u = math.sqrt(s)
    signum = -1.0 if xbound == "c" else 1.0
    if _on_line(xd, xwd, yd, ywd, theta):
        total = (pdb3_sub(0, s, math.sqrt((xd - xwd) ** 2 + (yd - ywd) ** 2), 0, xed, 0, 0, -1, 1, "frac")
                 + _images_dw(u, xd, xwd, xed, yd, ywd, theta, signum, own=True))
    else:
        total = _images_dw(u, xd, xwd, xed, yd, ywd, theta, signum, own=False)
    return _vert_tail(s, xd, xwd, xed, yd, ywd, signum, 2, total)


def f_b2_dw(s, yd, ywd, yed, xd, xwd, xed, zd, zwd, zed, ld, theta, zb_up, zb_down, xbound, ybound,
            subtract_inf) -> float:
    if xbound != "c" or not subtract_inf:
        raise NotImplementedError("F_b2_DW: используется только при границах «c» и subtract_inf")
    def k1(p, k):
        n = _n_of(p, zb_up, zb_down)
        e = math.sqrt(s + (n * PI_ * ld) ** 2 + k ** 2 * PI_ ** 2 / xed ** 2)
        smexp = sumexp(e, yed)
        part1 = math.sin(k * PI_ * xd / xed) * math.sin(k * PI_ * xwd / xed)
        part2 = (_ie12_1(k, e, yd, ywd, yed, xwd, xed, theta) + _ie22_1(k, e, yd, ywd, yed, xwd, xed, theta)
                 + _ie32_1(k, e, yd, ywd, yed, xwd, xed, theta) + _ie42_1(k, e, yd, ywd, yed, xwd, xed, theta)) * (1 + smexp)
        part2 = 1 / (k ** 2 * PI_ ** 2 * math.cos(theta) ** 2 + e ** 2 * xed ** 2 * math.sin(theta) ** 2) * part2
        return part1 * part2 / xed / e

    def k3(p):
        n = _n_of(p, zb_up, zb_down)
        return _zpart(n, zd, zwd, zed, zb_up, zb_down) * _series_c1(lambda k: k1(p, k))

    return _series_c1(k3)


def f_b3_dw(s, xd, xwd, xed, zd, zwd, zed, yd, ywd, ld, theta, zb_up, zb_down, xbound) -> float:
    signum = -1.0 if xbound == "c" else 1.0
    own = _on_line(xd, xwd, yd, ywd, theta)

    def term(k):
        n = _n_of(k, zb_up, zb_down)
        part1 = _zpart(n, zd, zwd, zed, zb_up, zb_down)
        e_n = math.sqrt(s + (n * PI_ * ld) ** 2)
        total = _images_dw(e_n, xd, xwd, xed, yd, ywd, theta, signum, own)
        # в книге в pdb3_sub передаётся e_n вместо s
        total = _vert_tail(e_n, xd, xwd, xed, yd, ywd, signum, 2, total)
        return 2 * part1 * total

    total = _series_c1(term)
    if own:
        return f_hor(s, math.sqrt((xd - xwd) ** 2 + (yd - ywd) ** 2), 0, zd, zwd, zed, ld, 0, 0, zb_up, zb_down) + total
    return total


def deviated_well_for_cinco(s, xd, yd, zd, xwd, ywd, zwd, xed, yed, zed, psi, xbound, ybound, zb_up, zb_down,
                            compl_type):
    """deviated_well_for_cinco (c8). Возвращает (pwd, угол после вызова): pd_b2_DW в VBA меняет угол по ссылке."""
    if not (zb_up == "n" and zb_down == "n") or not s > 0:
        raise NotImplementedError("deviated_well_for_cinco: только «nn» и s > 0")
    ld = 1 / zed
    pwd = 0.0                                  # pd_b1_DW = 0 при xbound = «c» (до изменения угла)
    if psi < 0:
        psi = psi + 2 * PI_
    pwd = pwd + pd_b2_dw(s, xd, xwd, xed, yd, ywd, yed, psi, xbound, ybound, True)
    pwd = pwd + pd_b3_dw(s, xd, xwd, xed, yd, ywd, psi, xbound, ybound)
    if compl_type == "hor":
        pwd = (pwd + 0.0                       # F_b1_DW = 0 при xbound = «c»
               + f_b2_dw(s, yd, ywd, yed, xd, xwd, xed, zd, zwd, zed, ld, psi, zb_up, zb_down, xbound, ybound, True)
               + f_b3_dw(s, xd, xwd, xed, zd, zwd, zed, yd, ywd, ld, psi, zb_up, zb_down, xbound))
    return pwd, psi


N_SEG_MAIN_MULTILAT = 10
N_SEG_LATERAL_MULTILAT = 2
LATERAL_CONTROL_POINT_OFFSET = 1.0
MAIN_BORE_CONTROL_POINT_OFFSET = 0.0


def multilateral_rect_lapl(s, xd, yd, zd, xwd, ywd, zwd, xed, yed, zed, rwd, l_lateral_d, n_lateral, psi,
                           xbound, ybound, zb_up, zb_down) -> float:
    """multilateral_rect_lapl (c6), метод 1: сегменты стволов, матрица влияния, равное давление."""
    zd = zwd + rwd
    n_hor = N_SEG_MAIN_MULTILAT
    n_lat = N_SEG_LATERAL_MULTILAT
    if 2 * n_lateral > n_hor:
        n_hor = 2 * n_lateral
    n_tot = n_lateral * n_lat + n_hor
    nn = [[0.0] * (n_tot + 2) for _ in range(n_tot + 2)]
    dzd = zd - zwd
    dl_lat = l_lateral_d / n_lat
    dl_hor = 2 / n_hor
    ul = dl_lat / 2
    ul1 = dl_hor / 2
    sd = s * ul ** 2
    sd1 = s * ul1 ** 2
    xedd, yedd, zedd = xed / ul, yed / ul, zed / ul
    dzdd = dzd / ul
    x_start = [(xwd - 1) / ul] + [0.0] * n_lateral
    y_start = [ywd / ul] * (n_lateral + 1)
    z_start = [zwd / ul] * (n_lateral + 1)
    theta_i = [0.0] * (n_lateral + 1)
    dlat = (2 / n_lateral) / ul
    for i in range(1, n_lateral + 1):
        x_start[i] = x_start[0] + MULTILAT_FIRST_BRANCH_COEFF * dlat / 2 + dlat * (i - 1)
        theta_i[i] = psi * (-1) ** (i - 1)
    ax = [0.0] * (n_tot + 1)
    ay = [0.0] * (n_tot + 1)
    az = [0.0] * (n_tot + 1)
    for i in range(1, n_lateral + 1):
        dx = dl_lat * math.cos(theta_i[i]) / ul
        dy = dl_lat * math.sin(theta_i[i]) / ul
        for j in range(1, n_lat + 1):
            idx = j + (i - 1) * n_lat
            ax[idx] = x_start[i] + dx / 2 + (j - 1) * dx
            ay[idx] = y_start[i] + dy / 2 + (j - 1) * dy
            az[idx] = z_start[i]
    dx_hor = dl_hor / ul
    offs = n_lateral * n_lat
    for i in range(1, n_hor + 1):
        ax[offs + i] = x_start[0] + dx_hor / 2 + dx_hor * (i - 1)
        ay[offs + i] = y_start[0]
        az[offs + i] = z_start[0]
    dldd_hor = MAIN_BORE_CONTROL_POINT_OFFSET * calcxd(10000)
    dldd_lat = LATERAL_CONTROL_POINT_OFFSET * calcxd(10000)
    factor = ul / ul1
    for i in range(1, n_tot + 1):
        for j in range(1, n_lateral + 1):
            ang = theta_i[j]
            for k in range(1, n_lat + 1):
                s_ind = (j - 1) * n_lat + k
                if i == s_ind:
                    dxdd, dydd = dldd_lat * math.cos(ang), dldd_lat * math.sin(ang)
                else:
                    dxdd = dydd = 0.0
                compl = "hor" if i == s_ind else "frac"
                nn[i][s_ind], ang = deviated_well_for_cinco(sd, ax[i] + dxdd, ay[i] + dydd, az[i] + dzdd, ax[s_ind],
                                                            ay[s_ind], az[s_ind], xedd, yedd, zedd, ang, xbound, ybound,
                                                            zb_up, zb_down, compl)
        for j in range(1, n_hor + 1):
            s_ind = offs + j
            if i == s_ind:
                dxdd, dydd = dldd_hor, 0.0
                nn[i][s_ind] = horizontal_well_for_cinco(sd1, ax[i] * factor + dxdd, ay[i] * factor + dydd,
                                                         (az[i] + dzdd) * factor, ax[s_ind] * factor,
                                                         ay[s_ind] * factor, az[s_ind] * factor, xedd * factor,
                                                         yedd * factor, zedd * factor, xbound, ybound, zb_up, zb_down)
            else:
                nn[i][s_ind] = pd_lapl_rect(sd1, ax[i] * factor, ax[s_ind] * factor, xedd * factor, ay[i] * factor,
                                            ay[s_ind] * factor, yedd * factor, xbound, ybound, "frac")
    for i in range(1, n_tot + 1):
        nn[i][n_tot + 1] = -1.0
        nn[n_tot + 1][i] = 1.0
    nn[n_tot + 1][n_tot + 1] = 0.0
    rght = [0.0] * (n_tot + 2)
    rght[n_tot + 1] = 1.0
    return lu_solve_nr(nn, rght, n_tot + 1)[n_tot + 1]


# --- Get_J ------------------------------------------------------------------------

def get_completion(l: float, frac_count: int, st_count: int) -> str:
    if st_count > 0:
        return "МЗС"
    if l > 0:
        return "ГС+ГРП" if frac_count > 0 else ("ГС" if frac_count == 0 else "н/д")
    if l == 0:
        return "ННС+ГРП" if frac_count > 0 else ("ННС" if frac_count == 0 else "н/д")
    return "н/д"


def fracture_effective_radius_mult_barri(fcd: float) -> float:
    fcd_opt = 1.7
    return 1 / 2 * 1 / (1 + (fcd_opt / fcd) ** 1.01) if fcd > 0 else 0.0


def fracture_skin_barri(xf, k, wf, kf, rw) -> float:
    if rw > 0 and k * xf > 0 and kf * wf > 0:
        fcd = kf * wf / (k * xf)
    else:
        return 0.0
    return -math.log(xf * fracture_effective_radius_mult_barri(fcd) / rw)


def well_extents_xy(model, rw, xf, l_hor, n_frac, l_lateral, psi_lateral, n_lateral, frac_dir):
    if model == "ННС":
        return 2 * rw, 2 * rw
    if model == "ННС+ГРП":
        return 2 * xf, 2 * rw
    if model == "ГС":
        return l_hor, 2 * rw
    if model == "ГС+ГРП":
        if frac_dir == "Вдоль":
            if n_frac > 1:
                x = l_hor + 2 * xf
            elif l_hor > 2 * xf:
                x = l_hor
            else:
                x = 2 * xf
            return x, 2 * rw
        return l_hor, 2 * xf
    if model == "МЗС":
        psi = psi_lateral * PI_ / 180
        x = 2 * (l_hor / 2 - (1 - MULTILAT_FIRST_BRANCH_COEFF) * l_hor / n_lateral + l_lateral * math.cos(psi))
        if l_hor > x:
            x = l_hor
        return x, 2 * l_lateral * math.sin(psi)
    return -1.0, -1.0


def well_length_for_aspect_ratio(model, xf, l_hor, n_frac, frac_dir) -> float:
    if model == "ННС":
        return 1.0
    if model == "ННС+ГРП":
        return 2 * xf
    if model in ("ГС", "МЗС"):
        return l_hor
    if model == "ГС+ГРП":
        if frac_dir == "Вдоль":
            if n_frac > 1:
                return l_hor + 2 * xf
            return l_hor if l_hor > 2 * xf else 2 * xf
        return l_hor
    return 0.0


@dataclass
class _Well:
    compl_type: str
    xwd: list
    ywd: list
    zwd: list
    rwd: float
    fcd: float
    skin: float
    sfrac: float
    n_frac: int
    l_lateral_d: float
    n_lateral: int
    psi_lateral: float
    r_eff_low_fcd_xf: float


def get_j(kv_kh: float, phi: float, l_hor: float, l_hor_eff: float, t_p: float, r_e: float, r_w: float, h: float,
          k_h: float, s: float, mu: float, c_t: float, b: float, frac_count: int = 0, w_f: float = 0.0,
          k_f: float = 0.0, xf: float = 0.0, l_lateral: float = 0.0, l_lateral_eff: float = 0.0,
          n_lateral: int = 0, frac_dir: str = "") -> float:
    """Get_J: коэффициент продуктивности, м³/сут/атм (−1 — недопустимая геометрия, как в книге).

    Аргументы — как на листах книги: kv/kh, Кп, L ГС общая и эффективная, м,
    время t_p, сут, Rконт, Rскв, h, м, k, мД, скин, μ, сП, Ct, 1/атм, B,
    число трещин, раскрытие, мм, проницаемость проппанта, Д, полудлина, м,
    длина бокового ствола (общая, эффективная), м, число боковых стволов,
    ориентация трещин «Вдоль»/«Поперёк».
    """
    l_hor = l_hor or 0.0
    l_hor_eff = l_hor_eff or 0.0
    frac_count = int(frac_count or 0)
    n_lateral = int(n_lateral or 0)
    s = s or 0.0
    model = get_completion(l_hor, frac_count, n_lateral)
    r_wb_eff = r_w
    if s < 0:
        if model in ("ННС+ГРП", "ГС+ГРП"):
            s = 0.0
        else:
            r_wb_eff = r_w * math.exp(-s)
    if model in ("ННС+ГРП", "ГС+ГРП") and (xf <= 0 or k_f <= 0 or w_f <= 0):
        return -1.0
    if model in ("ГС", "МЗС") and 2 * r_wb_eff >= h:
        return -1.0
    if model in ("ГС", "МЗС") and (l_hor_eff <= 0 or l_hor_eff > l_hor):
        return -1.0
    if model in ("ГС", "МЗС") and kv_kh <= 0:
        return -1.0
    if model == "МЗС" and (l_lateral_eff <= 0 or l_lateral_eff > l_lateral):
        return -1.0
    if model == "ГС+ГРП" and frac_dir == "Вдоль" and l_hor < 2 * xf * (frac_count - 1):
        return -1.0
    ext = well_extents_xy(model, r_wb_eff, xf, l_hor, frac_count, l_lateral, PSI_LATERAL, n_lateral, frac_dir)
    length = well_length_for_aspect_ratio(model, xf, l_hor, frac_count, frac_dir)
    s_dr = PI_ * r_e ** 2
    aspect = 1 + length ** 2 / s_dr                 # Calc_optimal_aspect_ratio_Butler
    x_e = math.sqrt(s_dr * aspect)
    y_e = math.sqrt(s_dr / aspect)
    if x_e < ext[0] or y_e < ext[1]:
        return -1.0
    if model in ("ГС", "МЗС"):
        l_hor = l_hor_eff
        l_lateral = l_lateral_eff
    return _get_j_private(kv_kh, phi, l_hor, t_p, r_e, r_w, h, k_h, s, mu, c_t, b, frac_count, w_f, k_f, xf,
                          l_lateral, n_lateral, PSI_LATERAL, frac_dir, model, aspect)


def _get_j_private(kv_kh, phi, l_hor, t_p, r_e, r_w, h, k_h, s, mu, c_t, b, n_frac, w_f, k_f, xf, l_lateral,
                   n_lateral, psi_lateral, frac_dir, model, aspect) -> float:
    t = t_p * 24
    rw, k, skin, sfrac = r_w, k_h, s, s
    w = r_e * math.sqrt(aspect * PI_)
    l = r_e * math.sqrt(PI_ / aspect)
    wf = lf = 0.5
    fcd = 0.0
    r_eff_low = 0.0
    if model in ("ННС+ГРП", "ГС+ГРП"):
        fcd = k_f * w_f / (k_h * xf)
        r_eff_low = fracture_effective_radius_mult_barri(fcd)
        if CALC_OPTION == 1 and 0 < fcd < LOW_FCD:
            # Correct_for_low_FcD = 2: та же эффективная радиус-длина при FcD = low_FcD
            xf = xf * fracture_effective_radius_mult_barri(fcd) / fracture_effective_radius_mult_barri(LOW_FCD)
            fcd = LOW_FCD
    compl_type = {"ННС": "vert", "ННС+ГРП": "frac", "ГС": "horizontal", "ГС+ГРП": "multifrac",
                  "МЗС": "multilateral"}[model]
    # DefineGeometry (BoundaryType 2 — «cccc», zBoundaryType 1 — «nn»)
    xbound = ybound = "c"
    zb_up = zb_down = "n"
    frac_dir_e = "longitudal" if frac_dir == "Вдоль" else "transverse"
    xw, yw = [w * wf], [l * lf]
    xe, ye, ze = w, l, h
    zw = [ze * 0.5]
    z = zw[0]
    if compl_type == "vert":
        if skin < 0:
            rw = rw * math.exp(-skin)
            skin = 0.0
        r = rw
        unit = rw
    elif compl_type in ("frac", "multifrac"):
        unit, r = xf, 0.0
    else:
        if skin < 0:
            rw = rw * math.exp(-skin)
            skin = 0.0
        unit, r = l_hor / 2, 0.0
    if compl_type == "multifrac":
        xw, yw, xe, ye, xbound, ybound = _multifrac_geometry(l_hor, n_frac, xe, ye, xw, yw, xbound, ybound,
                                                             frac_dir_e)
        zw = [zw[0]] * len(xw)
    x = r + xw[0]
    y = yw[0]
    # DimensionlessVariables (mode 1 — дебит при постоянном Рзаб)
    multq = k * h / (18.42 * b * mu)
    mult_t = c_t * phi * mu * unit ** 2 / 0.00036 / k
    td = t / mult_t
    # DimensionlessGeometry
    s_kv = math.sqrt(kv_kh) if kv_kh > 0 else 1.0
    xd, yd, zd = x / unit, y / unit, z / unit / s_kv
    xwd = [v / unit for v in xw]
    ywd = [v / unit for v in yw]
    zwd = [v / unit / s_kv for v in zw]
    xed, yed, zed = xe / unit, ye / unit, ze / unit / s_kv
    well = _Well(compl_type, xwd, ywd, zwd, rw * (1 + 1 / s_kv) / 2 / unit, fcd, skin, sfrac, n_frac,
                 l_lateral / unit, n_lateral, psi_lateral * PI_ / 180, r_eff_low)
    return multq * _pd_qd_qtd_u(td, xd, yd, zd, well, xed, yed, zed, xbound, ybound, zb_up, zb_down)


def _multifrac_geometry(l_hor, n_frac, xe, ye, xw, yw, xbound, ybound, direction):
    """Define_multifrac_geometry (c11): трещины равномерно по стволу; «поперёк» — оси x и y меняются."""
    xw = list(xw) + [0.0] * n_frac
    yw = list(yw) + [0.0] * n_frac
    if n_frac == 1:
        xw[1], yw[1] = xw[0], yw[0]
    elif n_frac > 1:
        x_min = xw[0] - l_hor / 2
        delta = l_hor / (n_frac - 1)
        for i in range(1, n_frac + 1):
            xw[i] = x_min + delta * (i - 1)
            yw[i] = yw[0]
    if direction == "transverse":
        xe, ye = ye, xe
        xw, yw = yw, xw
        xbound, ybound = ybound, xbound
    return xw, yw, xe, ye, xbound, ybound


def lu_solve_nr(a: list, b: list, n: int) -> list:
    """LU_ (c9): разложение Краута с выбором ведущего элемента и обратный ход (Numerical Recipes).

    a — (n+1)×(n+1), b — n+1, индексы с 1 (нулевые не используются). Возвращает решение в b.
    """
    tiny = 1e-20
    vv = [0.0] * (n + 1)
    indx = [0] * (n + 1)
    for i in range(1, n + 1):
        big = 0.0
        for j in range(1, n + 1):
            t = abs(a[i][j])
            if t > big:
                big = t
        if big == 0.0:
            return b
        vv[i] = 1.0 / big
    imax = 0
    for j in range(1, n + 1):
        for i in range(1, j):
            total = a[i][j]
            for k in range(1, i):
                total = total - a[i][k] * a[k][j]
            a[i][j] = total
        big = 0.0
        for i in range(j, n + 1):
            total = a[i][j]
            for k in range(1, j):
                total = total - a[i][k] * a[k][j]
            a[i][j] = total
            dum = vv[i] * abs(total)
            if dum >= big:
                big = dum
                imax = i
        if j != imax:
            for k in range(1, n + 1):
                a[imax][k], a[j][k] = a[j][k], a[imax][k]
            vv[imax] = vv[j]
        indx[j] = imax
        if a[j][j] == 0.0:
            a[j][j] = tiny
        if j != n:
            dum = 1.0 / a[j][j]
            for i in range(j + 1, n + 1):
                a[i][j] = a[i][j] * dum
    ii = 0
    for i in range(1, n + 1):
        ip = indx[i]
        total = b[ip]
        b[ip] = b[i]
        if ii:
            for j in range(ii, i):
                total = total - a[i][j] * b[j]
        elif total:
            ii = i
        b[i] = total
    for i in range(n, 0, -1):
        total = b[i]
        for j in range(i + 1, n + 1):
            total = total - a[i][j] * b[j]
        b[i] = total / a[i][i]
    return b


def multifrac_response_lapl(s, n_frac, well_x, well_y, xed, yed, cfd, xbound, ybound, s_frac_face, s_choke,
                            r_eff_xf) -> float:
    """multifrac_response_lapl (c3), метод 1: матрица влияния трещин + условие равного давления."""
    n = n_frac
    m = [[0.0] * (n + 2) for _ in range(n + 2)]
    for j in range(1, n + 1):
        for i in range(1, n + 1):
            if i >= j:
                m[i][j] = pd_frac_rect_lapl(s, well_x[i], well_y[i], well_x[j], well_y[j], xed, yed, xbound,
                                            ybound, cfd, r_eff_xf, DEF_ETA_D, s_frac_face, s_choke)
            else:
                m[i][j] = m[j][i]
            if i == j:
                m[i][j] = m[i][j] + s_choke / 6.28318530717959
    bb = [0.0] * (n + 2)
    for i in range(1, n + 1):
        m[i][n + 1] = -1.0
        m[n + 1][i] = 1.0
    m[n + 1][n + 1] = 0.0
    bb[n + 1] = 1.0
    return lu_solve_nr(m, bb, n + 1)[n + 1]


def _pd_qd_qtd_u(td, xd, yd, zd, well, xed, yed, zed, xbound, ybound, zb_up, zb_down) -> float:
    v = stehfest_coef(N_STEHFEST)
    dlog = math.log(2.0)
    total = 0.0
    for j in range(1, N_STEHFEST + 1):
        s = j * dlog / td
        q_d = (2 * PI_) / s
        p_d = _pd_lapl_u(s, xd, yd, zd, well, xed, yed, zed, xbound, ybound, zb_up, zb_down)
        total += (v[j] / j) / (p_d * q_d * s)
    return total


def _pd_lapl_u(s, xd, yd, zd, well, xed, yed, zed, xbound, ybound, zb_up, zb_down) -> float:
    if well.compl_type == "vert":
        return pd_vert_rect_lapl(s, xd, yd, well.xwd[0], well.ywd[0], xed, yed, xbound, ybound, well.skin)
    if well.compl_type == "frac":
        return pd_frac_rect_lapl(s, xd, yd, well.xwd[0], well.ywd[0], xed, yed, xbound, ybound, well.fcd,
                                 well.r_eff_low_fcd_xf, DEF_ETA_D, well.sfrac, 0.0)
    if well.compl_type == "multifrac":
        return multifrac_response_lapl(s, well.n_frac, well.xwd, well.ywd, xed, yed, well.fcd, xbound, ybound,
                                       well.sfrac, 0.0, well.r_eff_low_fcd_xf)
    if well.compl_type == "multilateral":
        return multilateral_rect_lapl(s, xd, yd, zd, well.xwd[0], well.ywd[0], well.zwd[0], xed, yed, zed, well.rwd,
                                      well.l_lateral_d, well.n_lateral, well.psi_lateral, xbound, ybound, zb_up, zb_down)
    if well.compl_type == "horizontal":
        return horizontal_rect_lapl(s, xd, yd, zd, well.xwd[0], well.ywd[0], well.zwd[0], xed, yed, zed, well.rwd,
                                    xbound, ybound, zb_up, zb_down, well.skin)
    raise NotImplementedError(well.compl_type)
