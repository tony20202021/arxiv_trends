from __future__ import annotations
import datetime as dt

import pandas as pd
import pytest

from analytics.trends import (
    to_frame,
    pivot_week_keyword,
    top_popular_now,
    top_growing_last_window,
)


def _make_rows(domain: str = "cs_lg") -> list[dict]:
    base = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
    rows = []
    keywords = ["transformer", "diffusion", "attention"]
    for week_offset in range(4):
        ws = base + dt.timedelta(weeks=week_offset)
        for i, kw in enumerate(keywords):
            rows.append({
                "domain": domain,
                "week_start": ws,
                "keyword": kw,
                "count": (i + 1) * (week_offset + 1),
            })
    return rows


class TestToFrame:
    def test_empty_returns_empty_df(self):
        df = to_frame([])
        assert df.empty
        assert list(df.columns) == ["domain", "week_start", "keyword", "count"]

    def test_non_empty_has_datetime_column(self):
        rows = _make_rows()
        df = to_frame(rows)
        assert pd.api.types.is_datetime64_any_dtype(df["week_start"])


class TestPivotWeekKeyword:
    def test_empty_returns_empty(self):
        df = to_frame([])
        pivot = pivot_week_keyword(df)
        assert pivot.empty

    def test_shape(self):
        rows = _make_rows()
        df = to_frame(rows)
        pivot = pivot_week_keyword(df)
        assert pivot.shape[0] == 4   # 4 недели
        assert pivot.shape[1] == 3   # 3 ключевых слова

    def test_index_sorted(self):
        rows = _make_rows()
        df = to_frame(rows)
        pivot = pivot_week_keyword(df)
        assert list(pivot.index) == sorted(pivot.index)


class TestTopPopularNow:
    def test_empty_pivot_returns_empty(self):
        result = top_popular_now(pd.DataFrame(), top_n=5)
        assert result == []

    def test_returns_top_n(self):
        rows = _make_rows()
        df = to_frame(rows)
        pivot = pivot_week_keyword(df)
        result = top_popular_now(pivot, top_n=2)
        assert len(result) == 2

    def test_most_popular_first(self):
        rows = _make_rows()
        df = to_frame(rows)
        pivot = pivot_week_keyword(df)
        result = top_popular_now(pivot, top_n=3)
        assert result[0] == "attention"

    def test_popular_by_pct_filters_generic(self):
        """Высокий raw count, но низкий pct — не должен побеждать."""
        ws = dt.datetime(2024, 6, 1, tzinfo=dt.timezone.utc)
        rows = [
            {"domain": "cs_lg", "week_start": ws, "keyword": "generic", "count": 1000},
            {"domain": "cs_lg", "week_start": ws, "keyword": "mamba", "count": 50},
        ]
        df = to_frame(rows)
        pivot = pivot_week_keyword(df)
        art_counts = {ws: 1000}
        result = top_popular_now(
            pivot, top_n=1,
            article_counts=art_counts,
            score_scale=1,
            max_df_pct=40.0,
            min_pct=0.0,
        )
        assert result[0] == "mamba"


class TestTopGrowingLastWindow:
    def test_empty_returns_empty(self):
        result = top_growing_last_window(pd.DataFrame(), window_weeks=4, top_n=5)
        assert result == []

    def test_returns_list(self):
        rows = _make_rows()
        df = to_frame(rows)
        pivot = pivot_week_keyword(df)
        result = top_growing_last_window(pivot, window_weeks=4, top_n=2)
        assert isinstance(result, list)
        assert len(result) <= 2

    def test_single_week_falls_back_to_popular(self):
        rows = [{"domain": "cs_lg", "week_start": dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc),
                 "keyword": "transformer", "count": 10}]
        df = to_frame(rows)
        pivot = pivot_week_keyword(df)
        result = top_growing_last_window(pivot, window_weeks=4, top_n=1)
        assert result == ["transformer"]
