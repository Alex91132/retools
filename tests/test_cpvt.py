# -*- coding: utf-8 -*-
"""Паритет CPVT с кэшем листа PVT_MBE_Waterflood (corr=1 McCain-based).

Параметры контрольного флюида (колонка D книги): gg=0.7, go=0.9, gw=1.01,
rsb=60, pb=159 атм, bob=1.08, muob=8.8, t_res=32 C, корреляции = 1.
"""
import json
import math
from pathlib import Path

from retools.cpvt import CPVT

FIXTURE = json.loads((Path(__file__).parent / "cpvt_fixture.json").read_text(encoding="utf-8"))


def control_fluid() -> CPVT:
    return CPVT(gamma_gas=0.7, gamma_oil=0.9, gamma_wat=1.01, rsb_m3m3=60,
                pb_atma=159, bob_m3m3=1.08, muob_cP=8.8, corr=1, t_res_C=32)


def test_rs_parity():
    fl = control_fluid()
    worst = 0.0
    for row in FIXTURE:
        got = fl.calc(row["P"], 32)["rs"]
        worst = max(worst, abs(got - row["Rs"]) / max(row["Rs"], 1e-9))
    assert worst < 1e-9, f"worst rel {worst:.2e}"


def test_bo_parity():
    fl = control_fluid()
    worst = 0.0
    for row in FIXTURE:
        got = fl.calc(row["P"], 32)["bo"]
        worst = max(worst, abs(got - row["Bo"]) / row["Bo"])
    assert worst < 1e-9, f"worst rel {worst:.2e}"


def test_bg_parity():
    fl = control_fluid()
    worst = 0.0
    for row in FIXTURE:
        got = fl.calc(row["P"], 32)["bg"]
        worst = max(worst, abs(got - row["Bg"]) / row["Bg"])
    assert worst < 1e-9, f"worst rel {worst:.2e}"


def test_mu_gas_parity():
    fl = control_fluid()
    worst = 0.0
    for row in FIXTURE:
        got = fl.calc(row["P"], 32)["mu_gas"]
        worst = max(worst, abs(got - row["mu_gas"]) / row["mu_gas"])
    assert worst < 1e-9, f"worst rel {worst:.2e}"


def test_saturation_point():
    """При P = Pb = 159 атм Rs = Rsb = 60."""
    fl = control_fluid()
    res = fl.calc(159, 32)
    assert math.isclose(res["rs"], 60.0, rel_tol=1e-9)


def test_standing_path_runs_and_shape():
    fl = CPVT(gamma_gas=0.7, gamma_oil=0.9, rsb_m3m3=60, pb_atma=159,
              bob_m3m3=1.08, muob_cP=8.8, corr=0, t_res_C=32)
    res = {p: fl.calc(p, 32) for p in (250, 159, 120, 80, 40, 10)}
    # Rs монотонно растёт с давлением; на калиброванном Рнас Rs ≈ Rsb
    # (в Standing-ветке формула Rs не является точной инверсией Pb — как в VBA;
    #  McCain/Velarde даёт ровно Rsb — проверено в test_saturation_point)
    rs_vals = [res[p]["rs"] for p in (10, 40, 80, 120, 159)]
    assert rs_vals == sorted(rs_vals)
    assert abs(res[159]["rs"] - 60.0) < 2.0
    # Bo максимален у Рнас: выше — сжатие, ниже — выделение газа
    assert res[159]["bo"] > res[250]["bo"]
    assert res[159]["bo"] > res[120]["bo"]
