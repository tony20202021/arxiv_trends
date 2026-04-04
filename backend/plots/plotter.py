from __future__ import annotations
from pathlib import Path
from typing import List

import pandas as pd
import matplotlib.pyplot as plt

from config.constants import HISTORY_WEEKS


def plot_keywords_over_time(pivot: pd.DataFrame, keywords: List[str], title: str, out_path: Path):
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

    _markers = ["o", "s", "^", "D", "v", "P", "*", "X", "h", "<", ">", "p", "H", "+", "x"]

    fig = plt.figure()
    for i, kw in enumerate(keywords):
        if kw in pivot.columns:
            plt.plot(
                pivot.index, pivot[kw].values,
                label=kw,
                marker=_markers[i % len(_markers)],
                markersize=5,
            )

    plt.title(title)
    plt.xlabel("Week")
    plt.ylabel("Count")
    plt.legend(fontsize=8, ncols=2)
    fig.autofmt_xdate()
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
