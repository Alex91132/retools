# -*- coding: utf-8 -*-
"""Корреляционный класс PVT (порт CPVT из RE Tools / Unifloc).

Метод: корреляцииpublished (Standing, Valko-McCain, Velarde, Beggs-Robinson,
Vasquez-Beggs, Lee, Kareem z-factor) с калибровкой на пользовательские точки
Pb / Rsb / Bob / Muob через множители p_fact / b_fact / mu_fact — давление
«растягивается» на калиброванное Рнас, объёмный коэффициент и вязкость
масштабируются относительно корреляционного значения при насыщении.

Единицы: давление атм (вход/выход), внутри — МПа; температура °C → К.
Поддержаны оба набора корреляций книги: corr=0 (Standing-based) и
corr=1 (McCain-based; контрольный пример листа PVT_MBE_Waterflood).
"""
from __future__ import annotations

from math import exp, log

# Константы u7_const.bas
ATMA_MPA = 101325 / 1e6            # const_convert_atma_MPa
MPA_PSIA = (1e6 / 101325) * 14.7   # const_convert_MPa_psia
RHO_AIR = 1.2217                   # const_rho_air
RHO_REF = 1000                     # const_rho_ref
M3M3_SCFBBL = 5.614583544          # const_convert_m3m3_scfbbl
T_K_MIN = 273                      # const_t_K_min


def _k_to_f(t_k: float) -> float:
    return t_k * 9 / 5 - 459.67


def _gamma_to_api(go: float) -> float:
    return 141.5 / go - 131.5


# ================= корреляции (u7_PVT.bas, verbatim) =================

def mu_dead_oil_standing(t_k: float, go: float) -> float:
    api = 141.5 / go - 131.5
    return (0.32 + 1.8e7 / api ** 4.53) * (360 / (1.8 * t_k - 260)) ** (
        10 ** (0.43 + 8.33 / api))


def mu_dead_oil_beggs_robinson(t_k: float, go: float) -> float:
    x = _k_to_f(t_k) ** (-1.163) * exp(13.108 - 6.591 / go)
    return 10 ** x - 1


def mu_oil_saturated_beggs_robinson(gor_pb: float, mu_dead: float) -> float:
    a = 10.715 * (5.615 * gor_pb + 100) ** (-0.515)
    b = 5.44 * (5.615 * gor_pb + 150) ** (-0.338)
    return a * mu_dead ** b


def mu_oil_vasquez_beggs(mu_sat: float, p_mpa: float, pb_mpa: float) -> float:
    m = 957 * p_mpa ** 1.187 * exp(-11.513 - 0.01302 * p_mpa)
    return mu_sat * (p_mpa / pb_mpa) ** m


def mu_oil_standing(rs: float, mu_dead: float, p_mpa: float, pb_mpa: float) -> float:
    a = 5.6148 * rs * (0.1235e-5 * rs - 0.00074)
    b = 0.68 / 10 ** (0.000484 * rs) + 0.25 / 10 ** (0.006176 * rs) + 0.062 / 10 ** (0.021 * rs)
    mu = 10 ** a * mu_dead ** b
    if pb_mpa < p_mpa:
        mu = mu + 0.14504 * (p_mpa - pb_mpa) * (
            0.024 * mu ** 1.6 + 0.038 * mu ** 0.56)
    return mu


def pb_standing_mpa(rsb: float, gg: float, t_k: float, go: float) -> float:
    min_rsb = 1.8
    rsb_old = rsb
    rsb = max(rsb, min_rsb)
    yg = 1.225 + 0.001648 * t_k - 1.769 / go
    pb = 0.5197 * (rsb / gg) ** 0.83 * 10 ** yg
    if rsb_old < min_rsb:
        pb = (pb - 0.1013) * rsb_old / min_rsb + 0.1013
    return pb


def rs_standing_m3m3(p_mpa: float, gg: float, t_k: float, go: float):
    """Возвращает (rs, drs/dp) — как ByRef в оригинале."""
    yg = 1.225 + 0.001648 * t_k - 1.769 / go
    rs = gg * (1.92 * p_mpa / 10 ** yg) ** 1.204
    drs_dp = gg * (1.92 / 10 ** yg) ** 1.204 * 1.204 * p_mpa ** 0.204
    return rs, drs_dp


def bo_saturated_standing_m3m3(rs: float, gg: float, t_k: float, go: float) -> float:
    f = 5.615 * rs * (gg / go) ** 0.5 + 2.25 * t_k - 575
    return 0.972 + 0.000147 * f ** 1.175


def dbo_drs_standing(rs: float, gg: float, t_k: float, go: float) -> float:
    alpha = 5.615 * (gg / go) ** 0.5
    f = alpha * rs + 2.25 * t_k - 575
    return 0.000147 * 1.175 * f ** (1.175 - 1) * alpha


def co_oil_vb_1mpa(rs: float, gg: float, t_k: float, go: float, p_mpa: float) -> float:
    return (28.1 * rs + 30.6 * t_k - 1180 * gg + 1784 / go - 10910) / (100000 * p_mpa)


def pb_valko_mccain_mpa(rsb: float, gg: float, t_k: float, go: float) -> float:
    min_rsb, max_rsb = 1.8, 800
    rsb_old = rsb
    rsb = min(max(rsb, min_rsb), max_rsb)
    api = _gamma_to_api(go)
    lrs = log(rsb)
    z1 = -4.814074834 + 0.7480913 * lrs + 0.1743556 * lrs ** 2 - 0.0206 * lrs ** 3
    z2 = 1.27 - 0.0449 * api + 4.36e-4 * api ** 2 - 4.76e-6 * api ** 3
    z3 = 4.51 - 10.84 * gg + 8.39 * gg ** 2 - 2.34 * gg ** 3
    z4 = (-7.2254661 + 0.043155 * t_k - 8.5548e-5 * t_k ** 2
          + 6.00696e-8 * t_k ** 3)
    z = z1 + z2 + z3 + z4
    lnpb = 2.498006 + 0.713 * z + 0.0075 * z ** 2
    pb = 2.718282 ** lnpb
    if rsb_old < min_rsb:
        pb = (pb - 0.1013) * rsb_old / min_rsb + 0.1013
    if rsb_old > max_rsb:
        pb = (pb - 0.1013) * rsb_old / max_rsb + 0.1013
    return pb


def rs_velarde_m3m3(p_mpa: float, pb_mpa: float, gg: float, t_k: float,
                    go: float, rsb: float):
    """Rs по Velarde-McCain (1999); возвращает (rs, drs/dp)."""
    api = _gamma_to_api(go)
    if pb_mpa > pb_valko_mccain_mpa(800, gg, t_k, go):
        if p_mpa < pb_mpa:
            return rsb * (p_mpa / pb_mpa), 0.0
        return rsb, 0.0
    pr = (p_mpa - 0.101) / (pb_mpa - 0.101) if pb_mpa > 0 else 0.0
    if pr <= 0:
        return 0.0, 0.0
    a_ = (1.8653e-4, 1.672608, 0.92987, 0.247235, 1.056052)
    b_ = (0.1004, -1.00475, 0.337711, 0.132795, 0.302065)
    c_ = (0.9167, -1.48548, -0.164741, -0.09133, 0.047094)
    if pr >= 1:
        return rsb, 0.0
    t_f = 1.8 * t_k - 460
    a1 = a_[0] * gg ** a_[1] * api ** a_[2] * t_f ** a_[3] * pb_mpa ** a_[4]
    a2 = b_[0] * gg ** b_[1] * api ** b_[2] * t_f ** b_[3] * pb_mpa ** b_[4]
    a3 = c_[0] * gg ** c_[1] * api ** c_[2] * t_f ** c_[3] * pb_mpa ** c_[4]
    rsr = a1 * pr ** a2 + (1 - a1) * pr ** a3
    drs_dp = (a1 * a2 * pr ** (a2 - 1) + (1 - a1) * a3 * pr ** (a3 - 1))
    drs_dp = drs_dp * rsb / (pb_mpa - 0.101)
    return rsr * rsb, drs_dp


def rho_oil_mccain_kgm3(p_mpa: float, gg: float, t_k: float, go: float,
                         rs: float, pb_mpa: float, co_1mpa: float) -> float:
    """Плотность нефти McCain: итерационная схема + поправки на P и T."""
    if rs > 800:
        rs = 800
        pb_mpa = pb_valko_mccain_mpa(rs, gg, t_k, go)
    ropo = 845.8 - 0.9 * rs
    pm, pmmo = ropo, 0.0
    eps, counter = 1e-6, 0
    a0, a1, a2, a3, a4, a5 = -799.21, 1361.8, -3.70373, 0.003, 2.98914, -0.00223
    while abs(pmmo - pm) > eps and counter < 100:
        pmmo = pm
        roa = (a0 + a1 * gg + a2 * gg * ropo + a3 * gg * ropo ** 2
               + a4 * ropo + a5 * ropo ** 2)
        ropo = (rs * gg + 818.81 * go) / (0.81881 + rs * gg / roa)
        pm = ropo
        counter += 1
    t_f_60 = 1.8 * t_k - 520
    if p_mpa <= pb_mpa:
        p_ref = p_mpa
    else:
        p_ref = pb_mpa
    dpp = ((0.167 + 16.181 * 10 ** (-0.00265 * pm)) * 2.32328 * p_ref
           - 0.16 * (0.299 + 263 * 10 ** (-0.00376 * pm)) * (0.14503774 * p_ref) ** 2)
    pbs = pm + dpp
    dpt = ((0.04837 + 337.094 * pbs ** (-0.951)) * t_f_60 ** 0.938
           - (0.346 - 0.3732 * 10 ** (-0.001 * pbs)) * t_f_60 ** 0.475)
    rho = pbs - dpt
    if p_mpa > pb_mpa:
        rho = rho * exp(co_1mpa * (p_mpa - pb_mpa))
    return rho


def bo_mccain_m3m3(rs: float, gg: float, sto_density: float, res_density: float) -> float:
    return (sto_density + 1.22117 * rs * gg) / res_density


def co_oil_saturated_mccain_1mpa(rsb: float, go: float, t_k: float,
                                 p_mpa: float, pb_mpa: float) -> float:
    rsb_scf = rsb * M3M3_SCFBBL
    t_f = _k_to_f(t_k)
    api = _gamma_to_api(go)
    p_psia = p_mpa * MPA_PSIA
    pb_psia = pb_mpa * MPA_PSIA
    co_1psi = exp(-7.573 - 1.45 * log(p_psia) - 0.383 * log(pb_psia)
                  + 1.402 * log(t_f) + 0.256 * log(api) + 0.449 * log(rsb_scf))
    return co_1psi * MPA_PSIA


def z_factor_kareem(tpr: float, ppr: float) -> float:
    """Явная корреляция z-фактора Kareem et al. (2016)."""
    a = (0.317842, 0.382216, -7.768354, 14.290531, 2e-6, -0.004693,
         0.096254, 0.16672, 0.96691, 0.063069, -1.966847, 21.0581,
         -27.0246, 16.23, 207.783, -488.161, 176.29, 1.88453, 3.05921)
    t = 1 / tpr
    t2, t3 = t ** 2, t ** 3
    aa = (a[0] * t * exp(a[1] * (1 - t) ** 2) * ppr) ** 2
    bb = a[2] * t + a[3] * t2 + a[4] * t ** 6 * ppr ** 6
    cc = a[8] + a[7] * t * ppr + a[6] * t2 * ppr ** 2 + a[5] * t3 * ppr ** 3
    dd = a[9] * t * exp(a[10] * (1 - t) ** 2)
    ee = a[11] * t + a[12] * t2 + a[13] * t3
    ff = a[14] * t + a[15] * t2 + a[16] * t3
    gg = a[17] + a[18] * t
    dppr = dd * ppr
    y = dppr / ((1 + aa) / cc - aa * bb / cc ** 3)
    y2 = y ** 2
    return dppr * (1 + y + y2 - y ** 3) / (dppr + ee * y2 - ff * y ** gg) / (1 - y) ** 3


def z_gas(t_k: float, p_mpa: float, gg: float) -> float:
    t_pc = 93.3 + 180 * gg - 6.94 * gg ** 2
    p_pc = 4.6 + 0.1 * gg - 0.258 * gg ** 2
    return z_factor_kareem(t_k / t_pc, p_mpa / p_pc)


def mu_gas_lee_cP(t_k: float, p_mpa: float, z: float, gg: float) -> float:
    r = 1.8 * t_k
    mwg = 28.966 * gg
    gd = p_mpa * mwg / (z * t_k * 8.31)
    a = (9.379 + 0.01607 * mwg) * r ** 1.5 / (209.2 + 19.26 * mwg + r)
    b = 3.448 + 986.4 / r + 0.01009 * mwg
    c = 2.447 - 0.2224 * b
    return 1e-4 * a * exp(b * gd ** c)


def bg_m3m3(t_k: float, p_mpa: float, z: float) -> float:
    return 0.00034722 * t_k * z / p_mpa


# ================= класс (CPVT.calc_PVT) =================

class CPVT:
    """Порт CPVT: init(...) + calc_PVT(p_atma, t_C) -> свойства.

    corr: 0 — Standing-based, 1 — McCain-based (контрольный пример книги).
    """

    def __init__(self, gamma_gas=0.6, gamma_oil=0.86, gamma_wat=1.0,
                 rsb_m3m3=100.0, pb_atma=-1.0, bob_m3m3=-1.0,
                 corr=0, t_res_C=90.0, muob_cP=-1.0):
        self.gg = gamma_gas
        self.go = gamma_oil
        self.gw = gamma_wat
        self.rsb = rsb_m3m3
        self.pb_atma = pb_atma
        self.bob = bob_m3m3
        self.muob = muob_cP
        self.corr = corr
        self.t_res_C = t_res_C
        if rsb_m3m3 <= 0 and pb_atma > 1:
            rs, _ = rs_standing_m3m3(pb_atma * ATMA_MPA, gamma_gas,
                                      t_res_C + T_K_MIN, gamma_oil)
            self.rsb = rs

    def calc(self, p_atma: float, t_C: float) -> dict:
        t_k = t_C + T_K_MIN
        p_mpa = p_atma * ATMA_MPA
        pb_calbr_mpa = self.pb_atma * ATMA_MPA
        t_res_k = self.t_res_C + T_K_MIN

        z_ = z_gas(t_k, p_mpa, self.gg)
        bg = bg_m3m3(t_k, p_mpa, z_)
        mu_g = mu_gas_lee_cP(t_k, p_mpa, z_, self.gg)

        if self.corr == 0:  # Standing-based
            p_fact = (pb_standing_mpa(self.rsb, self.gg, t_res_k, self.go) / pb_calbr_mpa
                      if pb_calbr_mpa > 0 else 1.0)
            if self.bob > 0:
                bob_sat = bo_saturated_standing_m3m3(self.rsb, self.gg, t_res_k, self.go)
                b_fact = (self.bob - 1) / (bob_sat - 1)
            else:
                b_fact = 1.0
            if self.muob > 0:
                mu_dead_res = mu_dead_oil_beggs_robinson(t_res_k, self.go)
                mu_sat_res = mu_oil_saturated_beggs_robinson(self.rsb, mu_dead_res)
                mu_fact = self.muob / mu_sat_res
            else:
                mu_fact = 1.0
            mu_dead = mu_dead_oil_beggs_robinson(t_k, self.go)
            p_bi = pb_standing_mpa(self.rsb, self.gg, t_k, self.go)
            p = p_mpa * p_fact
            if p > p_bi:
                rs = self.rsb
                bob_sat = b_fact * (bo_saturated_standing_m3m3(self.rsb, self.gg, t_k, self.go) - 1) + 1
                co = co_oil_vb_1mpa(self.rsb, self.gg, t_k, self.go, p)
                bo = bob_sat * exp(co * (p_bi - p))
                mu_sat = mu_oil_saturated_beggs_robinson(self.rsb, mu_dead)
                mu_o = mu_fact * mu_oil_vasquez_beggs(mu_sat, p, p_bi)
            else:
                rs, drs_dp = rs_standing_m3m3(p, self.gg, t_k, self.go)
                bo = b_fact * (bo_saturated_standing_m3m3(rs, self.gg, t_k, self.go) - 1) + 1
                dbo_drs = b_fact * dbo_drs_standing(rs, self.gg, t_k, self.go)
                co = -1 / bo * (dbo_drs * drs_dp - bg * drs_dp)
                mu_o = mu_fact * mu_oil_saturated_beggs_robinson(rs, mu_dead)
            pb_calc_atma = p_bi / p_fact / ATMA_MPA
        elif self.corr == 1:  # McCain-based
            p_bi_res = pb_valko_mccain_mpa(self.rsb, self.gg, t_res_k, self.go)
            p_fact = p_bi_res / pb_calbr_mpa if pb_calbr_mpa > 0 else 1.0
            if self.bob > 0:
                co = co_oil_vb_1mpa(self.rsb, self.gg, t_res_k, self.go, p_bi_res)
                rho_sat = rho_oil_mccain_kgm3(p_bi_res, self.gg, t_res_k, self.go,
                                              self.rsb, p_bi_res, co)
                bob_sat = bo_mccain_m3m3(self.rsb, self.gg, self.go * RHO_REF, rho_sat)
                b_fact = (self.bob - 1) / (bob_sat - 1)
            else:
                b_fact = 1.0
            if self.muob > 0:
                mu_dead_res = mu_dead_oil_standing(t_res_k, self.go)
                if self.rsb < 350:
                    mu_fact = self.muob / mu_oil_standing(self.rsb, mu_dead_res,
                                                          p_bi_res, p_bi_res)
                else:
                    mu_sat = mu_oil_saturated_beggs_robinson(self.rsb, mu_dead_res)
                    mu_fact = self.muob / mu_sat
            else:
                mu_fact = 1.0
            p = p_mpa * p_fact
            p_bi = pb_valko_mccain_mpa(self.rsb, self.gg, t_k, self.go)
            rs, _ = rs_velarde_m3m3(p, p_bi, self.gg, t_k, self.go, self.rsb)
            if p > p_bi:
                co = co_oil_vb_1mpa(self.rsb, self.gg, t_k, self.go, p)
                rho_sat = rho_oil_mccain_kgm3(p_bi, self.gg, t_k, self.go,
                                              self.rsb, p_bi, co)
                bob_sat = bo_mccain_m3m3(self.rsb, self.gg, self.go * RHO_REF, rho_sat)
                bob_sat = b_fact * (bob_sat - 1) + 1
                bo = bob_sat * exp(co * (p_bi - p))
            else:
                co = co_oil_saturated_mccain_1mpa(self.rsb, self.go, t_k, p, p_bi)
                rho_o = rho_oil_mccain_kgm3(p, self.gg, t_k, self.go, rs, p_bi, co)
                bo = b_fact * (bo_mccain_m3m3(rs, self.gg, self.go * RHO_REF, rho_o) - 1) + 1
            mu_dead = mu_dead_oil_standing(t_k, self.go)
            if self.rsb < 350:
                mu_o = mu_fact * mu_oil_standing(rs, mu_dead, p, p_bi)
            elif p > p_bi:
                mu_sat = mu_oil_saturated_beggs_robinson(self.rsb, mu_dead)
                mu_o = mu_fact * mu_oil_vasquez_beggs(mu_sat, p, p_bi)
            else:
                mu_o = mu_fact * mu_oil_saturated_beggs_robinson(rs, mu_dead)
            pb_calc_atma = p_bi / p_fact / ATMA_MPA
        else:
            raise ValueError("поддержаны corr=0 (Standing) и corr=1 (McCain)")

        return {"rs": rs, "bo": bo, "bg": bg, "z": z_,
                "mu_oil": mu_o, "mu_gas": mu_g, "co_1MPa": co,
                "pb_calc_atma": pb_calc_atma, "p_scaled_MPa": p_mpa * p_fact,
                "mu_dead": mu_dead}
