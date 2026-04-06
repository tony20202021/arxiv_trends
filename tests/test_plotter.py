from __future__ import annotations
import datetime as dt
from pathlib import Path

import pandas as pd
import pytest

from plots.plotter import plot_keywords_over_time, plot_article_counts, build_keyword_styles


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

    def test_keyword_styles_accepted(self, tmp_path):
        pivot = _make_pivot()
        out = tmp_path / "styled.png"
        styles = build_keyword_styles(["transformer", "diffusion"])
        # не должно падать
        plot_keywords_over_time(pivot, ["transformer", "diffusion"], "Styled", out, keyword_styles=styles)
        assert out.exists()


class TestPlotArticleCounts:
    def _make_counts(self, weeks=4) -> dict:
        import datetime as dt
        base = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
        return {base + dt.timedelta(weeks=i): (i + 1) * 10 for i in range(weeks)}

    def test_creates_output_file(self, tmp_path):
        out = tmp_path / "articles.png"
        plot_article_counts(self._make_counts(), "Articles per week", out)
        assert out.exists()
        assert out.stat().st_size > 0

    def test_creates_parent_dirs(self, tmp_path):
        out = tmp_path / "a" / "b" / "articles.png"
        plot_article_counts(self._make_counts(), "Title", out)
        assert out.exists()

    def test_empty_counts_creates_no_data_file(self, tmp_path):
        out = tmp_path / "empty.png"
        plot_article_counts({}, "Empty", out)
        assert out.exists()
        assert out.stat().st_size > 0

    def test_truncates_to_history_weeks(self, tmp_path):
        from config.constants import HISTORY_WEEKS
        out = tmp_path / "long.png"
        plot_article_counts(self._make_counts(weeks=HISTORY_WEEKS + 5), "Long", out)
        assert out.exists()


class TestBuildKeywordStyles:
    def test_returns_dict_with_all_keywords(self):
        kws = ["transformer", "diffusion", "attention"]
        styles = build_keyword_styles(kws)
        assert set(styles.keys()) == set(kws)

    def test_each_value_is_color_and_marker_tuple(self):
        styles = build_keyword_styles(["transformer", "diffusion"])
        for kw, (color, marker) in styles.items():
            assert isinstance(color, str) and color.startswith("#")
            assert isinstance(marker, str)

    def test_shared_keyword_gets_same_style_in_both_lists(self):
        popular = ["transformer", "diffusion", "attention"]
        growing = ["diffusion", "robot", "vision"]
        # объединение в том порядке в котором их передаст pipeline
        all_kws = list(dict.fromkeys(popular + growing))
        styles = build_keyword_styles(all_kws)

        # "diffusion" есть в обоих списках — стиль должен быть один
        assert "diffusion" in styles
        color_pop, marker_pop = styles["diffusion"]
        color_grw, marker_grw = styles["diffusion"]
        assert color_pop == color_grw
        assert marker_pop == marker_grw

    def test_different_keywords_get_different_colors(self):
        styles = build_keyword_styles(["a", "b", "c", "d"])
        colors = [c for c, _ in styles.values()]
        # все 4 слова в пределах одной палитры — цвета не повторятся (палитра >= 10 цветов)
        assert len(set(colors)) == 4

    def test_empty_list_returns_empty_dict(self):
        assert build_keyword_styles([]) == {}

    def test_single_keyword(self):
        styles = build_keyword_styles(["transformer"])
        assert "transformer" in styles
        color, marker = styles["transformer"]
        assert color and marker
