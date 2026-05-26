"""Сервис 3: пересчёт агрегатов из weekly_keyword_counts → aggregates.

Публичный API:
    recompute_aggregates(domains, mongo_uri, mongo_db, force, date_from)
"""
from __future__ import annotations
import ctypes
import datetime as dt
import gc
import logging
from typing import List

from config.constants import TOP_N, GROWTH_WINDOW_WEEKS, AGGREGATOR_VERSION
from keywords.registry import ACTIVE_EXTRACTOR_KEY, ACTIVE_EXTRACTOR
from storage.mongo import MongoStore
from analytics.trends import to_frame, pivot_week_keyword, top_popular_now, top_growing_last_window
from utils import last_complete_week_start

logger = logging.getLogger(__name__)

_CANDIDATES_K = 1000  # pre-select server-side before loading into Python


def _growth_weeks(week_datetimes: list) -> list:
    """Last GROWTH_WINDOW_WEEKS from the list (or all if fewer)."""
    return week_datetimes[-GROWTH_WINDOW_WEEKS:] if len(week_datetimes) >= GROWTH_WINDOW_WEEKS else week_datetimes


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
    # Исключаем текущую (незакрытую) неделю — данные по ней неполные
    _before = last_complete_week_start()
    logger.info("Агрегаты считаются по завершённым неделям (до %s включительно), agg_v=%s",
                _before.date(), AGGREGATOR_VERSION)

    for domain in domains:
        dname = domain["domain"]

        # Проверка актуальности агрегатов
        if not force:
            latest_update = store.get_latest_article_update(dname)
            agg = store.get_aggregated(dname)
            computed_at = agg.get("computed_at") if agg else None
            agg_version = agg.get("aggregator_version") if agg else None

            data_fresh = latest_update and computed_at and computed_at >= latest_update
            agg_version_ok = agg_version == AGGREGATOR_VERSION

            if data_fresh and agg_version_ok:
                logger.info(
                    "Домен '%s': агрегаты актуальны (computed_at=%s >= updated_at=%s, agg_v=%s), пропускаем",
                    dname, computed_at.date(), latest_update.date(), agg_version,
                )
                store.upsert_domain_meta(dname, [ACTIVE_EXTRACTOR.db_id])
                results[dname] = {
                    "weeks": 0,
                    "popular": agg.get("top_popular", [])[:5],
                    "growing": agg.get("top_growing", [])[:5],
                    "skipped": True,
                }
                continue
            if data_fresh and not agg_version_ok:
                logger.info(
                    "Домен '%s': данные актуальны, но версия агрегатора устарела (%s → %s), пересчитываем",
                    dname, agg_version, AGGREGATOR_VERSION,
                )

        week_datetimes = sorted(store.col.distinct("week_start", {"domain": dname}))
        week_datetimes = [w.replace(tzinfo=None) if w.tzinfo is not None else w for w in week_datetimes]
        if _since is not None:
            week_datetimes = [w for w in week_datetimes if w >= _since]
        week_datetimes = [w for w in week_datetimes if w <= _before]
        if not week_datetimes:
            logger.warning("Домен '%s': нет данных в БД, пропускаем", dname)
            results[dname] = {"weeks": 0, "popular": [], "growing": [], "skipped": False}
            continue

        logger.info("Домен '%s': пересчёт агрегатов по %d неделям...", dname, len(week_datetimes))

        gw = _growth_weeks(week_datetimes)
        candidates = store.get_top_keyword_candidates(dname, gw, top_k=_CANDIDATES_K)
        logger.debug("  Кандидатов (топ-%d из роств-окна): %d", _CANDIDATES_K, len(candidates))
        rows = store.get_counts_for_keywords(dname, week_datetimes, candidates)
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
            total_weeks=len(week_datetimes),
            aggregator_version=AGGREGATOR_VERSION,
        )
        store.upsert_domain_meta(dname, [ACTIVE_EXTRACTOR.db_id])
        logger.info("Домен '%s': агрегаты обновлены  популярные=%s", dname, popular[:3])

        results[dname] = {
            "weeks": len(week_datetimes),
            "popular": popular[:5],
            "growing": growing[:5],
            "skipped": False,
        }
        gc.collect()
        try:
            ctypes.cdll.LoadLibrary("libc.so.6").malloc_trim(0)
        except Exception:
            pass

    # Суммарный агрегат по всем доменам
    logger.info("=== Суммарный агрегат по всем доменам ===")
    all_week_datetimes = store.get_all_week_starts()
    all_week_datetimes = [w.replace(tzinfo=None) if w.tzinfo is not None else w for w in all_week_datetimes]
    if _since is not None:
        all_week_datetimes = [w for w in all_week_datetimes if w >= _since]
    all_week_datetimes = [w for w in all_week_datetimes if w <= _before]
    if all_week_datetimes:
        # Candidates from pre-computed per-domain aggregates — avoids 24M-row scan.
        # Also collect per-domain extractor_keys to derive actual data version for _all.
        all_candidates = []
        domain_ext_keys = []
        for dom_agg in store.get_all_aggregated():
            all_candidates += dom_agg.get("top_popular", [])
            all_candidates += dom_agg.get("top_growing", [])
            if dom_agg.get("extractor_key") and dom_agg.get("domain") != "_all":
                domain_ext_keys.append(dom_agg["extractor_key"])
        all_candidates = list(dict.fromkeys(all_candidates))
        # _all extractor_key reflects actual data version (most common among domains)
        from collections import Counter
        all_extractor_key = Counter(domain_ext_keys).most_common(1)[0][0] if domain_ext_keys else ACTIVE_EXTRACTOR_KEY
        logger.info("  Загружаю данные (%d кандидатов из агрегатов, %d недель, все домены)...", len(all_candidates), len(all_week_datetimes))
        all_rows = store.get_counts_all_domains_for_keywords(all_week_datetimes, all_candidates)
        logger.info("  Загружено %d строк, строю pivot...", len(all_rows))
        all_df = to_frame(all_rows)
        all_pivot = pivot_week_keyword(all_df)
        logger.info("  Pivot готов (%d недель × %d слов), считаю топ...", *all_pivot.shape)
        all_popular = top_popular_now(all_pivot, TOP_N)
        all_growing = top_growing_last_window(all_pivot, GROWTH_WINDOW_WEEKS, TOP_N)
        store.save_aggregated(
            domain="_all",
            computed_at=dt.datetime.now(dt.timezone.utc),
            top_popular=all_popular,
            top_growing=all_growing,
            extractor_key=all_extractor_key,
            total_weeks=len(all_week_datetimes),
            aggregator_version=AGGREGATOR_VERSION,
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
