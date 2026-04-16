from __future__ import annotations
import datetime as dt
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from config.constants import HISTORY_WEEKS

# Matplotlib tab10 (дефолтная палитра)
_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
]
_MARKERS = ["o", "s", "^", "D", "v", "P", "*", "X", "h", "<", ">", "p", "H", "+", "x"]


def build_keyword_styles(keywords: List[str]) -> Dict[str, Tuple[str, str]]:
    """Присвоить каждому ключевому слову цвет и маркер.

    Гарантирует что одно слово всегда получает одинаковые цвет и маркер
    независимо от того, в каком из двух графиков оно отображается.

    Args:
        keywords: упорядоченный список всех ключевых слов (объединение popular + growing)

    Returns:
        dict {keyword: (color, marker)}
    """
    return {
        kw: (_COLORS[i % len(_COLORS)], _MARKERS[i % len(_MARKERS)])
        for i, kw in enumerate(keywords)
    }


def plot_keywords_over_time(
    pivot: pd.DataFrame,
    keywords: List[str],
    title: str,
    out_path: Path,
    keyword_styles: Optional[Dict[str, Tuple[str, str]]] = None,
    regression_window: Optional[int] = None,
    ylabel: str = "Count",
):
    """Построить линейный график ключевых слов по неделям.

    Args:
        keyword_styles: словарь {keyword: (color, marker)} из build_keyword_styles.
            Если передан — слова из разных графиков получают одинаковые цвета и маркеры.
            Если None — стили назначаются по позиции в списке keywords.
        regression_window: если задан — рисует линию линейной регрессии за последние
            N недель для каждого ключевого слова (тем же цветом, тоньше и прозрачнее).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if pivot.empty or not keywords:
        fig = plt.figure()
        plt.title(title)
        plt.text(0.5, 0.5, "No data", ha="center", va="center")
        plt.axis("off")
        fig.savefig(out_path, bbox_inches="tight")
        plt.close(fig)
        return

    pivot = pivot.sort_index()
    if len(pivot.index) > HISTORY_WEEKS:
        pivot = pivot.iloc[-HISTORY_WEEKS:]

    fig = plt.figure()
    for i, kw in enumerate(keywords):
        if kw not in pivot.columns:
            continue
        if keyword_styles and kw in keyword_styles:
            color, marker = keyword_styles[kw]
        else:
            color = _COLORS[i % len(_COLORS)]
            marker = _MARKERS[i % len(_MARKERS)]
        plt.plot(
            pivot.index, pivot[kw].values,
            label=kw,
            color=color,
            marker=marker,
            markersize=5,
            linestyle="--",
        )

        if regression_window and len(pivot.index) >= 2:
            w = pivot.iloc[-regression_window:] if len(pivot.index) > regression_window else pivot
            x = np.arange(len(w.index), dtype=np.float32)
            y = w[kw].values.astype(np.float32)
            if y.sum() > 0:
                slope, intercept = np.polyfit(x, y, 1)
                y_reg = slope * x + intercept
                plt.plot(
                    w.index, y_reg,
                    color=color,
                    linewidth=2.5,
                    alpha=0.7,
                    linestyle=(0, (1, 1)),  # плотный пунктир-точки
                )

    plt.title(title)
    plt.xlabel("Week")
    plt.ylabel(ylabel)
    plt.legend(fontsize=8, ncols=2)
    fig.autofmt_xdate()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def plot_keyword_across_domains(
    keyword: str,
    domain_series: Dict[str, pd.Series],
    title: str,
    out_path: Path,
):
    """Кросс-доменный график: один ключевой термин по нескольким доменам.

    Args:
        keyword:       ключевой термин (для подписи на графике)
        domain_series: {domain_id: pd.Series(index=datetime, values=count)}
        title:         заголовок графика
        out_path:      путь к выходному PNG
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    non_empty = {d: s for d, s in domain_series.items() if not s.empty and s.sum() > 0}
    if not non_empty:
        fig = plt.figure()
        plt.title(title)
        plt.text(0.5, 0.5, f"No data for '{keyword}'", ha="center", va="center")
        plt.axis("off")
        fig.savefig(out_path, bbox_inches="tight")
        plt.close(fig)
        return

    fig = plt.figure()
    for i, (domain, series) in enumerate(sorted(non_empty.items())):
        color = _COLORS[i % len(_COLORS)]
        marker = _MARKERS[i % len(_MARKERS)]
        idx = sorted(series.index)
        if len(idx) > HISTORY_WEEKS:
            idx = idx[-HISTORY_WEEKS:]
        vals = [series.get(w, 0) for w in idx]
        plt.plot(idx, vals, label=domain, color=color, marker=marker,
                 markersize=5, linestyle="--")

    plt.title(title)
    plt.xlabel("Week")
    plt.ylabel("Count")
    plt.legend(fontsize=8, ncols=2)
    fig.autofmt_xdate()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def plot_article_counts(
    counts_by_week: Dict[dt.datetime, int],
    title: str,
    out_path: Path,
):
    """Столбчатый график количества статей по неделям."""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not counts_by_week:
        fig = plt.figure()
        plt.title(title)
        plt.text(0.5, 0.5, "No data", ha="center", va="center")
        plt.axis("off")
        fig.savefig(out_path, bbox_inches="tight")
        plt.close(fig)
        return

    weeks = sorted(counts_by_week)
    if len(weeks) > HISTORY_WEEKS:
        weeks = weeks[-HISTORY_WEEKS:]

    counts = [counts_by_week[w] for w in weeks]

    fig, ax = plt.subplots()
    ax.plot(weeks, counts, color=_COLORS[0], marker="o", markersize=5, linestyle="--")
    ax.set_title(title)
    ax.set_xlabel("Week")
    ax.set_ylabel("Articles")
    fig.autofmt_xdate()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
