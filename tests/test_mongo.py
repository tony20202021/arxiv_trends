from __future__ import annotations
import datetime as dt
from unittest.mock import MagicMock, patch, call

import pytest

# Мокируем MongoClient до импорта MongoStore
_mock_client = MagicMock()
_mock_db = MagicMock()
_mock_col = MagicMock()
_mock_agg_col = MagicMock()

_mock_client.__getitem__ = MagicMock(return_value=_mock_db)
_mock_db.__getitem__ = MagicMock(side_effect=lambda name: _mock_col if name == "weekly_keyword_counts" else _mock_agg_col)


def _make_store():
    with patch("storage.mongo.MongoClient", return_value=_mock_client):
        from storage.mongo import MongoStore
        store = MongoStore("mongodb://localhost:27017", "test_db")
    return store


@pytest.fixture(autouse=True)
def reset_mocks():
    _mock_col.reset_mock()
    _mock_agg_col.reset_mock()
    yield


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
        # должен быть $limit=5
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


class TestMongoStoreSaveAndGetAggregated:
    def test_save_calls_update_one(self):
        store = _make_store()
        ts = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
        store.save_aggregated("cs_lg", ts, ["transformer"], ["diffusion"])
        _mock_agg_col.update_one.assert_called_once()
        filter_doc = _mock_agg_col.update_one.call_args[0][0]
        assert filter_doc == {"domain": "cs_lg"}

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


class TestMongoStoreDeleteDomain:
    def test_calls_delete_many(self):
        store = _make_store()
        _mock_col.delete_many.return_value = MagicMock(deleted_count=42)
        count = store.delete_domain("cs_lg")
        _mock_col.delete_many.assert_called_with({"domain": "cs_lg"})
        assert count == 42
