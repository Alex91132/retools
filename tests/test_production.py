# -*- coding: utf-8 -*-
"""Тесты движка добычи: компоновка портированных модулей."""
import math
import os

import pytest

from retools.gtm_io import GtmWell, read_gtm
from retools.production import produce

BOOK = os.environ.get("RETOOLS_BOOK", "")


def vankor_well() -> GtmWell:
    """Скважина №1 из рейтинга ГТМ (кэш книги, адаптированная для движка).

    В книге flood_share=0.99 (99% толщин заводняются) — при такой доле истощаемая
    часть мала. Для теста компоновки движка берём flood_share=0.5 и начальную
    Sw=0.3 (типично для ВНС на объекте).
    """
    return GtmWell(
        n=1, region="Район-1", field="Северное", pad="1", well="1",
        target_zone="Пласт-А", pvt_sheet="PVT_MBE_Waterflood",
        gtm="ВНС", case="ГС по слоям", completion="ГС", purpose="доб.",
        h_eff=20, phi=0.18, perm=250, kv_kh=0.1, sw_init=0.3,
        p_res_init=110, flood_share=0.5, l_hor=300, l_hor_eff=300,
        r_contour=400, r_well=0.1, skin=0.0, p_wf_target=50,
        operation_factor=0.95, q_min=1, wc_limit=98,
        oip=500.0,
    )


def test_produces_positive_rates():
    p = produce(vankor_well(), n_months=24)
    assert len(p.months) == 24
    qn = [m.q_oil for m in p.months]
    assert all(q > 0 for q in qn[:12]), "первые 12 месяцев добыча > 0"


def test_declining_profile():
    """Дебит нефти убывает (истощение + рост обводнённости)."""
    p = produce(vankor_well(), n_months=36)
    qn = [m.q_oil for m in p.months]
    assert qn[0] > qn[6] > qn[12], "профиль убывает"
    assert qn[0] > qn[-1]


def test_water_cut_rises():
    """Обводнённость растёт от месяца к месяцу."""
    p = produce(vankor_well(), n_months=24)
    wc = [m.water_cut for m in p.months]
    assert wc[0] < wc[-1]


def test_pressure_declines():
    """Рпл падает с накопленным отбором."""
    p = produce(vankor_well(), n_months=24)
    pres = [m.p_res for m in p.months]
    assert pres[0] >= pres[-1]


def test_cumulative_monotonic():
    p = produce(vankor_well(), n_months=24)
    cum = [m.cum_oil for m in p.months]
    assert cum == sorted(cum)


def test_waterflood_supports_pressure():
    """С ППД (VRR>0) Рпл держится выше, чем без него."""
    w1 = vankor_well()
    w1.vrr_target = 1.0
    w2 = vankor_well()
    w2.vrr_target = 0.0
    p1 = produce(w1, n_months=24)
    p2 = produce(w2, n_months=24)
    assert p1.months[-1].p_res >= p2.months[-1].p_res


@pytest.mark.skipif(not os.path.exists(BOOK), reason="книга недоступна")
def test_engine_on_book_well():
    """Скважина №1 книги: flood_share=0.99 (99% ППД) — Qн близка к нулю,
    но движок отрабатывает без ошибок и производит корректную структуру."""
    wells = read_gtm(BOOK)
    if not wells:
        pytest.skip("рейтинг пуст")
    p = produce(wells[0], n_months=12)
    assert len(p.months) == 12
    # движок производит расчёт (даже если Qн=0 из-за предела или обводнённости)
    assert all(m.q_oil >= 0 for m in p.months)
    assert all(m.water_cut >= 0 for m in p.months)
    assert p.months[0].p_res >= p.months[-1].p_res  # Рпл не растёт
