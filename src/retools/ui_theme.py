# -*- coding: utf-8 -*-
"""Единый стиль графиков: plotly-темы и настройки matplotlib.

Зачем отдельный модуль: раньше каждый график задавал свои поля, легенды и размеры,
поэтому подписи отличались, а на узком экране три графика в ряд становились
нечитаемыми. Здесь — один набор правил, который подключают все страницы.
"""

from __future__ import annotations

import plotly.graph_objects as go

# цвета для величин: нефть, жидкость, вода, давление, закачка
COLORS = {
    "oil": "#2e9d4f",
    "liq": "#2f7fd8",
    "water": "#d64545",
    "p_res": "#8e44ad",
    "p_wf": "#9aa0a6",
    "inj": "#e07b00",
    "accent": "#b33a1f",
}

# размеры шрифтов для matplotlib-графиков (PVT, факторный анализ, палетки)
MPL_RC = {
    "font.size": 10,
    "axes.titlesize": 11,
    "axes.labelsize": 10,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "legend.fontsize": 9,
    "figure.titlesize": 12,
}


def style(fig: go.Figure, height: int = 320, legend: bool = True) -> go.Figure:
    """Приводит plotly-график к общему виду: белый фон, читаемые подписи, легенда снизу."""
    fig.update_layout(
        template="plotly_white",
        height=height,
        font=dict(size=13),
        margin=dict(l=10, r=10, t=40, b=10),
        hovermode="x unified",
    )
    if legend:
        fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=-0.35, x=0))
    return fig


__all__ = ["COLORS", "MPL_RC", "style"]