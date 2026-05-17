"""Сервис 2: извлечение ключевых слов из articles → weekly_keyword_counts.

Публичный API:
    extract_keywords_batch(domains, week_from, week_to, mongo_uri, mongo_db, batch_size)
"""
from __future__ import annotations
import datetime as dt
import logging
from typing import List

from tqdm import tqdm

from config.constants import ARXIV_BATCH_SIZE, ARXIV_BATCH_SLEEP_SEC
from keywords.registry import extract_keywords, ACTIVE_EXTRACTOR, extractor_info
from storage.mongo import MongoStore
from utils import iter_weeks_between, to_week_datetime

logger = logging.getLogger(__name__)


def extract_keywords_batch(
    domains: List[dict],
    week_from: dt.date,
    week_to: dt.date,
    mongo_uri: str,
    mongo_db: str,
    batch_size: int = 100,
) -> dict:
    """Сервис 2: читает articles из БД, извлекает ключевые слова, записывает обратно.

    Обрабатывает статьи у которых:
    - keywords = None (ещё не обработаны), ИЛИ
    - keyword_extractor_version < ACTIVE_EXTRACTOR.db_id (версия устарела)

    При обновлении версии: вычитает старые keyword counts, добавляет новые.

    Returns:
        dict {domain: {"processed": int, "skipped": int}}
    """
    store = MongoStore(mongo_uri, mongo_db)
    weeks = iter_weeks_between(week_from, week_to)
    week_datetimes = [to_week_datetime(w) for w in weeks]

    stats: dict[str, dict] = {}

    for domain in domains:
        dname = domain["domain"]
        logger.info("=== extract_keywords '%s': %s … %s (%s) ===",
                    dname, weeks[0], weeks[-1], extractor_info())

        processed = 0
        skipped = 0
        round_num = 0

        while True:
            round_total = store.count_articles_for_extraction(dname, week_datetimes, ACTIVE_EXTRACTOR.db_id)
            if round_total == 0:
                break

            round_num += 1
            logger.info("  Раунд %d: статей для обработки %d", round_num, round_total)
            done_in_round = 0

            with tqdm(total=round_total, desc=f"{dname} [{round_num}]", unit="ст") as pbar:
                while done_in_round < round_total:
                    articles = store.get_articles_for_extraction(
                        domain=dname,
                        week_starts=week_datetimes,
                        extractor_version=ACTIVE_EXTRACTOR.db_id,
                        batch_size=min(batch_size, round_total - done_in_round),
                    )
                    if not articles:
                        break

                    for art in articles:
                        arxiv_id = art["arxiv_id"]
                        abstract = art.get("abstract") or ""
                        ws_dt = art["week_start"]
                        old_keywords: dict | None = art.get("keywords")

                        if not abstract:
                            skipped += 1
                            done_in_round += 1
                            pbar.update(1)
                            continue

                        new_keywords = extract_keywords(abstract)

                        # Если была старая версия — вычитаем старые counts
                        if old_keywords:
                            minus = {k: -v for k, v in old_keywords.items()}
                            store.upsert_week_counts(dname, ws_dt, minus)

                        # Записываем новые keywords в articles
                        store.save_article_keywords(arxiv_id, dname, new_keywords, ACTIVE_EXTRACTOR.db_id)

                        # Добавляем новые counts в weekly_keyword_counts
                        store.upsert_week_counts(dname, ws_dt, new_keywords)
                        processed += 1
                        done_in_round += 1
                        pbar.update(1)

        logger.info("  Готово: обработано=%d, пропущено=%d", processed, skipped)
        stats[dname] = {"processed": processed, "skipped": skipped}

        versions = store.get_article_versions(dname)
        store.upsert_domain_meta(dname, versions)
        logger.info("  domain_meta: %s → версии %s", dname, versions)

    return stats
