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
        assert len(plots) == 3

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


# ──────────────────────────────────────────────────────────────────────────────
# recompute_aggregates (Сервис 3)
# ──────────────────────────────────────────────────────────────────────────────

class TestRecomputePlots:
    _WS1 = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
    _WS2 = dt.datetime(2024, 1, 8, tzinfo=dt.timezone.utc)
    _OLD = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)   # старый computed_at
    _NEW = dt.datetime(2024, 1, 9, tzinfo=dt.timezone.utc)   # свежий updated_at

    def _make_rows(self, domain="cs_lg"):
        return [
            {"domain": domain, "week_start": self._WS1, "keyword": "transformer", "count": 10},
            {"domain": domain, "week_start": self._WS1, "keyword": "diffusion",   "count": 5},
            {"domain": domain, "week_start": self._WS2, "keyword": "transformer", "count": 15},
            {"domain": domain, "week_start": self._WS2, "keyword": "diffusion",   "count": 8},
        ]

    def _make_store(self, *, latest_update=None, computed_at=None, week_datetimes=None, rows=None):
        store = MagicMock()
        store.get_latest_article_update.return_value = latest_update
        store.get_aggregated.return_value = (
            {"computed_at": computed_at, "top_popular": ["transformer"], "top_growing": ["diffusion"]}
            if computed_at else None
        )
        store.col.distinct.return_value = week_datetimes or []
        store.get_counts_last_weeks.return_value = rows or []
        store.get_article_counts_by_week.return_value = {}
        store.get_all_week_starts.return_value = week_datetimes or []
        store.get_counts_all_domains.return_value = rows or []
        return store

    def _run(self, domains, store, force=False):
        with patch("pipeline.MongoStore", return_value=store), \
             patch("pipeline.plot_keywords_over_time"):
            from pipeline import recompute_aggregates
            return recompute_aggregates(
                domains=domains,
                mongo_uri="mongodb://localhost",
                mongo_db="test_db",
                force=force,
            ), store

    # --- базовые ---

    def test_returns_stats_per_domain(self):
        store = self._make_store(
            latest_update=self._NEW, computed_at=self._OLD,
            week_datetimes=[self._WS1, self._WS2], rows=self._make_rows(),
        )
        results, _ = self._run([_make_domain()], store)
        assert "cs_lg" in results
        assert results["cs_lg"]["weeks"] == 2
        assert "_all" in results

    def test_saves_all_aggregated(self):
        store = self._make_store(
            latest_update=self._NEW, computed_at=self._OLD,
            week_datetimes=[self._WS1, self._WS2], rows=self._make_rows(),
        )
        _, store = self._run([_make_domain()], store)
        domains_saved = [c[1]["domain"] for c in store.save_aggregated.call_args_list]
        assert "_all" in domains_saved

    def test_saves_aggregated(self):
        store = self._make_store(
            latest_update=self._NEW, computed_at=self._OLD,
            week_datetimes=[self._WS1, self._WS2], rows=self._make_rows(),
        )
        _, store = self._run([_make_domain()], store)
        # вызывается дважды: для домена + для _all
        assert store.save_aggregated.call_count == 2
        domains_saved = [c[1]["domain"] for c in store.save_aggregated.call_args_list]
        assert "cs_lg" in domains_saved
        assert "_all" in domains_saved

    def test_no_data_returns_zero_weeks(self):
        store = self._make_store(latest_update=self._NEW, computed_at=self._OLD)
        results, store = self._run([_make_domain()], store)
        assert results["cs_lg"]["weeks"] == 0
        store.save_aggregated.assert_not_called()

    def test_multiple_domains_processed_independently(self):
        domains = [_make_domain("cs_lg"), _make_domain("stat_ml")]
        store = self._make_store(
            latest_update=self._NEW, computed_at=self._OLD,
            week_datetimes=[self._WS1], rows=self._make_rows(),
        )
        results, store = self._run(domains, store)
        assert "cs_lg" in results and "stat_ml" in results
        # 2 домена + _all
        assert store.save_aggregated.call_count == 3

    # --- проверка актуальности ---

    def test_skips_domain_when_aggregates_are_fresh(self):
        # computed_at >= updated_at → пропуск
        store = self._make_store(latest_update=self._OLD, computed_at=self._NEW)
        results, store = self._run([_make_domain()], store)
        assert results["cs_lg"]["skipped"] is True
        store.save_aggregated.assert_not_called()
        store.col.distinct.assert_not_called()

    def test_recomputes_when_articles_are_newer(self):
        # updated_at > computed_at → пересчёт
        store = self._make_store(
            latest_update=self._NEW, computed_at=self._OLD,
            week_datetimes=[self._WS1], rows=self._make_rows(),
        )
        results, store = self._run([_make_domain()], store)
        assert results["cs_lg"].get("skipped") is False
        domains_saved = [c[1]["domain"] for c in store.save_aggregated.call_args_list]
        assert "cs_lg" in domains_saved

    def test_recomputes_when_no_aggregates_yet(self):
        # агрегатов нет совсем → пересчёт
        store = self._make_store(
            latest_update=self._NEW, computed_at=None,
            week_datetimes=[self._WS1], rows=self._make_rows(),
        )
        results, store = self._run([_make_domain()], store)
        assert results["cs_lg"].get("skipped") is False
        domains_saved = [c[1]["domain"] for c in store.save_aggregated.call_args_list]
        assert "cs_lg" in domains_saved

    def test_recomputes_when_no_updated_at(self):
        # updated_at нет → агрегаты считаются устаревшими → пересчёт
        store = self._make_store(
            latest_update=None, computed_at=self._NEW,
            week_datetimes=[self._WS1], rows=self._make_rows(),
        )
        results, store = self._run([_make_domain()], store)
        assert results["cs_lg"].get("skipped") is False
        domains_saved = [c[1]["domain"] for c in store.save_aggregated.call_args_list]
        assert "cs_lg" in domains_saved

    def test_force_bypasses_freshness_check(self):
        # force=True → пересчитывает даже если aggregates свежее
        store = self._make_store(
            latest_update=self._OLD, computed_at=self._NEW,
            week_datetimes=[self._WS1], rows=self._make_rows(),
        )
        results, store = self._run([_make_domain()], store, force=True)
        assert results["cs_lg"].get("skipped") is False
        domains_saved = [c[1]["domain"] for c in store.save_aggregated.call_args_list]
        assert "cs_lg" in domains_saved
        # при force — get_latest_article_update не должен вызываться
        store.get_latest_article_update.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# render_plots (Сервис 4)
# ──────────────────────────────────────────────────────────────────────────────

class TestRenderPlots:
    _WS1 = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
    _WS2 = dt.datetime(2024, 1, 8, tzinfo=dt.timezone.utc)

    def _make_rows(self, domain="cs_lg"):
        return [
            {"domain": domain, "week_start": self._WS1, "keyword": "transformer", "count": 10},
            {"domain": domain, "week_start": self._WS2, "keyword": "transformer", "count": 15},
        ]

    def _make_store(self, *, agg=None, week_datetimes=None, rows=None):
        store = MagicMock()
        store.get_aggregated.return_value = agg
        store.col.distinct.return_value = week_datetimes or []
        store.get_counts_last_weeks.return_value = rows or []
        store.get_article_counts_by_week.return_value = {}
        store.get_all_week_starts.return_value = week_datetimes or []
        store.get_counts_all_domains.return_value = rows or []
        store.get_article_counts_all_domains.return_value = {}
        return store

    def _run(self, domains, store, tmp_path):
        with patch("pipeline.MongoStore", return_value=store), \
             patch("pipeline.plot_keywords_over_time"), \
             patch("pipeline.plot_article_counts"):
            from pipeline import render_plots
            return render_plots(
                domains=domains,
                mongo_uri="mongodb://localhost",
                mongo_db="test_db",
                out_dir=str(tmp_path),
            ), store

    def test_skips_domain_without_aggregates(self, tmp_path):
        store = self._make_store(agg=None)
        results, store = self._run([_make_domain()], store, tmp_path)
        assert results["cs_lg"]["skipped"] is True
        store.get_counts_last_weeks.assert_not_called()

    def test_skips_domain_without_keyword_counts(self, tmp_path):
        store = self._make_store(
            agg={"top_popular": ["transformer"], "top_growing": ["diffusion"]},
            week_datetimes=[],
        )
        results, store = self._run([_make_domain()], store, tmp_path)
        assert results["cs_lg"]["skipped"] is True

    def test_returns_plot_count(self, tmp_path):
        store = self._make_store(
            agg={"top_popular": ["transformer"], "top_growing": ["diffusion"]},
            week_datetimes=[self._WS1, self._WS2],
            rows=self._make_rows(),
        )
        results, _ = self._run([_make_domain()], store, tmp_path)
        assert results["cs_lg"]["plots"] == 3

    def test_renders_all_domains_summary(self, tmp_path):
        store = self._make_store(
            agg={"top_popular": ["transformer"], "top_growing": ["diffusion"]},
            week_datetimes=[self._WS1],
            rows=self._make_rows(),
        )
        results, _ = self._run([_make_domain()], store, tmp_path)
        assert "_all" in results
        assert results["_all"]["plots"] == 3

    def test_does_not_call_save_aggregated(self, tmp_path):
        store = self._make_store(
            agg={"top_popular": ["transformer"], "top_growing": ["diffusion"]},
            week_datetimes=[self._WS1],
            rows=self._make_rows(),
        )
        _, store = self._run([_make_domain()], store, tmp_path)
        store.save_aggregated.assert_not_called()

    def test_multiple_domains(self, tmp_path):
        domains = [_make_domain("cs_lg"), _make_domain("stat_ml")]
        store = self._make_store(
            agg={"top_popular": ["transformer"], "top_growing": ["diffusion"]},
            week_datetimes=[self._WS1],
            rows=self._make_rows(),
        )
        results, _ = self._run(domains, store, tmp_path)
        assert "cs_lg" in results and "stat_ml" in results


# ──────────────────────────────────────────────────────────────────────────────
# fetch_abstracts (Сервис 1)
# ──────────────────────────────────────────────────────────────────────────────

def _make_entry(arxiv_id: str, published: str = "2024-01-03T00:00:00Z", abstract: str = "deep learning transformer model") -> dict:
    return {"id": f"http://arxiv.org/abs/{arxiv_id}v1", "published": published, "abstract": abstract}


class TestFetchAbstracts:
    _WEEK_FROM = dt.date(2024, 1, 1)
    _WEEK_TO   = dt.date(2024, 1, 7)

    def _run(self, entries=None, article_exists=False):
        store = MagicMock()
        store.article_exists.return_value = article_exists
        store.upsert_article.return_value = True

        api = MagicMock()
        api.query.return_value = MagicMock()
        api.parse_entries.side_effect = [entries or [], []]  # second call → stop pagination

        with patch("pipeline.MongoStore", return_value=store), \
             patch("pipeline.ArxivApiClient", return_value=api):
            from pipeline import fetch_abstracts
            stats = fetch_abstracts(
                domains=[_make_domain()],
                week_from=self._WEEK_FROM,
                week_to=self._WEEK_TO,
                mongo_uri="mongodb://localhost",
                mongo_db="test_db",
                api_url="http://export.arxiv.org/api/query",
                user_agent="test/1.0",
            )
        return stats, store, api

    def test_returns_stats_dict(self):
        stats, *_ = self._run(entries=[_make_entry("2401.00001")])
        assert "cs_lg" in stats
        s = stats["cs_lg"]
        assert "fetched" in s and "new" in s and "skipped" in s and "truncated" in s

    def test_new_article_saved(self):
        stats, store, *_ = self._run(entries=[_make_entry("2401.00001")])
        store.upsert_article.assert_called_once()
        assert stats["cs_lg"]["new"] == 1

    def test_existing_article_skipped(self):
        stats, store, *_ = self._run(entries=[_make_entry("2401.00001")], article_exists=True)
        store.upsert_article.assert_not_called()
        assert stats["cs_lg"]["skipped"] == 1

    def test_empty_abstract_skips_article(self):
        stats, store, *_ = self._run(entries=[_make_entry("2401.00001", abstract="")])
        store.upsert_article.assert_not_called()
        assert stats["cs_lg"]["skipped"] == 1

    def test_pagination_stops_on_empty_batch(self):
        stats, store, api = self._run(entries=[_make_entry("2401.00001")])
        assert api.query.called

    def test_entry_without_id_skipped(self):
        stats, store, *_ = self._run(entries=[{"id": "", "published": "2024-01-03T00:00:00Z", "abstract": "text"}])
        store.upsert_article.assert_not_called()
        assert stats["cs_lg"]["skipped"] == 1

    def test_article_domain_stored(self):
        stats, store, *_ = self._run(entries=[_make_entry("2401.00001")])
        call_kwargs = store.upsert_article.call_args[1]
        assert call_kwargs["domain"] == "cs_lg"


# ──────────────────────────────────────────────────────────────────────────────
# extract_keywords_batch (Сервис 2)
# ──────────────────────────────────────────────────────────────────────────────

class TestExtractKeywordsBatch:
    _WEEK_FROM = dt.date(2024, 1, 1)
    _WEEK_TO   = dt.date(2024, 1, 7)

    _WS_DT = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)

    def _run(self, articles_batches):
        store = MagicMock()
        # count called once per round + final 0 to stop; each batch is one round
        counts = [len(b) for b in articles_batches] + [0]
        store.count_articles_for_extraction.side_effect = counts
        # get_articles_for_extraction yields each batch then empty list per round
        store.get_articles_for_extraction.side_effect = [b for b in articles_batches] + [[]]

        with patch("pipeline.MongoStore", return_value=store):
            from pipeline import extract_keywords_batch
            stats = extract_keywords_batch(
                domains=[_make_domain()],
                week_from=self._WEEK_FROM,
                week_to=self._WEEK_TO,
                mongo_uri="mongodb://localhost",
                mongo_db="test_db",
            )
        return stats, store

    def _make_article(self, arxiv_id, abstract="deep learning transformer", keywords=None, version=None):
        return {
            "arxiv_id": arxiv_id,
            "abstract": abstract,
            "week_start": self._WS_DT,
            "keywords": keywords,
            "keyword_extractor_version": version,
        }

    def test_returns_stats_dict(self):
        stats, _ = self._run([[self._make_article("2401.00001")]])
        assert "cs_lg" in stats
        assert "processed" in stats["cs_lg"]

    def test_saves_keywords_for_new_article(self):
        stats, store = self._run([[self._make_article("2401.00001")]])
        store.save_article_keywords.assert_called_once()
        assert stats["cs_lg"]["processed"] == 1

    def test_adds_keyword_counts(self):
        stats, store = self._run([[self._make_article("2401.00001")]])
        # upsert_week_counts called once for adding new keywords (no old version to subtract)
        assert store.upsert_week_counts.call_count == 1

    def test_subtracts_old_counts_on_version_upgrade(self):
        old_kws = {"old_term": 3}
        art = self._make_article("2401.00001", keywords=old_kws, version=0)
        stats, store = self._run([[art]])
        # upsert called twice: subtract old, add new
        assert store.upsert_week_counts.call_count == 2
        # first call subtracts (negative values)
        first_counts = store.upsert_week_counts.call_args_list[0][0][2]
        assert all(v < 0 for v in first_counts.values())

    def test_skips_article_without_abstract(self):
        art = self._make_article("2401.00001", abstract="")
        stats, store = self._run([[art]])
        store.save_article_keywords.assert_not_called()
        assert stats["cs_lg"]["skipped"] == 1

    def test_processes_multiple_articles(self):
        articles = [self._make_article(f"2401.0000{i}") for i in range(3)]
        stats, store = self._run([articles])
        assert stats["cs_lg"]["processed"] == 3


# ──────────────────────────────────────────────────────────────────────────────
# _date_ranges_for_period
# ──────────────────────────────────────────────────────────────────────────────

class TestDateRangesForPeriod:
    def test_single_week(self):
        from pipeline import _date_ranges_for_period
        result = _date_ranges_for_period(dt.date(2024, 1, 1), dt.date(2024, 1, 7))
        assert len(result) == 1
        assert result[0] == (dt.date(2024, 1, 1), dt.date(2024, 1, 7))

    def test_two_full_weeks(self):
        from pipeline import _date_ranges_for_period
        result = _date_ranges_for_period(dt.date(2024, 1, 1), dt.date(2024, 1, 14))
        assert len(result) == 2
        assert result[0] == (dt.date(2024, 1, 1), dt.date(2024, 1, 7))
        assert result[1] == (dt.date(2024, 1, 8), dt.date(2024, 1, 14))

    def test_partial_last_week_clipped_to_end(self):
        from pipeline import _date_ranges_for_period
        result = _date_ranges_for_period(dt.date(2024, 1, 1), dt.date(2024, 1, 10))
        assert len(result) == 2
        assert result[-1][1] == dt.date(2024, 1, 10)  # конец обрезан

    def test_single_day(self):
        from pipeline import _date_ranges_for_period
        d = dt.date(2024, 1, 3)
        result = _date_ranges_for_period(d, d)
        assert len(result) == 1
        assert result[0] == (d, d)

    def test_ranges_are_contiguous(self):
        from pipeline import _date_ranges_for_period
        result = _date_ranges_for_period(dt.date(2024, 1, 1), dt.date(2024, 3, 31))
        for i in range(len(result) - 1):
            _, end = result[i]
            start, _ = result[i + 1]
            import datetime as _dt
            assert start == end + _dt.timedelta(days=1)


# ──────────────────────────────────────────────────────────────────────────────
# date_from фильтрация в recompute_aggregates / render_plots
# ──────────────────────────────────────────────────────────────────────────────

class TestDateFromFiltering:
    _WS_OLD = dt.datetime(2023, 6, 1)   # старая неделя — без timezone (как в MongoDB)
    _WS_NEW = dt.datetime(2024, 1, 1)   # новая неделя

    def _make_store(self, week_datetimes):
        store = MagicMock()
        store.get_latest_article_update.return_value = dt.datetime(2024, 2, 1, tzinfo=dt.timezone.utc)
        store.get_aggregated.return_value = {
            "computed_at": dt.datetime(2023, 1, 1, tzinfo=dt.timezone.utc),
            "top_popular": ["transformer"],
            "top_growing": ["diffusion"],
            "extractor_key": "1_count_stopwords",
        }
        store.col.distinct.return_value = week_datetimes
        store.get_counts_last_weeks.return_value = []
        store.get_all_week_starts.return_value = week_datetimes
        store.get_counts_all_domains.return_value = []
        store.get_article_counts_by_week.return_value = {}
        store.get_article_counts_all_domains.return_value = {}
        return store

    def test_recompute_aggregates_filters_old_weeks(self):
        store = self._make_store([self._WS_OLD, self._WS_NEW])
        cutoff = dt.date(2024, 1, 1)

        with patch("pipeline.MongoStore", return_value=store):
            from pipeline import recompute_aggregates
            results = recompute_aggregates(
                domains=[_make_domain()],
                mongo_uri="mongodb://localhost",
                mongo_db="test_db",
                date_from=cutoff,
            )
        # Только _WS_NEW должна пройти фильтр → 1 неделя
        assert results["cs_lg"]["weeks"] == 1

    def test_recompute_aggregates_no_date_from_uses_all_weeks(self):
        store = self._make_store([self._WS_OLD, self._WS_NEW])

        with patch("pipeline.MongoStore", return_value=store):
            from pipeline import recompute_aggregates
            results = recompute_aggregates(
                domains=[_make_domain()],
                mongo_uri="mongodb://localhost",
                mongo_db="test_db",
            )
        assert results["cs_lg"]["weeks"] == 2

    def test_render_plots_filters_old_weeks(self, tmp_path):
        store = self._make_store([self._WS_OLD, self._WS_NEW])
        cutoff = dt.date(2024, 1, 1)

        with patch("pipeline.MongoStore", return_value=store), \
             patch("pipeline.plot_keywords_over_time"), \
             patch("pipeline.plot_article_counts"):
            from pipeline import render_plots
            render_plots(
                domains=[_make_domain()],
                mongo_uri="mongodb://localhost",
                mongo_db="test_db",
                out_dir=str(tmp_path),
                date_from=cutoff,
            )
        # get_counts_last_weeks должен получить только одну неделю (_WS_NEW)
        call_args = store.get_counts_last_weeks.call_args
        weeks_passed = call_args[0][1]  # второй позиционный аргумент
        assert self._WS_OLD not in weeks_passed
        assert self._WS_NEW in weeks_passed
