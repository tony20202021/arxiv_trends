from __future__ import annotations
import datetime as dt
from unittest.mock import MagicMock, patch

import pytest

# Collections returned by db["<name>"]
_mock_client = MagicMock()
_mock_db = MagicMock()
_mock_col = MagicMock()          # weekly_keyword_counts
_mock_processed = MagicMock()    # processed_articles
_mock_articles = MagicMock()     # articles
_mock_agg_col = MagicMock()      # aggregates

_COLLECTION_MAP = {
    "weekly_keyword_counts": _mock_col,
    "processed_articles": _mock_processed,
    "articles": _mock_articles,
    "aggregates": _mock_agg_col,
}

_mock_client.__getitem__ = MagicMock(return_value=_mock_db)
_mock_db.__getitem__ = MagicMock(side_effect=lambda name: _COLLECTION_MAP.get(name, MagicMock()))


def _make_store():
    with patch("storage.mongo.MongoClient", return_value=_mock_client):
        from storage.mongo import MongoStore
        store = MongoStore("mongodb://localhost:27017", "test_db")
    return store


@pytest.fixture(autouse=True)
def reset_mocks():
    _mock_col.reset_mock()
    _mock_processed.reset_mock()
    _mock_articles.reset_mock()
    _mock_agg_col.reset_mock()
    yield


# ──────────────────────────────────────────────────────────────────────────────
# weekly_keyword_counts
# ──────────────────────────────────────────────────────────────────────────────

class TestMongoStoreUpsertWeekCounts:
    def test_calls_bulk_write(self):
        store = _make_store()
        ws = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
        store.upsert_week_counts("cs_lg", ws, {"transformer": 5, "attention": 3})
        _mock_col.bulk_write.assert_called_once()

    def test_empty_counts_skips_bulk_write(self):
        store = _make_store()
        ws = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
        store.upsert_week_counts("cs_lg", ws, {})
        _mock_col.bulk_write.assert_not_called()

    def test_bulk_write_count_matches_keywords(self):
        store = _make_store()
        ws = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
        counts = {"a": 1, "b": 2, "c": 3}
        store.upsert_week_counts("cs_lg", ws, counts)
        ops = _mock_col.bulk_write.call_args[0][0]
        assert len(ops) == 3


class TestMongoStoreGetCountsLastWeeks:
    def test_calls_find_with_domain_and_range(self):
        store = _make_store()
        w1 = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
        w2 = dt.datetime(2024, 1, 8, tzinfo=dt.timezone.utc)
        _mock_col.find.return_value = iter([])
        store.get_counts_last_weeks("cs_lg", [w1, w2])
        query = _mock_col.find.call_args[0][0]
        assert query["domain"] == "cs_lg"
        assert query["week_start"]["$gte"] == w1
        assert query["week_start"]["$lte"] == w2

    def test_returns_list(self):
        store = _make_store()
        rows = [{"domain": "cs_lg", "week_start": dt.datetime(2024, 1, 1), "keyword": "x", "count": 1}]
        _mock_col.find.return_value = iter(rows)
        result = store.get_counts_last_weeks("cs_lg", [dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)])
        assert isinstance(result, list)


class TestMongoStoreGetAllDomains:
    def test_calls_distinct(self):
        store = _make_store()
        _mock_col.distinct.return_value = ["cs_lg", "stat_ml"]
        result = store.get_all_domains()
        _mock_col.distinct.assert_called_with("domain")
        assert result == ["cs_lg", "stat_ml"]


class TestMongoStoreGetTopKeywords:
    def test_calls_aggregate(self):
        store = _make_store()
        ws = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
        _mock_col.aggregate.return_value = iter([{"keyword": "transformer", "count": 10}])
        result = store.get_top_keywords("cs_lg", ws, top_n=5)
        assert _mock_col.aggregate.called
        pipeline = _mock_col.aggregate.call_args[0][0]
        limit_stage = next(s for s in pipeline if "$limit" in s)
        assert limit_stage["$limit"] == 5


class TestMongoStoreGetKeywordHistory:
    def test_query_includes_keyword_and_domain(self):
        store = _make_store()
        cursor = MagicMock()
        cursor.sort.return_value = iter([])
        _mock_col.find.return_value = cursor
        store.get_keyword_history("cs_lg", "transformer")
        query = _mock_col.find.call_args[0][0]
        assert query["domain"] == "cs_lg"
        assert query["keyword"] == "transformer"

    def test_since_adds_gte_filter(self):
        store = _make_store()
        since = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
        cursor = MagicMock()
        cursor.sort.return_value = iter([])
        _mock_col.find.return_value = cursor
        store.get_keyword_history("cs_lg", "transformer", since=since)
        query = _mock_col.find.call_args[0][0]
        assert query["week_start"]["$gte"] == since


class TestMongoStoreClearWeekCounts:
    def test_calls_delete_many_with_domain_and_weeks(self):
        store = _make_store()
        ws = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
        _mock_col.delete_many.return_value = MagicMock(deleted_count=7)
        count = store.clear_week_counts("cs_lg", [ws])
        query = _mock_col.delete_many.call_args[0][0]
        assert query["domain"] == "cs_lg"
        assert ws in query["week_start"]["$in"]
        assert count == 7


# ──────────────────────────────────────────────────────────────────────────────
# articles
# ──────────────────────────────────────────────────────────────────────────────

class TestMongoStoreUpsertArticle:
    def test_calls_update_one_with_arxiv_id_and_domain(self):
        store = _make_store()
        _mock_articles.update_one.return_value = MagicMock(upserted_id="abc123")
        ws = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
        result = store.upsert_article(
            arxiv_id="2401.00001",
            domain="cs_lg",
            week_start=ws,
            title="Test paper",
            published="2024-01-03T00:00:00Z",
            abstract="Deep learning rocks",
            fetched_at=ws,
        )
        _mock_articles.update_one.assert_called_once()
        filter_doc = _mock_articles.update_one.call_args[0][0]
        assert filter_doc == {"arxiv_id": "2401.00001", "domain": "cs_lg"}
        assert result is True  # upserted_id is set → new document

    def test_returns_false_when_article_already_exists(self):
        store = _make_store()
        _mock_articles.update_one.return_value = MagicMock(upserted_id=None)
        ws = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
        result = store.upsert_article(
            arxiv_id="2401.00001",
            domain="cs_lg",
            week_start=ws,
            title="Test",
            published="2024-01-03T00:00:00Z",
            abstract="Abstract",
            fetched_at=ws,
        )
        assert result is False

    def test_document_contains_domain(self):
        store = _make_store()
        _mock_articles.update_one.return_value = MagicMock(upserted_id="x")
        ws = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
        store.upsert_article("2401.00001", "cs_lg", ws, "Title", "2024-01-01", "Abstract", ws)
        update_doc = _mock_articles.update_one.call_args[0][1]
        set_on_insert = update_doc["$setOnInsert"]
        assert set_on_insert["domain"] == "cs_lg"


class TestMongoStoreArticleExists:
    def test_returns_true_when_document_found(self):
        store = _make_store()
        _mock_articles.count_documents.return_value = 1
        assert store.article_exists("2401.00001", "cs_lg") is True
        _mock_articles.count_documents.assert_called_with(
            {"arxiv_id": "2401.00001", "domain": "cs_lg"}, limit=1
        )

    def test_returns_false_when_not_found(self):
        store = _make_store()
        _mock_articles.count_documents.return_value = 0
        assert store.article_exists("2401.00001", "cs_lg") is False


class TestMongoStoreGetArticlesForExtraction:
    _WS = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)

    def _query_from_find(self, store, version=2, batch_size=50):
        mock_cursor = MagicMock()
        mock_cursor.limit.return_value = []
        _mock_articles.find.return_value = mock_cursor
        store.get_articles_for_extraction("cs_lg", [self._WS], extractor_version=version, batch_size=batch_size)
        return _mock_articles.find.call_args[0][0], mock_cursor

    def test_calls_find_with_version_filter(self):
        store = _make_store()
        query, _ = self._query_from_find(store)
        assert query["domain"] == "cs_lg"
        assert self._WS in query["week_start"]["$in"]
        or_clauses = query["$or"]
        none_clause = next(
            c for c in or_clauses
            if "keyword_extractor_version" in c and c["keyword_extractor_version"] is None
        )
        lt_clause = next(
            c for c in or_clauses
            if isinstance(c.get("keyword_extractor_version"), dict)
            and "$lt" in c["keyword_extractor_version"]
        )
        assert lt_clause["keyword_extractor_version"]["$lt"] == 2

    def test_respects_batch_size(self):
        store = _make_store()
        _, mock_cursor = self._query_from_find(store, batch_size=25)
        mock_cursor.limit.assert_called_with(25)


class TestMongoStoreCountArticlesForExtraction:
    def test_calls_count_documents_with_same_query(self):
        store = _make_store()
        ws = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
        _mock_articles.count_documents.return_value = 42
        result = store.count_articles_for_extraction("cs_lg", [ws], extractor_version=1)
        assert result == 42
        query = _mock_articles.count_documents.call_args[0][0]
        assert query["domain"] == "cs_lg"
        assert ws in query["week_start"]["$in"]
        assert "$or" in query

    def test_returns_zero_when_no_articles(self):
        store = _make_store()
        _mock_articles.count_documents.return_value = 0
        result = store.count_articles_for_extraction("cs_lg", [], extractor_version=1)
        assert result == 0


class TestMongoStoreSaveArticleKeywords:
    def test_calls_update_one_with_keywords_and_version(self):
        store = _make_store()
        store.save_article_keywords("2401.00001", "cs_lg", {"transformer": 5}, extractor_version=1)
        _mock_articles.update_one.assert_called_once()
        filter_doc = _mock_articles.update_one.call_args[0][0]
        assert filter_doc == {"arxiv_id": "2401.00001", "domain": "cs_lg"}
        update_doc = _mock_articles.update_one.call_args[0][1]
        assert update_doc["$set"]["keywords"] == {"transformer": 5}
        assert update_doc["$set"]["keyword_extractor_version"] == 1

    def test_sets_updated_at(self):
        store = _make_store()
        store.save_article_keywords("2401.00001", "cs_lg", {"transformer": 5}, extractor_version=1)
        update_doc = _mock_articles.update_one.call_args[0][1]
        assert "updated_at" in update_doc["$set"]
        import datetime as dt
        assert isinstance(update_doc["$set"]["updated_at"], dt.datetime)


class TestMongoStoreGetArticleCountsByWeek:
    def test_calls_aggregate_with_domain(self):
        store = _make_store()
        ws = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
        _mock_articles.aggregate.return_value = iter([{"_id": ws, "count": 42}])
        result = store.get_article_counts_by_week("cs_lg")
        assert _mock_articles.aggregate.called
        pipeline = _mock_articles.aggregate.call_args[0][0]
        assert pipeline[0]["$match"]["domain"] == "cs_lg"
        assert result == {ws: 42}

    def test_returns_empty_dict_when_no_articles(self):
        store = _make_store()
        _mock_articles.aggregate.return_value = iter([])
        result = store.get_article_counts_by_week("cs_lg")
        assert result == {}


class TestMongoStoreGetLatestArticleUpdate:
    def test_returns_datetime_when_found(self):
        store = _make_store()
        ts = dt.datetime(2024, 3, 1, tzinfo=dt.timezone.utc)
        _mock_articles.find_one.return_value = {"updated_at": ts}
        result = store.get_latest_article_update("cs_lg")
        assert result == ts
        query = _mock_articles.find_one.call_args[0][0]
        assert query["domain"] == "cs_lg"
        assert "updated_at" in query

    def test_returns_none_when_no_articles_with_updated_at(self):
        store = _make_store()
        _mock_articles.find_one.return_value = None
        result = store.get_latest_article_update("cs_lg")
        assert result is None


# ──────────────────────────────────────────────────────────────────────────────
# aggregates
# ──────────────────────────────────────────────────────────────────────────────

class TestMongoStoreSaveAndGetAggregated:
    def test_save_calls_update_one(self):
        store = _make_store()
        ts = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
        store.save_aggregated("cs_lg", ts, ["transformer"], ["diffusion"])
        _mock_agg_col.update_one.assert_called_once()
        filter_doc = _mock_agg_col.update_one.call_args[0][0]
        assert filter_doc == {"domain": "cs_lg"}

    def test_save_includes_extractor_key(self):
        store = _make_store()
        ts = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
        store.save_aggregated("cs_lg", ts, ["transformer"], ["diffusion"],
                              extractor_key="1_count_stopwords")
        update_doc = _mock_agg_col.update_one.call_args[0][1]
        assert update_doc["$set"]["extractor_key"] == "1_count_stopwords"

    def test_save_extractor_key_default_empty(self):
        store = _make_store()
        ts = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
        store.save_aggregated("cs_lg", ts, [], [])
        update_doc = _mock_agg_col.update_one.call_args[0][1]
        assert "extractor_key" in update_doc["$set"]

    def test_get_calls_find_one(self):
        store = _make_store()
        _mock_agg_col.find_one.return_value = {"domain": "cs_lg", "top_popular": ["transformer"]}
        result = store.get_aggregated("cs_lg")
        _mock_agg_col.find_one.assert_called_with({"domain": "cs_lg"}, {"_id": 0})
        assert result["top_popular"] == ["transformer"]

    def test_get_returns_none_when_not_found(self):
        store = _make_store()
        _mock_agg_col.find_one.return_value = None
        assert store.get_aggregated("nonexistent") is None

    def test_get_all_aggregated_calls_find(self):
        store = _make_store()
        _mock_agg_col.find.return_value.sort.return_value = iter([])
        store.get_all_aggregated()
        _mock_agg_col.find.assert_called_with({}, {"_id": 0})


# ──────────────────────────────────────────────────────────────────────────────
# delete
# ──────────────────────────────────────────────────────────────────────────────

class TestMongoStoreDeleteDomain:
    def test_calls_delete_many(self):
        store = _make_store()
        _mock_col.delete_many.return_value = MagicMock(deleted_count=42)
        count = store.delete_domain("cs_lg")
        _mock_col.delete_many.assert_called_with({"domain": "cs_lg"})
        assert count == 42
