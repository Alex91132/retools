# -*- coding: utf-8 -*-
"""retools — порт расчётника RE Tools (VBA/Excel) на Python.

MVP по первым четырём вкладкам исходной книги:
- fa: факторный анализ отклонений Qн (лист «ФА»);
- jd: безразмерная продуктивность Jd и эквивалент трещины ГРП (Get_Jd/Get_x_f);
- intervals: модель данных интервалов РИГИС (лист «РИГИС»).
"""
from .fa import Scenario, FactorResult, decompose, factors_sorted
from .intervals import Interval, WellIntervals
from .intervals_io import RigisData, IntervalChoice, read_rigis
from .jd import get_jd, get_x_f
from .jd_pallets import Pallet, default_pallet
from .cpvt import CPVT
from .production import produce, ProductionProfile, MonthResult
from .gtm_io import GtmWell, read_gtm, read_result
from .pallets import Grid, default_pallets, read_pallets, mu_mix, kro_mix, krw_mix
from .pvt_mbe import (ControlFluid, corey_kro, corey_krw, eff_mu, eff_fvf,
                      frac_flow, kro_baker, mbe_lhs, mbe_rhs, rp_from_relperm,
                      sw_from_fw, total_compressibility)

__version__ = "0.1.0"
__all__ = [
    "Scenario", "FactorResult", "decompose", "factors_sorted",
    "Interval", "WellIntervals", "RigisData", "IntervalChoice", "read_rigis",
    "get_jd", "get_x_f",
    "Pallet", "default_pallet", "ControlFluid", "CPVT", "Grid", "default_pallets", "read_pallets",
    "mu_mix", "kro_mix", "krw_mix",
    "GtmWell", "read_gtm", "read_result",
    "produce", "ProductionProfile", "MonthResult",
    "corey_kro", "corey_krw", "eff_mu", "eff_fvf", "frac_flow", "kro_baker",
    "mbe_lhs", "mbe_rhs", "rp_from_relperm", "sw_from_fw", "total_compressibility",
]
