from __future__ import annotations
import datetime as dt
from typing import List

import numpy as np
import pandas as pd

from config.constants import TOP_N, GROWTH_WINDOW_WEEKS


def to_frame(rows: List[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["domain", "week_start", "keyword", "count"])
    df = pd.DataFrame(rows)
    df["week_start"] = pd.to_datetime(df["week_start"], utc=True)
    return df


def pivot_week_keyword(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    p = df.pivot_table(index="week_start", columns="keyword", values="count", aggfunc="sum", fill_value=0)
    return p.sort_index()


def pivot_week_keyword_pct(pivot: pd.DataFrame, article_counts: dict) -> pd.DataFrame:
    """Нормализовать pivot по числу статей за каждую неделю (результат в %).

    Args:
        pivot: DataFrame из pivot_week_keyword()
        article_counts: {datetime: int} из store.get_article_counts_by_week()

    Returns:
        DataFrame с теми же колонками, значения в % (0–100)
    """
    if pivot.empty or not article_counts:
        return pivot.copy().astype(float)

    # pymongo возвращает naive datetime, to_frame() конвертирует в UTC-aware.
    # Приводим ключи article_counts к UTC-aware чтобы совпадали с индексом pivot.
    normalized = {
        (k.replace(tzinfo=dt.timezone.utc) if isinstance(k, dt.datetime) and k.tzinfo is None else k): v
        for k, v in article_counts.items()
    }

    pct = pivot.copy().astype(float)
    for week in pct.index:
        n = normalized.get(week, 0)
        if n > 0:
            pct.loc[week] = pct.loc[week] / n * 100
        else:
            pct.loc[week] = 0.0
    return pct


def top_popular_now(pivot: pd.DataFrame, top_n: int = TOP_N) -> List[str]:
    if pivot.empty:
        return []
    last_week = pivot.index.max()
    return list(pivot.loc[last_week].sort_values(ascending=False).head(top_n).index)


def top_growing_last_window(
    pivot: pd.DataFrame,
    window_weeks: int = GROWTH_WINDOW_WEEKS,
    top_n: int = TOP_N
) -> List[str]:
    if pivot.empty:
        return []
    pivot = pivot.sort_index()
    last_week = pivot.index.max()
    window_start = last_week - pd.Timedelta(weeks=window_weeks - 1)
    w = pivot[pivot.index >= window_start]
    if len(w.index) < 2:
        return top_popular_now(pivot, top_n)

    x = np.arange(len(w.index), dtype=np.float32)
    scores = {}
    for kw in w.columns:
        y = w[kw].values.astype(np.float32)
        if y.sum() == 0:
            continue
        slope = np.polyfit(x, y, 1)[0]
        scores[kw] = float(slope)

    top = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
    return [k for k, _ in top]
