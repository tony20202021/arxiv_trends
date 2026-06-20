"""Сервис 2: извлечение ключевых слов из articles → weekly_keyword_counts."""
from __future__ import annotations
import datetime as dt
import logging
from typing import List

from tqdm import tqdm

from config.constants import ARXIV_BATCH_SIZE, ARXIV_BATCH_SLEEP_SEC
from keywords.registry import extract_keywords, ACTIVE_EXTRACTOR, extractor_info, active_extractor_uses_gensim
from keywords.gensim_extractor import get_gensim_model_version
from storage.mongo import MongoStore
from utils import iter_weeks_between, to_week_datetime

logger = logging.getLogger(__name__)


def _gensim_version_for_extract() -> int | None:
    if not active_extractor_uses_gensim():
        return None
    version = get_gensim_model_version()
    return version if version > 0 else None


def extract_keywords_batch(
    domains: List[dict],
    week_from: dt.date,
    week_to: dt.date,
    mongo_uri: str,
    mongo_db: str,
    batch_size: int = 100,
) -> dict:
    """Сервис 2: читает articles из БД, извлекает ключевые слова, записывает обратно.

    При смене keyword_extractor_version — чистый переход (сброс счётчиков домена).
    При смене gensim_model_version — точечный re-extract (вычитание старых counts по статье).

    Returns:
        dict {domain: {"processed": int, "skipped": int}}
    """
    store = MongoStore(mongo_uri, mongo_db)
    weeks = iter_weeks_between(week_from, week_to)
    week_datetimes = [to_week_datetime(w) for w in weeks]
    gensim_v = _gensim_version_for_extract()

    stats: dict[str, dict] = {}

    for domain in domains:
        dname = domain["domain"]
        logger.info("=== extract_keywords '%s': %s … %s (%s) ===",
                    dname, weeks[0], weeks[-1], extractor_info())
        if gensim_v is not None:
            logger.info("  gensim_model_version=%d", gensim_v)

        processed = 0
        skipped = 0
        round_num = 0

        while True:
            round_total = store.count_articles_for_extraction(
                dname, week_datetimes, ACTIVE_EXTRACTOR.db_id, gensim_v,
            )
            if round_total == 0:
                break

            if round_num == 0 and store.has_articles_with_old_version(dname, week_datetimes, ACTIVE_EXTRACTOR.db_id):
                cleared = store.delete_week_counts_for_weeks(dname, week_datetimes)
                reset = store.reset_article_keywords(dname, week_datetimes, ACTIVE_EXTRACTOR.db_id)
                logger.info(
                    "  Чистый переход → v%d: сброшено %d статей, удалено %d строк счётчиков",
                    ACTIVE_EXTRACTOR.db_id, reset, cleared,
                )
                round_total = store.count_articles_for_extraction(
                    dname, week_datetimes, ACTIVE_EXTRACTOR.db_id, gensim_v,
                )

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
                        gensim_model_version=gensim_v,
                    )
                    if not articles:
                        break

                    for art in articles:
                        arxiv_id = art["arxiv_id"]
                        abstract = art.get("abstract") or ""
                        ws_dt = art["week_start"]

                        if not abstract:
                            skipped += 1
                            done_in_round += 1
                            pbar.update(1)
                            continue

                        old_keywords = art.get("keywords") or {}
                        if old_keywords:
                            store.upsert_week_counts(
                                dname, ws_dt,
                                {kw: -cnt for kw, cnt in old_keywords.items()},
                            )

                        new_keywords = extract_keywords(abstract)

                        store.save_article_keywords(
                            arxiv_id, dname, new_keywords, ACTIVE_EXTRACTOR.db_id,
                            gensim_model_version=gensim_v,
                        )
                        store.upsert_week_counts(dname, ws_dt, new_keywords)
                        processed += 1
                        done_in_round += 1
                        pbar.update(1)

        logger.info("  Готово: обработано=%d, пропущено=%d", processed, skipped)
        stats[dname] = {"processed": processed, "skipped": skipped}

        store.upsert_domain_meta(dname, [ACTIVE_EXTRACTOR.db_id])
        logger.info("  domain_meta: %s → версия %s", dname, ACTIVE_EXTRACTOR.db_id)

    return stats
