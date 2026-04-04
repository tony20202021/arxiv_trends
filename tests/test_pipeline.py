from __future__ import annotations
import datetime as dt
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pandas as pd
import pytest

# --- helpers ---

def _make_domain(domain_id: str = "cs_lg") -> dict:
    return {
        "domain": domain_id,
        "title": "CS Machine Learning",
        "arxiv_search_query": f"cat:{domain_id.replace('_', '.')}",
    }


def _make_store() -> MagicMock:
    store = MagicMock()
    store.get_counts_last_weeks.return_value = []
    return store


def _make_api(entries=None) -> MagicMock:
    api = MagicMock()
    feed = MagicMock()
    api.query.return_value = feed
    api.parse_entries.return_value = entries or []
    return api


def _make_fetcher(abstract: str = "deep learning transformer model") -> MagicMock:
    fetcher = MagicMock()
    fetcher.fetch_abs_html.return_value = "<html></html>"
    fetcher.extract_abstract.return_value = abstract
    return fetcher


# --- tests ---

class TestRunForDomain:
    def test_calls_api_query(self, tmp_path):
        from pipeline import run_for_domain
        store = _make_store()
        api = _make_api()
        fetcher = _make_fetcher()
        run_for_domain(_make_domain(), store, api, fetcher, out_dir=str(tmp_path))
        api.query.assert_called()

    def test_writes_to_mongo(self, tmp_path):
        from pipeline import run_for_domain
        store = _make_store()
        api = _make_api()
        fetcher = _make_fetcher()
        run_for_domain(_make_domain(), store, api, fetcher, out_dir=str(tmp_path))
        store.upsert_week_counts.assert_called()

    def test_saves_aggregated(self, tmp_path):
        from pipeline import run_for_domain
        store = _make_store()
        api = _make_api()
        fetcher = _make_fetcher()
        run_for_domain(_make_domain(), store, api, fetcher, out_dir=str(tmp_path))
        store.save_aggregated.assert_called_once()
        args = store.save_aggregated.call_args[1]
        assert args["domain"] == "cs_lg"

    def test_creates_plot_files(self, tmp_path):
        from pipeline import run_for_domain

        ws = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
        rows = [{"domain": "cs_lg", "week_start": ws, "keyword": "transformer", "count": 10}]
        store = _make_store()
        store.get_counts_last_weeks.return_value = rows

        entry = {"id": "http://arxiv.org/abs/2401.00001v1", "published": "2024-01-03T00:00:00Z"}
        api = _make_api(entries=[entry])
        fetcher = _make_fetcher()

        run_for_domain(_make_domain(), store, api, fetcher, out_dir=str(tmp_path))

        plots = list(tmp_path.glob("plots/**/*.png"))
        assert len(plots) == 2

    def test_skips_entry_without_id(self, tmp_path):
        from pipeline import run_for_domain
        store = _make_store()
        api = _make_api(entries=[{"id": "", "published": "2024-01-01T00:00:00Z"}])
        fetcher = _make_fetcher()
        # не должно падать
        run_for_domain(_make_domain(), store, api, fetcher, out_dir=str(tmp_path))
        fetcher.fetch_abs_html.assert_not_called()

    def test_fetch_failure_skips_entry(self, tmp_path):
        from pipeline import run_for_domain
        import requests
        store = _make_store()
        api = _make_api(entries=[{"id": "http://arxiv.org/abs/2401.00001v1", "published": "2024-01-01T00:00:00Z"}])
        fetcher = _make_fetcher()
        fetcher.fetch_abs_html.side_effect = requests.ConnectionError("timeout")
        # не должно падать, pipeline продолжает
        run_for_domain(_make_domain(), store, api, fetcher, out_dir=str(tmp_path))
        store.upsert_week_counts.assert_called()

    def test_uses_provided_today(self, tmp_path):
        from pipeline import run_for_domain
        store = _make_store()
        api = _make_api()
        fetcher = _make_fetcher()
        today = dt.date(2023, 6, 15)
        run_for_domain(_make_domain(), store, api, fetcher, out_dir=str(tmp_path), today=today)
        # query должен быть вызван с датами из 2023
        url_args = api.query.call_args[1]
        lo, hi = url_args["submitted_date_range"]
        assert lo.startswith("2022") or lo.startswith("2023")  # 52 недели назад от 2023-06-15


class TestRunAll:
    def test_creates_output_dir(self, tmp_path):
        from pipeline import run_all
        out = tmp_path / "new_outputs"
        with patch("pipeline.MongoStore"), \
             patch("pipeline.ArxivApiClient"), \
             patch("pipeline.ArxivHtmlFetcher"), \
             patch("pipeline.run_for_domain"):
            run_all([], "mongodb://localhost", "db", "http://api", "agent", str(out))
        assert out.exists()

    def test_calls_run_for_domain_for_each(self, tmp_path):
        from pipeline import run_all
        domains = [_make_domain("cs_lg"), _make_domain("stat_ml")]
        with patch("pipeline.MongoStore"), \
             patch("pipeline.ArxivApiClient"), \
             patch("pipeline.ArxivHtmlFetcher"), \
             patch("pipeline.run_for_domain") as mock_rfd:
            run_all(domains, "mongodb://localhost", "db", "http://api", "agent", str(tmp_path))
        assert mock_rfd.call_count == 2

    def test_domain_exception_does_not_stop_others(self, tmp_path):
        from pipeline import run_all
        domains = [_make_domain("cs_lg"), _make_domain("stat_ml")]
        call_count = 0

        def _rfd_side_effect(domain, *a, **kw):
            nonlocal call_count
            call_count += 1
            if domain["domain"] == "cs_lg":
                raise RuntimeError("domain failed")

        with patch("pipeline.MongoStore"), \
             patch("pipeline.ArxivApiClient"), \
             patch("pipeline.ArxivHtmlFetcher"), \
             patch("pipeline.run_for_domain", side_effect=_rfd_side_effect):
            run_all(domains, "mongodb://localhost", "db", "http://api", "agent", str(tmp_path))

        assert call_count == 2  # оба домена попытались выполниться
