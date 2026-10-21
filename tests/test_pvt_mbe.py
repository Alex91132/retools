# -*- coding: utf-8 -*-
"""Тесты PVT/MBE: аналитика + эталоны из кэша листа PVT_MBE_Waterflood."""
import json
import math
from pathlib import Path

from retools.pvt_mbe import (
    ControlFluid, corey_kro, corey_krw, eff_mu, eff_fvf, frac_flow,
    kro_baker, mbe_lhs, mbe_rhs, rp_from_relperm, sw_from_fw,
    total_compressibility,
)

FIXTURE = json.loads((Path(__file__).parent / "mbe_fixture.json").read_text(encoding="utf-8"))


# ---------- ОФП Кори и обводнённость ----------

def test_corey_endpoints_and_monotonic():
    swc, sor = 0.2, 0.3
    assert math.isclose(corey_krw(swc, swc, sor), 0.0)
    assert math.isclose(corey_krw(1 - sor, swc, sor), 1.0)     # krw_end=1
    assert math.isclose(corey_kro(swc, swc, sor), 1.0)
    assert math.isclose(corey_kro(1 - sor, swc, sor), 0.0)
    # промежуточная точка: SD=0.5, M=1 -> 0.5
    sw_mid = swc + 0.5 * (1 - sor - swc)
    assert math.isclose(corey_krw(sw_mid, swc, sor), 0.5)
    assert math.isclose(corey_kro(sw_mid, swc, sor), 0.5)


def test_frac_flow_bounds_and_equal_viscosities():
    swc, sor = 0.2, 0.3
    assert frac_flow(1, 1, 1.1, 1.0, swc, swc, sor) == 0.0
    assert frac_flow(1, 1, 1.1, 1.0, 1 - sor, swc, sor) == 100.0
    # при равных µ и B и симметричных ОФП fw(SD=0.5) = 50 %
    sw_mid = swc + 0.5 * (1 - sor - swc)
    assert math.isclose(frac_flow(1, 1, 1.0, 1.0, sw_mid, swc, sor), 50.0)


def test_sw_from_fw_roundtrip():
    swc, sor = 0.2, 0.3
    for fw in (10.0, 40.0, 70.0, 95.0):
        sw = sw_from_fw(fw, mu_w=0.5, mu_o=3.0, bo=1.1, bw=1.0, swc=swc, sor=sor)
        back = frac_flow(0.5, 3.0, 1.1, 1.0, sw, swc, sor)
        assert abs(back - fw) < 0.5, (fw, back)


def test_eff_mu_total_compressibility_eff_fvf():
    # SD=0.5 -> krw=kro=0.5: mu = 1/(0.5+0.5) = 1.0
    assert math.isclose(eff_mu(1.0, 1.0, 0.5, 0.2, 0.3), 1.0)
    assert math.isclose(total_compressibility(3e-5, 1e-4, 4e-5, 0.3),
                        1e-4 * 0.7 + 4e-5 * 0.3 + 3e-5)
    assert math.isclose(eff_fvf(1.2, 1.0, 25.0), 1.2 * 0.75 + 1.0 * 0.25)


# ---------- Материальный баланс: эталоны книги ----------

def test_mbe_matches_book_cache():
    """Обе части MBE порознь совпадают с кэшем книги на всех давлениях.

    Примечание: в самой книге LHS = RHS не на всех строках — при низких P
    кэшированный Np не решает уравнение (колонка Δ книги показывает остаток);
    проверять баланс LHS==RHS по кэшу нельзя, поэтому сверяем каждую часть
    с её книжным значением."""
    c = ControlFluid()
    for row in FIXTURE["rows"]:
        lhs = mbe_lhs(row["Np"], row["Bo"], row["Bg"], row["Rs"], row["Rp"])
        rhs100 = 100.0 * mbe_rhs(row["Bo"], c.boi, c.rsi, row["Rs"], row["Bg"], c.bgi,
                                 c.swl, c.cw, c.cf, c.pi, row["P"], m=c.m_cap)
        assert math.isclose(lhs, row["MBE_LHS"], rel_tol=1e-9), (row["P"], lhs)
        assert math.isclose(rhs100, row["MBE_RHS"], rel_tol=1e-9), (row["P"], rhs100)


def test_mbe_lhs_manual():
    # Np=10, Bo=1.1, Bg=0.005, rs=50, rp=60: 10*(1.1 + 10*0.005) = 11.5
    assert math.isclose(mbe_lhs(10, 1.1, 0.005, 50, 60), 11.5)


# ---------- Бейкер и RP ----------

def test_kro_baker_gas_free_equals_ow():
    v = kro_baker(sw=0.5, swl=0.2, sg=0.0, sorg_og=0.18, sorw_ow=0.227,
                  fo=0.76, exo_ow=1.2, exo_og=1.1)
    sd = (0.5 - 0.2) / (1 - 0.227 - 0.2)
    assert math.isclose(v, 0.76 * (1 - sd) ** 1.2)


def test_kro_baker_weighted_combination():
    """Взвешенная сумма: kro_ow считается при SD, включающем sg (как в VBA)."""
    sw, swl, sg = 0.5, 0.2, 0.1
    fo, exo_ow, exo_og, sorg, sorw = 0.76, 1.2, 1.1, 0.18, 0.227
    v = kro_baker(sw, swl, sg, sorg, sorw, fo, exo_ow, exo_og)
    sd = (sw - swl + sg) / (1 - sorw - swl)
    kro_ow = fo * (1 - sd) ** exo_ow
    kro_og = fo * (1 - (sg + sw - swl) / (1 - sorg - swl)) ** exo_og
    w = sw - swl
    expected = kro_ow * w / (sg + w) + kro_og * sg / (w + sg)
    assert math.isclose(v, expected)
    assert 0 <= v <= fo


def test_rp_from_relperm_no_gas():
    # krg=0 -> Rp = (Rsi + Rs)/2
    assert math.isclose(rp_from_relperm(60, 50, 0.0, 0.5, 3.0, 1.1, 0.02, 0.005), 55.0)
