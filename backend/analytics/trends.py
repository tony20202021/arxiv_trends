from __future__ import annotations
import datetime as dt
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from config.constants import (
    TOP_N,
    GROWTH_WINDOW_WEEKS,
    MAX_KEYWORD_DF_PCT,
    MIN_KEYWORD_PCT,
    STOPWORDS_EN,
)


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


def _normalize_article_counts(article_counts: dict) -> dict:
    return {
        (k.replace(tzinfo=dt.timezone.utc) if isinstance(k, dt.datetime) and k.tzinfo is None else k): v
        for k, v in article_counts.items()
    }


def pivot_week_keyword_pct(
    pivot: pd.DataFrame,
    article_counts: dict,
    score_scale: int = 1,
) -> pd.DataFrame:
    """Нормализовать pivot по числу статей за каждую неделю (результат в %)."""
    if pivot.empty or not article_counts:
        return pivot.copy().astype(float)

    normalized = _normalize_article_counts(article_counts)
    pct = pivot.copy().astype(float)
    for week in pct.index:
        n = normalized.get(week, 0)
        if n > 0:
            pct.loc[week] = pct.loc[week] / (n * score_scale) * 100
        else:
            pct.loc[week] = 0.0
    return pct


def _is_stopword_keyword(kw: str) -> bool:
    parts = kw.lower().split()
    return not parts or all(p in STOPWORDS_EN for p in parts)


def _dedup_substrings(keywords: List[str], limit: int) -> List[str]:
    kept: List[str] = []
    for kw in keywords:
        if any(kw in other for other in kept):
            continue
        kept = [other for other in kept if other not in kw]
        kept.append(kw)
        if len(kept) == limit:
            break
    return kept


def _filter_by_max_df(pivot: pd.DataFrame, max_df_pct: float) -> pd.DataFrame:
    """Убрать колонки, где max pct за период pivot > max_df_pct."""
    if pivot.empty or max_df_pct <= 0:
        return pivot
    col_max = pivot.max()
    keep = col_max[col_max <= max_df_pct].index
    return pivot[keep]


def top_popular_now(
    pivot: pd.DataFrame,
    top_n: int = TOP_N,
    article_counts: Optional[dict] = None,
    score_scale: int = 1,
    max_df_pct: float = MAX_KEYWORD_DF_PCT,
    min_pct: float = MIN_KEYWORD_PCT,
) -> List[str]:
    if pivot.empty:
        return []

    if article_counts:
        ranked_pivot = pivot_week_keyword_pct(pivot, article_counts, score_scale)
        ranked_pivot = _filter_by_max_df(ranked_pivot, max_df_pct)
        last_week = ranked_pivot.index.max()
        last_row = ranked_pivot.loc[last_week]
        last_row = last_row[last_row >= min_pct]
        ranked = [k for k in last_row.sort_values(ascending=False).index if not _is_stopword_keyword(k)]
    else:
        last_week = pivot.index.max()
        ranked = [
            k for k in pivot.loc[last_week].sort_values(ascending=False).index
            if not _is_stopword_keyword(k)
        ]

    return _dedup_substrings(ranked, top_n)


def top_growing_last_window(
    pivot: pd.DataFrame,
    window_weeks: int = GROWTH_WINDOW_WEEKS,
    top_n: int = TOP_N,
    article_counts: Optional[dict] = None,
    score_scale: int = 1,
    max_df_pct: float = MAX_KEYWORD_DF_PCT,
) -> List[str]:
    if pivot.empty:
        return []

    work = pivot_week_keyword_pct(pivot, article_counts, score_scale) if article_counts else pivot.copy()
    work = work.sort_index()
    last_week = work.index.max()
    window_start = last_week - pd.Timedelta(weeks=window_weeks - 1)
    w = work[work.index >= window_start]
    if len(w.index) < 2:
        return top_popular_now(pivot, top_n, article_counts, score_scale, max_df_pct)

    w = _filter_by_max_df(w, max_df_pct)
    if w.empty:
        return []

    x = np.arange(len(w.index), dtype=np.float32)
    scores: dict[str, float] = {}
    for kw in w.columns:
        y = w[kw].values.astype(np.float32)
        if y.sum() == 0:
            continue
        scores[kw] = float(np.polyfit(x, y, 1)[0])

    ranked = [k for k, _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True) if not _is_stopword_keyword(k)]
    return _dedup_substrings(ranked, top_n)


def growing_slopes(
    pivot: pd.DataFrame,
    keywords: List[str],
    window_weeks: Optional[int] = None,
    article_counts: Optional[dict] = None,
    score_scale: int = 1,
) -> Dict[str, float]:
    if pivot.empty or not keywords:
        return {}
    work = pivot_week_keyword_pct(pivot, article_counts, score_scale) if article_counts else pivot
    work = work.sort_index()
    if window_weeks is not None:
        work = work.iloc[-window_weeks:]
    if len(work.index) < 2:
        return {}
    x = np.arange(len(work.index), dtype=np.float32)
    result = {}
    for kw in keywords:
        if kw not in work.columns:
            continue
        y = work[kw].values.astype(np.float32)
        result[kw] = float(np.polyfit(x, y, 1)[0])
    return result
