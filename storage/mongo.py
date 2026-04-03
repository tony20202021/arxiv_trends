from __future__ import annotations
import datetime as dt
from typing import Dict, List

from pymongo import MongoClient, ASCENDING, UpdateOne


class MongoStore:
    def __init__(self, mongo_uri: str, db_name: str):
        self.client = MongoClient(mongo_uri)
        self.db = self.client[db_name]
        self.col = self.db["weekly_keyword_counts"]
        self._ensure_indexes()

    def _ensure_indexes(self):
        self.col.create_index(
            [("domain", ASCENDING), ("week_start", ASCENDING), ("keyword", ASCENDING)],
            unique=True,
            name="uniq_domain_week_keyword",
        )
        self.col.create_index([("domain", ASCENDING), ("week_start", ASCENDING)], name="domain_week")

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

    def get_counts_last_weeks(self, domain: str, week_starts: List[dt.datetime]) -> List[dict]:
        lo = min(week_starts)
        hi = max(week_starts)
        cur = self.col.find({"domain": domain, "week_start": {"$gte": lo, "$lte": hi}}, {"_id": 0})
        return list(cur)

TODO добавить остальные методы для получения данных из БД
и для сохранения данных в БД