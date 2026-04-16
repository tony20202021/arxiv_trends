"""Интеграционные тесты MongoStore через mongomock.

Тестирует реальную логику хранилища без поднятия MongoDB-сервера:
- идемпотентность upsert-операций
- схему индексов (уникальные ограничения)
- корректность кэширования агрегатов
- накопление счётчиков ключевых слов
"""
from __future__ import annotations
import datetime as dt
from unittest.mock import patch

import mongomock
import mongomock.collection as _mc
import pytest

# Всё через sys.path — conftest.py добавляет backend в path
from storage.mongo import MongoStore


# pymongo 4.13+ добавил параметр `sort` в UpdateOne, mongomock 4.3 его не поддерживает.
# Патчим BulkOperationBuilder.add_update чтобы игнорировать неизвестные kwargs.
_orig_add_update = _mc.BulkOperationBuilder.add_update
def _patched_add_update(self, *args, **kwargs):
    kwargs.pop("sort", None)
    return _orig_add_update(self, *args, **kwargs)
_mc.BulkOperationBuilder.add_update = _patched_add_update


@pytest.fixture()
def store():
    """MongoStore поверх mongomock — без реального MongoDB."""
    with patch("storage.mongo.MongoClient", mongomock.MongoClient):
        s = MongoStore("mongodb://localhost:27017", "test_db")
    yield s


def _ws(year: int = 2025, month: int = 1, day: int = 6) -> dt.datetime:
    return dt.datetime(year, month, day, tzinfo=dt.timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Идемпотентность upsert_article
# ─────────────────────────────────────────────────────────────────────────────

class TestUpsertArticleIdempotency:
    def _insert(self, store: MongoStore, arxiv_id: str = "2501.00001", domain: str = "cs_lg"):
        return store.upsert_article(
            arxiv_id=arxiv_id,
            domain=domain,
            week_start=_ws(),
            title="Test paper",
            published="2025-01-07T00:00:00Z",
            abstract="Deep learning rocks",
            fetched_at=dt.datetime.now(dt.timezone.utc),
        )

    def test_first_insert_returns_true(self, store):
        assert self._insert(store) is True

    def test_second_insert_returns_false(self, store):
        self._insert(store)
        assert self._insert(store) is False

    def test_second_insert_does_not_duplicate(self, store):
        self._insert(store)
        self._insert(store)
        count = store.articles.count_documents({"arxiv_id": "2501.00001", "domain": "cs_lg"})
        assert count == 1

    def test_different_domain_same_arxiv_id_allowed(self, store):
        self._insert(store, domain="cs_lg")
        result = self._insert(store, domain="stat_ml")
        assert result is True
        count = store.articles.count_documents({"arxiv_id": "2501.00001"})
        assert count == 2

    def test_article_exists_after_insert(self, store):
        self._insert(store)
        assert store.article_exists("2501.00001", "cs_lg") is True

    def test_article_exists_before_insert(self, store):
        assert store.article_exists("2501.00001", "cs_lg") is False


# ─────────────────────────────────────────────────────────────────────────────
# Счётчики ключевых слов
# ─────────────────────────────────────────────────────────────────────────────

class TestWeeklyKeywordCounts:
    def test_upsert_and_retrieve(self, store):
        ws = _ws()
        store.upsert_week_counts("cs_lg", ws, {"transformer": 3, "attention": 7})
        rows = store.get_counts_last_weeks("cs_lg", [ws])
        kws = {r["keyword"]: r["count"] for r in rows}
        assert kws["transformer"] == 3
        assert kws["attention"] == 7

    def test_upsert_accumulates_counts(self, store):
        ws = _ws()
        store.upsert_week_counts("cs_lg", ws, {"transformer": 3})
        store.upsert_week_counts("cs_lg", ws, {"transformer": 5})
        rows = store.get_counts_last_weeks("cs_lg", [ws])
        kws = {r["keyword"]: r["count"] for r in rows}
        assert kws["transformer"] == 8

    def test_empty_counts_not_stored(self, store):
        ws = _ws()
        store.upsert_week_counts("cs_lg", ws, {})
        rows = store.get_counts_last_weeks("cs_lg", [ws])
        assert rows == []

    def test_counts_isolated_by_domain(self, store):
        ws = _ws()
        store.upsert_week_counts("cs_lg", ws, {"transformer": 10})
        store.upsert_week_counts("stat_ml", ws, {"bayesian": 5})
        cs_rows = store.get_counts_last_weeks("cs_lg", [ws])
        cs_kws = {r["keyword"] for r in cs_rows}
        assert "transformer" in cs_kws
        assert "bayesian" not in cs_kws

    def test_counts_isolated_by_week(self, store):
        ws1 = _ws(2025, 1, 6)
        ws2 = _ws(2025, 1, 13)
        store.upsert_week_counts("cs_lg", ws1, {"transformer": 10})
        store.upsert_week_counts("cs_lg", ws2, {"diffusion": 4})
        rows_w1 = store.get_counts_last_weeks("cs_lg", [ws1])
        kws_w1 = {r["keyword"] for r in rows_w1}
        assert "transformer" in kws_w1
        assert "diffusion" not in kws_w1

    def test_negative_counts_subtract(self, store):
        ws = _ws()
        store.upsert_week_counts("cs_lg", ws, {"transformer": 10})
        store.upsert_week_counts("cs_lg", ws, {"transformer": -3})
        rows = store.get_counts_last_weeks("cs_lg", [ws])
        kws = {r["keyword"]: r["count"] for r in rows}
        assert kws["transformer"] == 7

    def test_get_article_counts_by_week(self, store):
        ws = _ws()
        store.upsert_article("2501.00001", "cs_lg", ws, "T", "2025-01-07", "Abstract", dt.datetime.now(dt.timezone.utc))
        store.upsert_article("2501.00002", "cs_lg", ws, "T", "2025-01-07", "Abstract", dt.datetime.now(dt.timezone.utc))
        counts = store.get_article_counts_by_week("cs_lg")
        # mongomock strips tzinfo from stored datetimes — compare naive keys too
        total = sum(v for k, v in counts.items()
                    if k.replace(tzinfo=None) == ws.replace(tzinfo=None))
        assert total == 2


# ─────────────────────────────────────────────────────────────────────────────
# Кэширование агрегатов
# ─────────────────────────────────────────────────────────────────────────────

class TestAggregatesCaching:
    def test_get_aggregated_returns_none_before_save(self, store):
        assert store.get_aggregated("cs_lg") is None

    def test_save_and_get_roundtrip(self, store):
        ts = dt.datetime(2025, 1, 15, tzinfo=dt.timezone.utc)
        store.save_aggregated("cs_lg", ts, ["transformer", "attention"], ["diffusion"], extractor_key="v1")
        agg = store.get_aggregated("cs_lg")
        assert agg is not None
        assert agg["top_popular"] == ["transformer", "attention"]
        assert agg["top_growing"] == ["diffusion"]
        assert agg["extractor_key"] == "v1"
        # mongomock strips tzinfo — compare naive timestamp
        assert agg["computed_at"].replace(tzinfo=None) == ts.replace(tzinfo=None)

    def test_save_is_idempotent(self, store):
        ts1 = dt.datetime(2025, 1, 15, tzinfo=dt.timezone.utc)
        ts2 = dt.datetime(2025, 1, 22, tzinfo=dt.timezone.utc)
        store.save_aggregated("cs_lg", ts1, ["a"], ["b"])
        store.save_aggregated("cs_lg", ts2, ["x"], ["y"])
        agg = store.get_aggregated("cs_lg")
        # mongomock strips tzinfo — compare naive timestamp
        assert agg["computed_at"].replace(tzinfo=None) == ts2.replace(tzinfo=None)
        assert agg["top_popular"] == ["x"]
        count = store.db["aggregates"].count_documents({"domain": "cs_lg"})
        assert count == 1

    def test_get_latest_article_update_none_without_updated_at(self, store):
        ws = _ws()
        store.upsert_article("2501.00001", "cs_lg", ws, "T", "2025-01-07", "Abstract",
                             dt.datetime.now(dt.timezone.utc))
        # upsert_article doesn't set updated_at — so should return None
        result = store.get_latest_article_update("cs_lg")
        assert result is None

    def test_get_latest_article_update_after_save_keywords(self, store):
        ws = _ws()
        store.upsert_article("2501.00001", "cs_lg", ws, "T", "2025-01-07", "Abstract",
                             dt.datetime.now(dt.timezone.utc))
        store.save_article_keywords("2501.00001", "cs_lg", {"transformer": 3}, extractor_version=1)
        result = store.get_latest_article_update("cs_lg")
        assert isinstance(result, dt.datetime)

    def test_aggregate_stale_when_article_updated_after_compute(self, store):
        ws = _ws()
        store.upsert_article("2501.00001", "cs_lg", ws, "T", "2025-01-07", "Abstract",
                             dt.datetime.now(dt.timezone.utc))
        # Compute aggregates at ts_compute
        ts_compute = dt.datetime(2025, 1, 10, tzinfo=dt.timezone.utc)
        store.save_aggregated("cs_lg", ts_compute, ["transformer"], [])
        # Update keywords after compute
        store.save_article_keywords("2501.00001", "cs_lg", {"transformer": 5}, extractor_version=1)
        latest = store.get_latest_article_update("cs_lg")
        agg = store.get_aggregated("cs_lg")
        # latest_update > computed_at → aggregates are stale
        assert latest > agg["computed_at"]


# ─────────────────────────────────────────────────────────────────────────────
# Extraction-запросы
# ─────────────────────────────────────────────────────────────────────────────

class TestArticlesForExtraction:
    def _insert(self, store, arxiv_id: str, domain: str = "cs_lg",
                keywords=None, extractor_version=None):
        ws = _ws()
        store.upsert_article(arxiv_id, domain, ws, "T", "2025-01-07", "Abstract",
                             dt.datetime.now(dt.timezone.utc))
        if keywords is not None:
            store.save_article_keywords(arxiv_id, domain, keywords, extractor_version or 1)

    def test_count_unprocessed_articles(self, store):
        self._insert(store, "2501.00001")  # no keywords → needs extraction
        self._insert(store, "2501.00002", keywords={"x": 1}, extractor_version=2)
        count = store.count_articles_for_extraction("cs_lg", [_ws()], extractor_version=2)
        assert count == 1  # only 2501.00001

    def test_count_articles_with_old_version(self, store):
        self._insert(store, "2501.00001", keywords={"x": 1}, extractor_version=1)
        self._insert(store, "2501.00002", keywords={"y": 2}, extractor_version=2)
        # extractor_version=2 → version < 2 → only 2501.00001 is stale
        count = store.count_articles_for_extraction("cs_lg", [_ws()], extractor_version=2)
        assert count == 1

    def test_get_articles_returns_expected_fields(self, store):
        self._insert(store, "2501.00001")
        articles = store.get_articles_for_extraction("cs_lg", [_ws()], extractor_version=2, batch_size=10)
        assert len(articles) == 1
        art = articles[0]
        assert art["arxiv_id"] == "2501.00001"
        assert "abstract" in art
        assert "week_start" in art


# ─────────────────────────────────────────────────────────────────────────────
# Удаление данных
# ─────────────────────────────────────────────────────────────────────────────

class TestClearWeekCounts:
    def test_clear_removes_counts_for_week(self, store):
        ws = _ws()
        store.upsert_week_counts("cs_lg", ws, {"transformer": 5})
        store.clear_week_counts("cs_lg", [ws])
        rows = store.get_counts_last_weeks("cs_lg", [ws])
        assert rows == []

    def test_clear_only_affects_specified_domain(self, store):
        ws = _ws()
        store.upsert_week_counts("cs_lg", ws, {"transformer": 5})
        store.upsert_week_counts("stat_ml", ws, {"bayesian": 3})
        store.clear_week_counts("cs_lg", [ws])
        rows = store.get_counts_last_weeks("stat_ml", [ws])
        assert len(rows) > 0

    def test_clear_only_affects_specified_weeks(self, store):
        ws1 = _ws(2025, 1, 6)
        ws2 = _ws(2025, 1, 13)
        store.upsert_week_counts("cs_lg", ws1, {"transformer": 5})
        store.upsert_week_counts("cs_lg", ws2, {"diffusion": 3})
        store.clear_week_counts("cs_lg", [ws1])
        rows = store.get_counts_last_weeks("cs_lg", [ws2])
        assert len(rows) > 0
