from __future__ import annotations
import datetime as dt
import logging
from typing import Dict, List, Optional

from pymongo import MongoClient, ASCENDING, DESCENDING, UpdateOne, DeleteMany

logger = logging.getLogger(__name__)


class MongoStore:
    def __init__(self, mongo_uri: str, db_name: str):
        self.client = MongoClient(
            mongo_uri,
            serverSelectionTimeoutMS=5_000,
            socketTimeoutMS=600_000,   # 10 мин: агрегация _all по ~24M строкам занимает ~5 мин
            connectTimeoutMS=5_000,
        )
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

    def get_top_keyword_candidates(
        self,
        domain: str,
        week_starts: List[dt.datetime],
        top_k: int = 1000,
    ) -> List[str]:
        """Top-K keywords by total count for a domain over given weeks (server-side)."""
        lo = min(week_starts)
        hi = max(week_starts)
        pipeline = [
            {"$match": {"domain": domain, "week_start": {"$gte": lo, "$lte": hi}}},
            {"$group": {"_id": "$keyword", "total": {"$sum": "$count"}}},
            {"$sort": {"total": -1}},
            {"$limit": top_k},
        ]
        return [r["_id"] for r in self.col.aggregate(pipeline)]

    def get_counts_for_keywords(
        self,
        domain: str,
        week_starts: List[dt.datetime],
        keywords: List[str],
    ) -> List[dict]:
        """Per-week counts for specific keywords only (single domain)."""
        if not keywords:
            return []
        lo = min(week_starts)
        hi = max(week_starts)
        cur = self.col.find(
            {"domain": domain, "week_start": {"$gte": lo, "$lte": hi}, "keyword": {"$in": keywords}},
            {"_id": 0},
        )
        return list(cur)

    def get_top_keyword_candidates_all(
        self,
        week_starts: List[dt.datetime],
        top_k: int = 1000,
    ) -> List[str]:
        """Top-K keywords by total count across all domains over given weeks.

        Two-phase: collect per-domain candidates (indexed, fast), then re-rank
        the union cross-domain. Avoids a full ~24M-row collection scan.
        """
        domains = self.col.distinct("domain")
        all_candidates: set = set()
        for domain in domains:
            dc = self.get_top_keyword_candidates(domain, week_starts, top_k=top_k)
            all_candidates.update(dc)
        if not all_candidates:
            return []
        lo = min(week_starts)
        hi = max(week_starts)
        pipeline = [
            {"$match": {"week_start": {"$gte": lo, "$lte": hi}, "keyword": {"$in": list(all_candidates)}}},
            {"$group": {"_id": "$keyword", "total": {"$sum": "$count"}}},
            {"$sort": {"total": -1}},
            {"$limit": top_k},
        ]
        return [r["_id"] for r in self.col.aggregate(pipeline, allowDiskUse=True)]

    def get_counts_all_domains_for_keywords(
        self,
        week_starts: List[dt.datetime],
        keywords: List[str],
    ) -> List[dict]:
        """Per-week counts summed across all domains for specific keywords only."""
        if not keywords:
            return []
        lo = min(week_starts)
        hi = max(week_starts)
        pipeline = [
            {"$match": {"week_start": {"$gte": lo, "$lte": hi}, "keyword": {"$in": keywords}}},
            {"$group": {
                "_id": {"week_start": "$week_start", "keyword": "$keyword"},
                "count": {"$sum": "$count"},
            }},
            {"$project": {
                "_id": 0,
                "week_start": "$_id.week_start",
                "keyword": "$_id.keyword",
                "count": 1,
            }},
        ]
        return list(self.col.aggregate(pipeline, allowDiskUse=True))

    def get_all_domains(self) -> List[str]:
        """Вернуть список всех доменов, которые есть в БД."""
        return self.col.distinct("domain")

    def get_counts_all_domains(self, week_starts: List[dt.datetime]) -> List[dict]:
        """Суммарные keyword counts по всем доменам за указанные недели.

        Агрегация выполняется на стороне MongoDB ($group по week_start+keyword),
        что возвращает на порядок меньше данных, чем полный scan всех строк.
        """
        lo = min(week_starts)
        hi = max(week_starts)
        pipeline = [
            {"$match": {"week_start": {"$gte": lo, "$lte": hi}}},
            {"$group": {
                "_id": {"week_start": "$week_start", "keyword": "$keyword"},
                "count": {"$sum": "$count"},
            }},
            {"$project": {
                "_id": 0,
                "week_start": "$_id.week_start",
                "keyword": "$_id.keyword",
                "count": 1,
            }},
        ]
        return list(self.col.aggregate(pipeline, allowDiskUse=True))

    def get_all_week_starts(self) -> List[dt.datetime]:
        """Все недели присутствующие в weekly_keyword_counts (по всем доменам)."""
        return sorted(self.col.distinct("week_start"))

    def get_article_counts_all_domains(self) -> Dict[dt.datetime, int]:
        """Количество статей по неделям суммарно по всем доменам."""
        pipeline = [
            {"$group": {"_id": "$week_start", "count": {"$sum": 1}}},
            {"$sort": {"_id": ASCENDING}},
        ]
        return {r["_id"]: r["count"] for r in self.articles.aggregate(pipeline, allowDiskUse=True)}

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
        return list(self.col.aggregate(pipeline, maxTimeMS=10_000))

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
        total_weeks: int | None = None,
        aggregator_version: int | None = None,
    ) -> None:
        """Сохранить предвычисленные топ-списки в коллекцию aggregates."""
        agg_col = self.db["aggregates"]
        doc: dict = {
            "domain": domain,
            "computed_at": computed_at,
            "top_popular": top_popular,
            "top_growing": top_growing,
            "extractor_key": extractor_key,
        }
        if total_weeks is not None:
            doc["total_weeks"] = total_weeks
        if aggregator_version is not None:
            doc["aggregator_version"] = aggregator_version
        agg_col.update_one({"domain": domain}, {"$set": doc}, upsert=True)
        logger.debug("Saved aggregates for domain '%s' (extractor=%s, agg_v=%s)", domain, extractor_key, aggregator_version)

    def save_plots_rendered(self, domain: str, rendered_at: dt.datetime, plotter_version: int) -> None:
        """Обновить метаданные последнего рендеринга графиков в документе aggregates."""
        agg_col = self.db["aggregates"]
        agg_col.update_one(
            {"domain": domain},
            {"$set": {"plots_rendered_at": rendered_at, "plotter_version": plotter_version}},
        )

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

    def has_articles_with_old_version(
        self,
        domain: str,
        week_starts: List[dt.datetime],
        current_version: int,
    ) -> bool:
        """Есть ли статьи с устаревшей (не-None) версией экстрактора."""
        return self.articles.count_documents({
            "domain": domain,
            "week_start": {"$in": week_starts},
            "keyword_extractor_version": {"$exists": True, "$ne": None, "$lt": current_version},
        }, limit=1) > 0

    def reset_article_keywords(
        self,
        domain: str,
        week_starts: List[dt.datetime],
        current_version: int,
    ) -> int:
        """Сбросить ключевые слова статей старых версий для чистого переключения.

        Обнуляет keywords и keyword_extractor_version, снимает updated_at —
        чтобы aggregate.py не считал агрегаты актуальными после чистки счётчиков.
        """
        result = self.articles.update_many(
            {
                "domain": domain,
                "week_start": {"$in": week_starts},
                "keyword_extractor_version": {"$exists": True, "$ne": None, "$lt": current_version},
            },
            {
                "$set": {"keywords": None, "keyword_extractor_version": None},
                "$unset": {"updated_at": ""},
            },
        )
        return result.modified_count

    def _extraction_query(
        self,
        domain: str,
        week_starts: List[dt.datetime],
        extractor_version: int,
        gensim_model_version: int | None = None,
    ) -> dict:
        or_clauses: list[dict] = [
            {"keyword_extractor_version": None},
            {"keyword_extractor_version": {"$lt": extractor_version}},
        ]
        if gensim_model_version is not None and gensim_model_version > 0:
            or_clauses.append({
                "keyword_extractor_version": extractor_version,
                "$or": [
                    {"gensim_model_version": {"$exists": False}},
                    {"gensim_model_version": {"$ne": gensim_model_version}},
                ],
            })
        return {
            "domain": domain,
            "week_start": {"$in": week_starts},
            "$or": or_clauses,
        }

    def count_articles_for_extraction(
        self,
        domain: str,
        week_starts: List[dt.datetime],
        extractor_version: int,
        gensim_model_version: int | None = None,
    ) -> int:
        """Количество статей ожидающих извлечения ключевых слов."""
        return self.articles.count_documents(
            self._extraction_query(domain, week_starts, extractor_version, gensim_model_version)
        )

    def get_articles_for_extraction(
        self,
        domain: str,
        week_starts: List[dt.datetime],
        extractor_version: int,
        batch_size: int = 100,
        gensim_model_version: int | None = None,
    ) -> List[dict]:
        """Статьи у которых нет ключевых слов или версия экстрактора/gensim устарела."""
        return list(self.articles.find(
            self._extraction_query(domain, week_starts, extractor_version, gensim_model_version),
            {"arxiv_id": 1, "abstract": 1, "week_start": 1, "keywords": 1},
        ).limit(batch_size))

    def save_article_keywords(
        self,
        arxiv_id: str,
        domain: str,
        keywords: Dict[str, int],
        extractor_version: int,
        gensim_model_version: int | None = None,
    ) -> None:
        """Записать ключевые слова для статьи."""
        update: dict = {
            "keywords": keywords,
            "keyword_extractor_version": extractor_version,
            "updated_at": dt.datetime.now(dt.timezone.utc),
        }
        if gensim_model_version is not None:
            update["gensim_model_version"] = gensim_model_version
        self.articles.update_one(
            {"arxiv_id": arxiv_id, "domain": domain},
            {"$set": update},
        )

    def get_article_counts_by_week(self, domain: str) -> Dict[dt.datetime, int]:
        """Количество статей по неделям для домена (из коллекции articles)."""
        pipeline = [
            {"$match": {"domain": domain}},
            {"$group": {"_id": "$week_start", "count": {"$sum": 1}}},
            {"$sort": {"_id": ASCENDING}},
        ]
        return {r["_id"]: r["count"] for r in self.articles.aggregate(pipeline, allowDiskUse=True)}

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

    def delete_week_counts_for_weeks(self, domain: str, week_starts: List[dt.datetime], batch_size: int = 5) -> int:
        """Удалить keyword counts для домена за конкретные недели (батчами, чтобы не превышать socketTimeout)."""
        if not week_starts:
            return 0
        total = 0
        for i in range(0, len(week_starts), batch_size):
            batch = week_starts[i:i + batch_size]
            total += self.col.delete_many({"domain": domain, "week_start": {"$in": batch}}).deleted_count
        logger.info("Deleted %d keyword-count docs for domain '%s' (%d weeks)",
                    total, domain, len(week_starts))
        return total

    def delete_domain(self, domain: str) -> int:
        """Удалить все записи домена. Возвращает количество удалённых документов."""
        result = self.col.delete_many({"domain": domain})
        logger.info("Deleted %d documents for domain '%s'", result.deleted_count, domain)
        return result.deleted_count

    # ------------------------------------------------------------------ domain_meta

    def get_article_versions(self, domain: str) -> list[int]:
        """Distinct keyword_extractor_version из articles для домена."""
        raw = self.articles.distinct("keyword_extractor_version", {"domain": domain})
        return sorted(v for v in raw if v is not None)

    def upsert_domain_meta(self, domain: str, keyword_versions: list[int]) -> None:
        """Обновить метаданные домена (версии экстрактора)."""
        self.db["domain_meta"].update_one(
            {"domain": domain},
            {"$set": {
                "keyword_versions": keyword_versions,
                "updated_at": dt.datetime.now(dt.timezone.utc),
            }},
            upsert=True,
        )

    def get_all_domain_meta(self) -> list[dict]:
        """Все записи domain_meta, отсортированные по домену."""
        return list(self.db["domain_meta"].find({}, {"_id": 0}).sort("domain", ASCENDING))
