"""Сервис 3: пересчёт агрегатов из weekly_keyword_counts → aggregates.

Публичный API:
    recompute_aggregates(domains, mongo_uri, mongo_db, force, date_from)
"""
from __future__ import annotations
import datetime as dt
import logging
from typing import List

from config.constants import TOP_N, GROWTH_WINDOW_WEEKS
from keywords.registry import ACTIVE_EXTRACTOR_KEY
from storage.mongo import MongoStore
from analytics.trends import to_frame, pivot_week_keyword, top_popular_now, top_growing_last_window

logger = logging.getLogger(__name__)


def recompute_aggregates(
    domains: List[dict],
    mongo_uri: str,
    mongo_db: str,
    force: bool = False,
    date_from: dt.date | None = None,
) -> dict:
    """Сервис 3: пересчитать топ-популярные/растущие агрегаты из weekly_keyword_counts.

    Читает только из БД. Графики не строятся.
    Если date_from задан — берёт только недели начиная с этой даты.

    Проверяет актуальность: если articles.updated_at <= aggregates.computed_at —
    пропускает домен. force=True отключает проверку.

    Returns:
        dict {domain: {"weeks": int, "popular": [...], "growing": [...], "skipped": bool}}
    """
    store = MongoStore(mongo_uri, mongo_db)
    results: dict[str, dict] = {}
    _since = (
        dt.datetime(date_from.year, date_from.month, date_from.day)
        if date_from is not None else None
    )

    for domain in domains:
        dname = domain["domain"]

        # Проверка актуальности агрегатов
        if not force:
            latest_update = store.get_latest_article_update(dname)
            agg = store.get_aggregated(dname)
            computed_at = agg.get("computed_at") if agg else None

            if latest_update and computed_at and computed_at >= latest_update:
                logger.info(
                    "Домен '%s': агрегаты актуальны (computed_at=%s >= updated_at=%s), пропускаем",
                    dname, computed_at.date(), latest_update.date(),
                )
                results[dname] = {
                    "weeks": 0,
                    "popular": agg.get("top_popular", [])[:5],
                    "growing": agg.get("top_growing", [])[:5],
                    "skipped": True,
                }
                continue

        week_datetimes = sorted(store.col.distinct("week_start", {"domain": dname}))
        if _since is not None:
            week_datetimes = [w for w in week_datetimes if w >= _since]
        if not week_datetimes:
            logger.warning("Домен '%s': нет данных в БД, пропускаем", dname)
            results[dname] = {"weeks": 0, "popular": [], "growing": [], "skipped": False}
            continue

        logger.info("Домен '%s': %d недель в БД", dname, len(week_datetimes))

        rows = store.get_counts_last_weeks(dname, week_datetimes)
        df = to_frame(rows)
        pivot = pivot_week_keyword(df)

        popular = top_popular_now(pivot, TOP_N)
        growing = top_growing_last_window(pivot, GROWTH_WINDOW_WEEKS, TOP_N)

        store.save_aggregated(
            domain=dname,
            computed_at=dt.datetime.now(dt.timezone.utc),
            top_popular=popular,
            top_growing=growing,
            extractor_key=ACTIVE_EXTRACTOR_KEY,
        )

        results[dname] = {
            "weeks": len(week_datetimes),
            "popular": popular[:5],
            "growing": growing[:5],
            "skipped": False,
        }

    # Суммарный агрегат по всем доменам
    logger.info("=== Суммарный агрегат по всем доменам ===")
    all_week_datetimes = store.get_all_week_starts()
    if _since is not None:
        all_week_datetimes = [w for w in all_week_datetimes if w >= _since]
    if all_week_datetimes:
        all_rows = store.get_counts_all_domains(all_week_datetimes)
        all_df = to_frame(all_rows)
        all_pivot = pivot_week_keyword(all_df)
        all_popular = top_popular_now(all_pivot, TOP_N)
        all_growing = top_growing_last_window(all_pivot, GROWTH_WINDOW_WEEKS, TOP_N)
        store.save_aggregated(
            domain="_all",
            computed_at=dt.datetime.now(dt.timezone.utc),
            top_popular=all_popular,
            top_growing=all_growing,
            extractor_key=ACTIVE_EXTRACTOR_KEY,
        )
        results["_all"] = {
            "weeks": len(all_week_datetimes),
            "popular": all_popular[:5],
            "growing": all_growing[:5],
            "skipped": False,
        }
        logger.info("  Суммарно: %d недель, популярные=%s, растущие=%s",
                    len(all_week_datetimes), all_popular, all_growing)
    else:
        results["_all"] = {"weeks": 0, "popular": [], "growing": [], "skipped": False}

    return results
