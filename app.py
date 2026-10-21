# -*- coding: utf-8 -*-
"""Streamlit-приложение retools: интерактивный расчёт добычи.

Запуск: streamlit run app.py
"""
import streamlit as st
import numpy as np
import matplotlib.pyplot as plt

from retools.fa import Scenario, decompose
from retools.cpvt import CPVT
from retools.pallets import default_pallets
from retools import ui_gtm, ui_rigis

st.set_page_config(page_title="RE Tools", page_icon="🛢️", layout="wide")
st.title("🛢️ RE Tools: расчёт добычи скважин")
st.caption("Порт расчётника RE Tools (Excel/VBA → Python) | "
           "РИГИС, PVT, матбаланс, ОФП, Jd-продуктивность, палетки")

tab_rigis, tab_prod, tab_pvt, tab_fa, tab_pal = st.tabs([
    "🧭 Подбор компоновки (РИГИС)", "📊 Расчёт добычи (рейтинг ГТМ)", "🧪 PVT-свойства", "📈 Факторный анализ", "🎛️ Палетки"
])

with tab_rigis:
    ui_rigis.render()

# ============ Расчёт добычи ============
with tab_prod:
    ui_gtm.render()

# ============ PVT ============
with tab_pvt:
    st.header("PVT-свойства флюида")

    col1, col2 = st.columns(2)
    with col1:
        rsb = st.slider("Газосодержание при Рнас (Rsb)", 20, 300, 60, 10)
        pb = st.slider("Давление насыщения (Pb)", 50, 250, 159, 5)
    with col2:
        gamma_g = st.slider("Отн. плотность газа", 0.55, 1.2, 0.7, 0.05)
        gamma_o = st.slider("Отн. плотность нефти", 0.8, 1.0, 0.9, 0.01)

    fluid = CPVT(gamma_gas=gamma_g, gamma_oil=gamma_o, rsb_m3m3=rsb,
                 pb_atma=pb, bob_m3m3=1.08, muob_cP=8.8, corr=1, t_res_C=32)

    pressures = np.linspace(10, 350, 50)
    props = [fluid.calc(p, 32) for p in pressures]

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    fig.suptitle("PVT-свойства (McCain-based)", fontsize=14, fontweight="bold")

    axes[0, 0].plot(pressures, [p["rs"] for p in props], "b-")
    axes[0, 0].axvline(pb, color="r", ls="--", alpha=0.5, label="Pb")
    axes[0, 0].set_ylabel("Rs, м³/м³")
    axes[0, 0].set_title("Газосодержание")
    axes[0, 0].legend()
    axes[0, 0].grid(alpha=0.3)

    axes[0, 1].plot(pressures, [p["bo"] for p in props], "g-")
    axes[0, 1].axvline(pb, color="r", ls="--", alpha=0.5)
    axes[0, 1].set_ylabel("Bo, м³/м³")
    axes[0, 1].set_title("Объёмный коэффициент")
    axes[0, 1].grid(alpha=0.3)

    axes[1, 0].plot(pressures, [p["mu_oil"] for p in props], "r-")
    axes[1, 0].axvline(pb, color="r", ls="--", alpha=0.5)
    axes[1, 0].set_ylabel("µ, сПз")
    axes[1, 0].set_title("Вязкость нефти")
    axes[1, 0].grid(alpha=0.3)

    axes[1, 1].plot(pressures, [p["z"] for p in props], "k-")
    axes[1, 1].set_ylabel("z")
    axes[1, 1].set_title("Коэф. сверхсжимаемости газа")
    axes[1, 1].grid(alpha=0.3)

    for ax in axes.flat:
        ax.set_xlabel("P, атм")

    plt.tight_layout()
    st.pyplot(plt.gcf())
    plt.close()

# ============ Факторный анализ ============
with tab_fa:
    st.header("Факторный анализ отклонений Qн")

    st.markdown("""
    Разложение отклонения дебита нефти между двумя состояниями скважины
    на вклады четырёх факторов: обводнённость, Рпл, Рзаб, Кпр.
    """)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Базовый сценарий")
        b_qliq = st.number_input("Qж, м³/сут", 50.0, 500.0, 200.0, key="b_q")
        b_wc = st.number_input("Обводнённость, %", 0.0, 100.0, 10.0, key="b_wc")
        b_qoil = st.number_input("Qн (тренд), т/сут", 50.0, 500.0, 150.0, key="b_qn")
        b_pwf = st.number_input("Рзаб, атм", 20.0, 200.0, 80.0, key="b_pwf")
        b_pres = st.number_input("Рпл, атм", 50.0, 300.0, 120.0, key="b_pres")
    with col2:
        st.subheader("Новый сценарий")
        n_qliq = st.number_input("Qж, м³/сут", 50.0, 500.0, 210.0, key="n_q")
        n_wc = st.number_input("Обводнённость, %", 0.0, 100.0, 0.0, key="n_wc")
        n_qoil = st.number_input("Qн (тренд), т/сут", 50.0, 500.0, 170.0, key="n_qn")
        n_pwf = st.number_input("Рзаб, атм", 20.0, 200.0, 90.0, key="n_pwf")
        n_pres = st.number_input("Рпл, атм", 50.0, 300.0, 110.0, key="n_pres")

    base = Scenario(q_liq=b_qliq, water_cut=b_wc, q_oil=b_qoil, p_wf=b_pwf, p_res=b_pres)
    new = Scenario(q_liq=n_qliq, water_cut=n_wc, q_oil=n_qoil, p_wf=n_pwf, p_res=n_pres)
    result = decompose(base, new)

    st.subheader(f"ΔQн = {result.delta_q_oil:+.1f} м³/сут")

    factors = {
        "Обводнённость": result.water_cut,
        "Рпл": result.p_res,
        "Рзаб": result.p_wf,
        "Кпр": result.pi,
    }

    fig, ax = plt.subplots(figsize=(8, 4))
    names = list(factors.keys())
    vals = list(factors.values())
    colors = ["g" if v > 0 else "r" for v in vals]
    bars = ax.barh(names, vals, color=colors, alpha=0.7)
    ax.axvline(0, color="k", lw=1)
    ax.set_xlabel("Вклад в ΔQн, м³/сут")
    ax.set_title("Разложение отклонения дебита нефти")
    ax.grid(alpha=0.3, axis="x")
    for bar, val in zip(bars, vals):
        ax.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height() / 2,
                f"{val:+.1f}", va="center", fontsize=10)
    plt.tight_layout()
    st.pyplot(plt.gcf())
    plt.close()

    st.info(f"Невязка баланса: {result.balance_error:.6f} м³/сут (сумма факторов = ΔQн)")

# ============ Палетки ============
with tab_pal:
    st.header("Палетки нормировки Jd")

    pallets = default_pallets()
    pallet_name = st.selectbox("Палетка", ["mu", "kro_mix", "krw_mix"],
                               format_func=lambda x: {
                                   "mu": "Вязкость смеси (P × Sw)",
                                   "kro_mix": "ОФП нефти (%НПЗ × Sw)",
                                   "krw_mix": "ОФП воды (%НПЗ × Sw)"
                               }[x])

    g = pallets[pallet_name]
    f = np.array(g.f, dtype=float)

    y_label = "Рпл, атм" if pallet_name == "mu" else "%НПЗ"
    x_label = "Sw"

    fig, ax = plt.subplots(figsize=(10, 6))
    im = ax.imshow(f, cmap="YlOrRd", aspect="auto", origin="lower")
    ax.set_xticks(range(len(g.x)))
    ax.set_xticklabels([f"{v:.2f}" for v in g.x], rotation=45, fontsize=8)
    ax.set_yticks(range(len(g.y)))
    ax.set_yticklabels([f"{v:.0f}" if v > 1 else f"{v:.1f}" for v in g.y], fontsize=8)
    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.set_title(f"Палетка: {pallet_name}")
    plt.colorbar(im, ax=ax, shrink=0.8)
    plt.tight_layout()
    st.pyplot(plt.gcf())
    plt.close()

    st.markdown("""
    **Как пользоваться**: палетки нормируют Jd (безразмерную продуктивность)
    для секций горизонтальной скважины разной длины при разных давлениях
    и насыщенностях. Интерполяция — билинейная по сетке.
    """)
