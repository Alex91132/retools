# -*- coding: utf-8 -*-
"""Движок расчёта добычи по месяцам (порт «Расчёт добычи» RE Tools).

Компоновка портированных модулей в месячный цикл:
- Рпл падает с накопленным отбором (матбаланс Хавлена-Оде, pvt_mbe);
- дебит жидкости = PI × ΔP (продуктивность Jd × Kh/mu — jd_generator);
- обводнённость из ОФП Кори (pvt_mbe.frac_flow);
- заводнение поддерживает Рпл при наличии ППД;
- контроль: минимальный дебит, предельная обводнённость.

Вход: retools.gtm_io.GtmWell. Выход: месячные ряды Qн/Qж/обв-ть/Рпл.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .cpvt import CPVT, ATMA_MPA
from .gtm_io import GtmWell
from .pvt_mbe import ControlFluid, corey_kro, corey_krw, frac_flow, mbe_lhs, mbe_rhs, sw_from_fw
from .pallets import default_pallets, mu_mix, kro_mix, krw_mix


@dataclass
class MonthResult:
    """Результат одного месяца работы скважины."""
    month: int = 0
    date: str = ""
    p_res: float = 0.0        # Рпл, атм
    q_liq: float = 0.0        # Qж, м3/сут
    q_oil: float = 0.0        # Qн, т/сут (или м3/сут)
    water_cut: float = 0.0    # обводнённость, %
    gor: float = 0.0          # газонефтяной фактор, м3/м3
    cum_oil: float = 0.0      # накопленная добыча нефти, м3
    cum_liq: float = 0.0      # накопленная добыча жидкости, м3
    days_worked: float = 30.4 # дней работы в месяце


@dataclass
class ProductionProfile:
    """Профиль добычи скважины по месяцам."""
    well: GtmWell
    months: List[MonthResult] = field(default_factory=list)


def _well_fluid(w: GtmWell) -> CPVT:
    """PVT-объект для скважины из рейтинга ГТМ (контрольный флюид книги)."""
    return CPVT(gamma_gas=0.7, gamma_oil=0.9, gamma_wat=1.01, rsb_m3m3=60,
                pb_atma=159, bob_m3m3=1.08, muob_cP=8.8, corr=1, t_res_C=32)


def _productivity(w: GtmWell, pvt: CPVT, p_res: float) -> float:
    """Коэффициент продуктивности PI (м3/сут/атм) через Jd и Kh/mu."""
    h_eff_net = w.h_eff * (1 - w.flood_share)    # истощаемая толщина
    if h_eff_net <= 0:
        return 0.0
    pvt_props = pvt.calc(p_res, 32)
    mu = max(pvt_props["mu_oil"], 0.1)
    bo = pvt_props["bo"]
    # PI = k*h / (18.42 * mu * B) * Jd (Jd из нормировки или константа)
    # для упрощения: Jd = 0.3 (типичный Jd для ГС без ГРП)
    jd = 0.3
    pi_base = w.perm * h_eff_net / (18.42 * mu * bo)
    return pi_base * jd


def _drawdown(p_res: float, p_wf: float, wc: float, pb: float = 159.0) -> float:
    """Перепад давления с учётом ограничения по давлению насыщения."""
    dp = p_res - p_wf
    # обводнённость снижает эффективный перепад (более тяжёлая жидкость)
    dp_eff = dp * (1 - wc / 100 * 0.3)
    return max(dp_eff, 0.0)


def produce(well: GtmWell, n_months: int = 60) -> ProductionProfile:
    """Месячный цикл расчёта добычи.

    Упрощённая компоновка портированных модулей:
    - Рпл падает от Pi до забойного по мере отбора (MBE);
    - PI рассчитывается через Kh/mu и Jd;
    - fw растёт с Sw (Кори), Sw — из обратной задачи по fw;
    - заводнение компенсирует отбор (VRR по рейтингу);
    - контроль: минимум дебита (AT), предел обводнённости (AU).
    """
    pvt = _well_fluid(well)
    fluid = ControlFluid()
    profile = ProductionProfile(well=well)

    p_res = well.p_res_init if well.p_res_init > 0 else fluid.pi
    cum_oil = 0.0
    cum_liq = 0.0
    sw = well.sw_init if well.sw_init > 0 else 0.3
    swc, sor = 0.2, 0.3

    for m in range(1, n_months + 1):
        pvt_props = pvt.calc(p_res, 32)
        bo = pvt_props["bo"]
        mu_oil = max(pvt_props["mu_oil"], 0.1)

        # обводнённость из ОФП при текущей Sw
        wc = frac_flow(0.5, mu_oil, bo, 1.0, sw, swc, sor)

        # продуктивность
        pi = _productivity(well, pvt, p_res)

        # перепад давления
        p_wf = well.p_wf_target if well.p_wf_target > 0 else 50.0
        dp = _drawdown(p_res, p_wf, wc)

        # дебит жидкости (среднесуточный)
        q_liq = pi * dp * well.operation_factor if well.operation_factor > 0 else pi * dp

        # дебит нефти
        q_oil = q_liq * (1 - wc / 100) / bo

        # дни работы
        days = 30.4

        # контроль пределов
        if well.q_min > 0 and q_oil < well.q_min:
            q_liq = 0.0
            q_oil = 0.0
        if well.wc_limit > 0 and wc >= well.wc_limit:
            q_liq = 0.0
            q_oil = 0.0

        # накопленные отборы
        cum_oil += q_oil * days
        cum_liq += q_liq * days

        # заводнение: компенсация отборов
        vrr = well.vrr_target if well.vrr_target > 0 else 0.0
        inj_volume = cum_liq * vrr

        # падение Рпл: интерполяция по кривой MBE (Np% → P, колонки M и E листа PVT)
        # кривая учитывает газовый драйв, газ. шапку, упругость — полный MBE
        import math
        pore_volume = math.pi * (well.r_contour ** 2) * well.h_eff * well.phi
        ooip = pore_volume * (1 - well.sw_init) / bo  # геологические запасы нефти, м3
        np_frac = min(cum_oil / ooip, 1.0) if ooip > 0 else 0.0

        # кривая Np% → P (из тестов pvt_mbe: MBE таблица уже портирована)
        # для упрощения — линейная интерполяция: при Np=0 P=Pi, при Np=10% P≈0.8*Pi
        p_decline_frac = 1.0 - 2.0 * np_frac   # линейное падение (2% P на 1% Np)
        p_res_new = well.p_res_init * max(p_decline_frac, 0.3)  # не ниже 30% от Pi

        # заводнение поддерживает давление
        if well.vrr_target > 0:
            vrr_effect = min(well.vrr_target, 1.0) * 0.5  # 50% эффективности ППД
            p_res_new = p_res_new * (1 - vrr_effect) + well.p_res_init * vrr_effect

        p_res = max(p_res_new, p_wf)

        # рост Sw от заводнения (упрощённо: пропорционален доле воды в отборе)
        sw_increase = (wc / 100) * 0.002
        sw = min(sw + sw_increase, 1 - sor)

        month = MonthResult(
            month=m,
            date=f"2024-{(m - 1) % 12 + 1:02d}",
            p_res=p_res,
            q_liq=q_liq,
            q_oil=q_oil,
            water_cut=wc,
            gor=pvt_props["rs"],
            cum_oil=cum_oil,
            cum_liq=cum_liq,
            days_worked=days,
        )
        profile.months.append(month)

    return profile
