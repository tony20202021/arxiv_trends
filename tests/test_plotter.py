from __future__ import annotations
import datetime as dt
from pathlib import Path

import pandas as pd
import pytest

from plots.plotter import plot_keywords_over_time


def _make_pivot(weeks: int = 4) -> pd.DataFrame:
    base = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
    index = pd.date_range(start=base, periods=weeks, freq="W-MON", tz="UTC")
    import numpy as np
    data = {
        "transformer": np.arange(weeks) + 10,
        "diffusion": np.arange(weeks) + 5,
        "attention": np.arange(weeks) + 8,
    }
    return pd.DataFrame(data, index=index)


class TestPlotKeywordsOverTime:
    def test_creates_output_file(self, tmp_path):
        pivot = _make_pivot()
        out = tmp_path / "plots" / "test_domain" / "top_popular.png"
        plot_keywords_over_time(pivot, ["transformer", "diffusion"], "Test title", out)
        assert out.exists()
        assert out.stat().st_size > 0

    def test_creates_parent_dirs(self, tmp_path):
        pivot = _make_pivot()
        out = tmp_path / "a" / "b" / "c" / "chart.png"
        plot_keywords_over_time(pivot, ["transformer"], "Title", out)
        assert out.exists()

    def test_empty_pivot_creates_no_data_file(self, tmp_path):
        out = tmp_path / "empty.png"
        plot_keywords_over_time(pd.DataFrame(), [], "Empty", out)
        assert out.exists()
        assert out.stat().st_size > 0

    def test_empty_keywords_creates_no_data_file(self, tmp_path):
        pivot = _make_pivot()
        out = tmp_path / "empty_kw.png"
        plot_keywords_over_time(pivot, [], "No keywords", out)
        assert out.exists()

    def test_missing_keyword_in_pivot_skipped(self, tmp_path):
        pivot = _make_pivot()
        out = tmp_path / "missing.png"
        # keyword "nonexistent" не в pivot — не должно падать
        plot_keywords_over_time(pivot, ["transformer", "nonexistent"], "Title", out)
        assert out.exists()

    def test_pivot_truncated_to_history_weeks(self, tmp_path):
        # создаём pivot шире HISTORY_WEEKS — должно обрезаться без ошибок
        from config.constants import HISTORY_WEEKS
        pivot = _make_pivot(weeks=HISTORY_WEEKS + 5)
        out = tmp_path / "long.png"
        plot_keywords_over_time(pivot, ["transformer"], "Long", out)
        assert out.exists()
