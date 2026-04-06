from __future__ import annotations
import datetime as dt
import logging
from typing import Dict, List, Optional

from pymongo import MongoClient, ASCENDING, DESCENDING, UpdateOne, DeleteMany

logger = logging.getLogger(__name__)


class MongoStore:
    def __init__(self, mongo_uri: str, db_name: str):
        self.client = MongoClient(mongo_uri)
        self.db = self.client[db_name]
        self.col = self.db["weekly_keyword_counts"]
        self.articles = self.db["articles"]
        self._ensure_indexes()
        logger.debug("MongoStore connected: %s / %s", mongo_uri, db_name)

    def _ensure_indexes(self):
        # --- weekly_keyword_counts ---
        self.col.create_index(
            [("domain", ASCENDING), ("week_start", ASCENDING), ("keyword", ASCENDING)],
            unique=True,
            name="uniq_domain_week_keyword",
        )
        self.col.create_index([("domain", ASCENDING), ("week_start", ASCENDING)], name="domain_week")
        # для get_keyword_history: {domain, keyword} + sort by week_start
        self.col.create_index(
            [("domain", ASCENDING), ("keyword", ASCENDING), ("week_start", ASCENDING)],
            name="domain_keyword_week",
        )
        # для get_all_week_starts / get_counts_all_domains: фильтр/distinct только по week_start
        self.col.create_index([("week_start", ASCENDING)], name="week_start")

        # --- articles ---
        self.articles.create_index(
            [("arxiv_id", ASCENDING), ("domain", ASCENDING)],
            unique=True,
            name="uniq_art_domain",
        )
        self.articles.create_index([("domain", ASCENDING), ("week_start", ASCENDING)], name="art_domain_week")
        # для extraction-запросов: {domain, week_start, keyword_extractor_version}
        self.articles.create_index(
            [("domain", ASCENDING), ("week_start", ASCENDING), ("keyword_extractor_version", ASCENDING)],
            name="art_domain_week_ver",
        )
        self.articles.create_index([("domain", ASCENDING), ("updated_at", ASCENDING)], name="art_domain_updated")
        # для latest_records (sort fetched_at DESC) и возможных запросов по дате загрузки
        self.articles.create_index([("fetched_at", DESCENDING)], name="art_fetched_at")
        # для search_articles (sort published DESC)
        self.articles.create_index([("published", DESCENDING)], name="art_published")
        # полнотекстовый поиск по abstract и title
        self.articles.create_index(
            [("abstract", "text"), ("title", "text")],
            name="art_text",
            default_language="english",
        )

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

    def get_counts_all_domains(self, week_starts: List[dt.datetime]) -> List[dict]:
        """Keyword counts по всем доменам за указанные недели (без фильтра по домену)."""
        lo = min(week_starts)
        hi = max(week_starts)
        cur = self.col.find({"week_start": {"$gte": lo, "$lte": hi}}, {"_id": 0})
        return list(cur)

    def get_all_week_starts(self) -> List[dt.datetime]:
        """Все недели присутствующие в weekly_keyword_counts (по всем доменам)."""
        return sorted(self.col.distinct("week_start"))

    def get_article_counts_all_domains(self) -> Dict[dt.datetime, int]:
        """Количество статей по неделям суммарно по всем доменам."""
        pipeline = [
            {"$group": {"_id": "$week_start", "count": {"$sum": 1}}},
            {"$sort": {"_id": ASCENDING}},
        ]
        return {r["_id"]: r["count"] for r in self.articles.aggregate(pipeline)}

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
        extractor_key: str = "",
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
                "extractor_key": extractor_key,
            }},
            upsert=True,
        )
        logger.debug("Saved aggregates for domain '%s' (extractor=%s)", domain, extractor_key)

    def get_aggregated(self, domain: str) -> dict | None:
        """Получить последние предвычисленные топ-списки для домена."""
        agg_col = self.db["aggregates"]
        return agg_col.find_one({"domain": domain}, {"_id": 0})

    def get_all_aggregated(self) -> list[dict]:
        """Получить агрегаты по всем доменам."""
        agg_col = self.db["aggregates"]
        return list(agg_col.find({}, {"_id": 0}).sort("domain", ASCENDING))

    def clear_week_counts(self, domain: str, week_starts: List[dt.datetime]) -> int:
        """Удалить keyword counts для домена за указанные недели (для режима overwrite)."""
        result = self.col.delete_many(
            {"domain": domain, "week_start": {"$in": week_starts}}
        )
        return result.deleted_count

    # ------------------------------------------------------------------ articles (abstracts + keywords)

    def upsert_article(
        self,
        arxiv_id: str,
        domain: str,
        week_start: dt.datetime,
        title: str,
        published: str,
        abstract: str,
        fetched_at: dt.datetime,
    ) -> bool:
        """Сохранить статью с абстрактом. Возвращает True если запись новая."""
        result = self.articles.update_one(
            {"arxiv_id": arxiv_id, "domain": domain},
            {"$setOnInsert": {
                "arxiv_id": arxiv_id,
                "domain": domain,
                "week_start": week_start,
                "title": title,
                "published": published,
                "abstract": abstract,
                "fetched_at": fetched_at,
                "keywords": None,
                "keyword_extractor_version": None,
            }},
            upsert=True,
        )
        return result.upserted_id is not None

    def _extraction_query(self, domain: str, week_starts: List[dt.datetime], extractor_version: int) -> dict:
        return {
            "domain": domain,
            "week_start": {"$in": week_starts},
            "$or": [
                {"keyword_extractor_version": None},
                {"keyword_extractor_version": {"$lt": extractor_version}},
            ],
        }

    def count_articles_for_extraction(
        self,
        domain: str,
        week_starts: List[dt.datetime],
        extractor_version: int,
    ) -> int:
        """Количество статей ожидающих извлечения ключевых слов."""
        return self.articles.count_documents(
            self._extraction_query(domain, week_starts, extractor_version)
        )

    def get_articles_for_extraction(
        self,
        domain: str,
        week_starts: List[dt.datetime],
        extractor_version: int,
        batch_size: int = 100,
    ) -> List[dict]:
        """Статьи у которых нет ключевых слов или версия экстрактора устарела."""
        return list(self.articles.find(
            self._extraction_query(domain, week_starts, extractor_version),
            {"arxiv_id": 1, "abstract": 1, "week_start": 1, "keywords": 1},
        ).limit(batch_size))

    def save_article_keywords(
        self,
        arxiv_id: str,
        domain: str,
        keywords: Dict[str, int],
        extractor_version: int,
    ) -> None:
        """Записать ключевые слова для статьи."""
        self.articles.update_one(
            {"arxiv_id": arxiv_id, "domain": domain},
            {"$set": {
                "keywords": keywords,
                "keyword_extractor_version": extractor_version,
                "updated_at": dt.datetime.now(dt.timezone.utc),
            }},
        )

    def get_article_counts_by_week(self, domain: str) -> Dict[dt.datetime, int]:
        """Количество статей по неделям для домена (из коллекции articles)."""
        pipeline = [
            {"$match": {"domain": domain}},
            {"$group": {"_id": "$week_start", "count": {"$sum": 1}}},
            {"$sort": {"_id": ASCENDING}},
        ]
        return {r["_id"]: r["count"] for r in self.articles.aggregate(pipeline)}

    def get_latest_article_update(self, domain: str) -> Optional[dt.datetime]:
        """Вернуть дату последнего обновления ключевых слов для домена."""
        doc = self.articles.find_one(
            {"domain": domain, "updated_at": {"$exists": True}},
            {"updated_at": 1, "_id": 0},
            sort=[("updated_at", DESCENDING)],
        )
        return doc["updated_at"] if doc else None

    def article_exists(self, arxiv_id: str, domain: str) -> bool:
        """Проверить есть ли статья в таблице articles."""
        return self.articles.count_documents(
            {"arxiv_id": arxiv_id, "domain": domain}, limit=1
        ) > 0

    # ------------------------------------------------------------------ delete

    def get_week_starts_in_counts(self, domain: str) -> List[dt.datetime]:
        """Все недели присутствующие в weekly_keyword_counts для домена."""
        return sorted(self.col.distinct("week_start", {"domain": domain}))

    def get_week_starts_in_articles(self, domain: str) -> List[dt.datetime]:
        """Все недели присутствующие в articles для домена."""
        return sorted(self.articles.distinct("week_start", {"domain": domain}))

    def delete_week_counts_for_weeks(self, domain: str, week_starts: List[dt.datetime]) -> int:
        """Удалить keyword counts для домена за конкретные недели."""
        if not week_starts:
            return 0
        result = self.col.delete_many({"domain": domain, "week_start": {"$in": week_starts}})
        logger.info("Deleted %d keyword-count docs for domain '%s' (%d weeks)",
                    result.deleted_count, domain, len(week_starts))
        return result.deleted_count

    def delete_domain(self, domain: str) -> int:
        """Удалить все записи домена. Возвращает количество удалённых документов."""
        result = self.col.delete_many({"domain": domain})
        logger.info("Deleted %d documents for domain '%s'", result.deleted_count, domain)
        return result.deleted_count
