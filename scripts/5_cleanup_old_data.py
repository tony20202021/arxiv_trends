"""Сервис 5: очистка устаревших данных из MongoDB.

Удаляет статьи и keyword-counts старше ARTICLES_TTL_DAYS дней (по умолчанию 2 года).
Параметр задаётся в config/constants.py :: ARTICLES_TTL_DAYS.

Использование:
    # Посмотреть что будет удалено (без удаления):
    python scripts/5_cleanup_old_data.py --dry-run

    # Удалить устаревшие данные:
    python scripts/5_cleanup_old_data.py

    # Удалить данные старше 365 дней:
    python scripts/5_cleanup_old_data.py --ttl-days 365
"""
from __future__ import annotations
import argparse
import datetime as dt
import logging
import os
import sys
from pathlib import Path

_root = Path(__file__).parent.parent
sys.path.insert(0, str(_root / "backend"))
sys.path.insert(0, str(_root))

from dotenv import load_dotenv
load_dotenv(_root / ".env")

from config.constants import ARTICLES_TTL_DAYS
from storage.mongo import MongoStore


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler()],
    )


def cleanup(mongo_uri: str, mongo_db: str, ttl_days: int, dry_run: bool) -> None:
    store = MongoStore(mongo_uri, mongo_db)
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=ttl_days)
    cutoff_naive = cutoff.replace(tzinfo=None)  # MongoDB хранит naive datetime

    logging.info("Порог удаления: статьи старше %d дней (fetched_at < %s)", ttl_days, cutoff_naive.date())

    # --- articles ---
    art_filter = {"fetched_at": {"$lt": cutoff_naive}}
    art_count = store.articles.count_documents(art_filter)
    logging.info("articles к удалению: %d документов", art_count)

    # Собираем week_start затронутых недель — нужно также почистить keyword counts
    affected_weeks: set = set()
    affected_domains: set = set()
    if art_count > 0:
        for doc in store.articles.find(art_filter, {"week_start": 1, "domain": 1, "_id": 0}):
            ws = doc.get("week_start")
            dom = doc.get("domain")
            if ws and dom:
                affected_weeks.add(ws)
                affected_domains.add(dom)

    # --- weekly_keyword_counts для тех же недель ---
    kw_count = 0
    if affected_weeks:
        kw_filter = {
            "week_start": {"$in": list(affected_weeks)},
            "domain": {"$in": list(affected_domains)},
        }
        kw_count = store.col.count_documents(kw_filter)
        logging.info("weekly_keyword_counts к удалению: %d документов (%d недель, %d доменов)",
                     kw_count, len(affected_weeks), len(affected_domains))
    else:
        logging.info("weekly_keyword_counts к удалению: 0 документов")

    if dry_run:
        logging.info("Режим --dry-run: реального удаления не было.")
        return

    if art_count == 0 and kw_count == 0:
        logging.info("Нечего удалять.")
        return

    # Удаляем
    if art_count > 0:
        res = store.articles.delete_many(art_filter)
        logging.info("articles удалено: %d", res.deleted_count)

    if affected_weeks:
        res = store.col.delete_many(kw_filter)
        logging.info("weekly_keyword_counts удалено: %d", res.deleted_count)

    logging.info("Очистка завершена.")


def main() -> None:
    _setup_logging()
    ap = argparse.ArgumentParser(description="Очистка устаревших данных из MongoDB")
    ap.add_argument("--uri",      default=os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017"))
    ap.add_argument("--db",       default=os.environ.get("MONGO_DB", "arxiv_trends"))
    ap.add_argument("--ttl-days", type=int, default=ARTICLES_TTL_DAYS, dest="ttl_days",
                    help=f"Удалить статьи старше N дней (по умолчанию: {ARTICLES_TTL_DAYS} из constants.py)")
    ap.add_argument("--dry-run",  action="store_true", dest="dry_run",
                    help="Показать что будет удалено без фактического удаления")
    args = ap.parse_args()

    print(f"MongoDB: {args.uri}  /  {args.db}")
    print(f"TTL: {args.ttl_days} дней  |  dry-run: {args.dry_run}\n")
    cleanup(args.uri, args.db, args.ttl_days, args.dry_run)


if __name__ == "__main__":
    main()
