from __future__ import annotations
import datetime as dt
import logging
from typing import Dict, List, Optional

from pymongo import MongoClient, ASCENDING, UpdateOne, DeleteMany

logger = logging.getLogger(__name__)


class MongoStore:
    def __init__(self, mongo_uri: str, db_name: str):
        self.client = MongoClient(mongo_uri)
        self.db = self.client[db_name]
        self.col = self.db["weekly_keyword_counts"]
        self.processed = self.db["processed_articles"]
        self._ensure_indexes()
        logger.debug("MongoStore connected: %s / %s", mongo_uri, db_name)

    def _ensure_indexes(self):
        self.col.create_index(
            [("domain", ASCENDING), ("week_start", ASCENDING), ("keyword", ASCENDING)],
            unique=True,
            name="uniq_domain_week_keyword",
        )
        self.col.create_index([("domain", ASCENDING), ("week_start", ASCENDING)], name="domain_week")
        self.processed.create_index(
            [("arxiv_id", ASCENDING), ("domain", ASCENDING)],
            unique=True,
            name="uniq_article_domain",
        )
        self.processed.create_index([("domain", ASCENDING), ("week_start", ASCENDING)], name="proc_domain_week")

    # ------------------------------------------------------------------ write

    def upsert_week_counts(self, domain: str, week_start: dt.datetime, counts: Dict[str, int]):
        ops = [
            UpdateOne(
                {"domain": domain, "week_start": week_start, "keyword": kw},
                {"$inc": {"count": int(c)}},
                upsert=True,
            )
            for kw, c in counts.items()
        ]
        if ops:
            self.col.bulk_write(ops, ordered=False)
            logger.debug("Upserted %d keyword counts for domain '%s' week %s", len(ops), domain, week_start.date())

    # ------------------------------------------------------------------ read

    def get_counts_last_weeks(self, domain: str, week_starts: List[dt.datetime]) -> List[dict]:
        lo = min(week_starts)
        hi = max(week_starts)
        cur = self.col.find({"domain": domain, "week_start": {"$gte": lo, "$lte": hi}}, {"_id": 0})
        return list(cur)

    def get_all_domains(self) -> List[str]:
        """Вернуть список всех доменов, которые есть в БД."""
        return self.col.distinct("domain")

    def get_top_keywords(
        self,
        domain: str,
        week_start: dt.datetime,
        top_n: int = 20,
    ) -> List[Dict]:
        """Топ-N ключевых слов для домена за конкретную неделю."""
        pipeline = [
            {"$match": {"domain": domain, "week_start": week_start}},
            {"$sort": {"count": -1}},
            {"$limit": top_n},
            {"$project": {"_id": 0, "keyword": 1, "count": 1}},
        ]
        return list(self.col.aggregate(pipeline))

    def get_keyword_history(
        self,
        domain: str,
        keyword: str,
        since: Optional[dt.datetime] = None,
    ) -> List[Dict]:
        """История конкретного ключевого слова по неделям."""
        query: dict = {"domain": domain, "keyword": keyword}
        if since:
            query["week_start"] = {"$gte": since}
        cur = self.col.find(query, {"_id": 0}).sort("week_start", ASCENDING)
        return list(cur)

    def get_weekly_summary(self, domain: str, week_start: dt.datetime) -> Dict:
        """Суммарная статистика (кол-во уникальных слов, общий счёт) для недели."""
        pipeline = [
            {"$match": {"domain": domain, "week_start": week_start}},
            {"$group": {
                "_id": None,
                "unique_keywords": {"$sum": 1},
                "total_count": {"$sum": "$count"},
            }},
        ]
        results = list(self.col.aggregate(pipeline))
        if not results:
            return {"unique_keywords": 0, "total_count": 0}
        r = results[0]
        return {"unique_keywords": r["unique_keywords"], "total_count": r["total_count"]}

    # ------------------------------------------------------------------ aggregates

    def save_aggregated(
        self,
        domain: str,
        computed_at: dt.datetime,
        top_popular: list[str],
        top_growing: list[str],
    ) -> None:
        """Сохранить предвычисленные топ-списки в коллекцию aggregates."""
        agg_col = self.db["aggregates"]
        agg_col.update_one(
            {"domain": domain},
            {"$set": {
                "domain": domain,
                "computed_at": computed_at,
                "top_popular": top_popular,
                "top_growing": top_growing,
            }},
            upsert=True,
        )
        logger.debug("Saved aggregates for domain '%s'", domain)

    def get_aggregated(self, domain: str) -> dict | None:
        """Получить последние предвычисленные топ-списки для домена."""
        agg_col = self.db["aggregates"]
        return agg_col.find_one({"domain": domain}, {"_id": 0})

    def get_all_aggregated(self) -> list[dict]:
        """Получить агрегаты по всем доменам."""
        agg_col = self.db["aggregates"]
        return list(agg_col.find({}, {"_id": 0}).sort("domain", ASCENDING))

    # ------------------------------------------------------------------ processed articles

    def get_processed_ids(self, domain: str, week_starts: List[dt.datetime]) -> set[str]:
        """Вернуть набор arxiv_id уже обработанных статей для домена за указанные недели."""
        cur = self.processed.find(
            {"domain": domain, "week_start": {"$in": week_starts}},
            {"arxiv_id": 1, "_id": 0},
        )
        return {d["arxiv_id"] for d in cur}

    def mark_articles_processed(
        self,
        domain: str,
        week_start: dt.datetime,
        arxiv_ids: List[str],
        processed_at: dt.datetime,
    ) -> None:
        """Пометить статьи как обработанные (upsert)."""
        if not arxiv_ids:
            return
        ops = [
            UpdateOne(
                {"arxiv_id": aid, "domain": domain},
                {"$set": {"arxiv_id": aid, "domain": domain,
                          "week_start": week_start, "processed_at": processed_at}},
                upsert=True,
            )
            for aid in arxiv_ids
        ]
        self.processed.bulk_write(ops, ordered=False)

    def clear_processed(self, domain: str, week_starts: List[dt.datetime]) -> int:
        """Удалить записи об обработанных статьях (для режима overwrite)."""
        result = self.processed.delete_many(
            {"domain": domain, "week_start": {"$in": week_starts}}
        )
        return result.deleted_count

    def clear_week_counts(self, domain: str, week_starts: List[dt.datetime]) -> int:
        """Удалить keyword counts для домена за указанные недели (для режима overwrite)."""
        result = self.col.delete_many(
            {"domain": domain, "week_start": {"$in": week_starts}}
        )
        return result.deleted_count

    # ------------------------------------------------------------------ delete

    def delete_domain(self, domain: str) -> int:
        """Удалить все записи домена. Возвращает количество удалённых документов."""
        result = self.col.delete_many({"domain": domain})
        logger.info("Deleted %d documents for domain '%s'", result.deleted_count, domain)
        return result.deleted_count
