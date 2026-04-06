from __future__ import annotations
import datetime as dt
import logging
from pathlib import Path
from typing import Dict, List

import pandas as pd
from tqdm import tqdm
from slugify import slugify

import time

from config.constants import (
    HISTORY_WEEKS, TOP_N, GROWTH_WINDOW_WEEKS,
    ARXIV_PAGE_SIZE, ARXIV_MAX_OFFSET, ARXIV_OFFSET_LIMIT, ARXIV_BATCH_SIZE, ARXIV_BATCH_SLEEP_SEC, REQUEST_SLEEP_SEC,
)
from utils import utc_today, iter_week_starts, week_start, to_week_datetime, iter_weeks_between
from arxiv.api_client import ArxivApiClient
from arxiv.html_fetcher import ArxivHtmlFetcher
from keywords.registry import extract_keywords, ACTIVE_EXTRACTOR, ACTIVE_EXTRACTOR_KEY, extractor_info
from storage.mongo import MongoStore
from analytics.trends import to_frame, pivot_week_keyword, top_popular_now, top_growing_last_window
from plots.plotter import plot_keywords_over_time, plot_article_counts, build_keyword_styles

logger = logging.getLogger(__name__)


def _arxiv_id_from_entry_id(entry_id: str) -> str:
    return (entry_id or "").rstrip("/").split("/")[-1]


def run_for_domain(
    domain: dict,
    store: MongoStore,
    api: ArxivApiClient,
    fetcher: ArxivHtmlFetcher,
    out_dir: str,
    today: dt.date | None = None,
):
    today = today or utc_today()
    weeks = iter_week_starts(today, HISTORY_WEEKS)

    lo = weeks[0].strftime("%Y%m%d0000")
    hi = (weeks[-1] + dt.timedelta(days=6)).strftime("%Y%m%d2359")

    logger.info("Fetching domain '%s': %d weeks [%s .. %s]", domain["domain"], HISTORY_WEEKS, lo, hi)

    entries = []
    start = 0
    while True:
        feed = api.query(
            search_query=domain["arxiv_search_query"],
            start=start,
            max_results=ARXIV_PAGE_SIZE,
            sort_by="submittedDate",
            sort_order="descending",
            submitted_date_range=(lo, hi),
        )
        batch = api.parse_entries(feed)
        if not batch:
            break
        entries.extend(batch)
        start += len(batch)
        if len(batch) < ARXIV_PAGE_SIZE:
            break

    logger.info("Domain '%s': fetched %d entries, extracting keywords...", domain["domain"], len(entries))

    weekly_counts: Dict[dt.date, Dict[str, int]] = {ws: {} for ws in weeks}

    def add_counts(ws: dt.date, kws: Dict[str, int]):
        b = weekly_counts.setdefault(ws, {})
        for k, c in kws.items():
            b[k] = b.get(k, 0) + int(c)

    skipped = 0
    for e in tqdm(entries, desc=f"{domain['domain']} abstracts", leave=False):
        arxiv_id = _arxiv_id_from_entry_id(e.get("id", ""))
        if not arxiv_id:
            skipped += 1
            continue
        try:
            html = fetcher.fetch_abs_html(arxiv_id)
        except Exception as exc:
            logger.warning("Skipping %s — fetch failed: %s", arxiv_id, exc)
            skipped += 1
            continue
        abstract = fetcher.extract_abstract(html)
        if not abstract:
            skipped += 1
            continue
        kws = extract_keywords(abstract)

        pub = e.get("published", "")
        try:
            d = pd.to_datetime(pub, utc=True).date()
        except Exception:
            d = today
        ws = week_start(d)
        if ws in weekly_counts:
            add_counts(ws, kws)

    logger.info("Domain '%s': done. Skipped %d entries. Writing to MongoDB...", domain["domain"], skipped)

    # write to Mongo
    for ws in weeks:
        store.upsert_week_counts(domain["domain"], to_week_datetime(ws), weekly_counts.get(ws, {}))

    # read back and plot
    rows = store.get_counts_last_weeks(domain["domain"], [to_week_datetime(w) for w in weeks])
    df = to_frame(rows)
    pivot = pivot_week_keyword(df)

    popular = top_popular_now(pivot, TOP_N)
    growing = top_growing_last_window(pivot, GROWTH_WINDOW_WEEKS, TOP_N)

    # сохраняем агрегаты в отдельную коллекцию
    store.save_aggregated(
        domain=domain["domain"],
        computed_at=dt.datetime.now(dt.timezone.utc),
        top_popular=popular,
        top_growing=growing,
        extractor_key=ACTIVE_EXTRACTOR_KEY,
    )

    slug = slugify(domain["domain"])
    base = Path(out_dir) / "plots" / slug
    base.mkdir(parents=True, exist_ok=True)

    styles = build_keyword_styles(list(dict.fromkeys(popular + growing)))
    plot_keywords_over_time(pivot, popular, f"{domain['title']} — Top-{TOP_N} popular (last week)", base / "top_popular.png", keyword_styles=styles)
    plot_keywords_over_time(pivot, growing, f"{domain['title']} — Top-{TOP_N} growing (last {GROWTH_WINDOW_WEEKS} weeks)", base / "top_growing.png", keyword_styles=styles, regression_window=GROWTH_WINDOW_WEEKS)
    plot_article_counts(store.get_article_counts_by_week(domain["domain"]), f"{domain['title']} — Articles per week", base / "articles_per_week.png")

    logger.info("Domain '%s': plots saved to %s", domain["domain"], base)


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
        logger.info("  Суммарно: %d недель, популярные=%s, растущие=%s", len(all_week_datetimes), all_popular, all_growing)
    else:
        results["_all"] = {"weeks": 0, "popular": [], "growing": [], "skipped": False}

    return results


def render_plots(
    domains: List[dict],
    mongo_uri: str,
    mongo_db: str,
    out_dir: str,
    date_from: dt.date | None = None,
) -> dict:
    """Сервис 4: построить графики из агрегатов и данных БД.

    Читает aggregates и weekly_keyword_counts / articles из БД.
    Если date_from задан — рисует только данные начиная с этой даты.
    Агрегаты не пересчитываются.

    Returns:
        dict {domain: {"plots": int, "skipped": bool}}
    """
    store = MongoStore(mongo_uri, mongo_db)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    results: dict[str, dict] = {}
    _since = (
        dt.datetime(date_from.year, date_from.month, date_from.day)
        if date_from is not None else None
    )

    for domain in domains:
        dname = domain["domain"]

        agg = store.get_aggregated(dname)
        if not agg:
            logger.warning("Домен '%s': нет агрегатов, пропускаем. Запустите сначала скрипт 3.", dname)
            results[dname] = {"plots": 0, "skipped": True}
            continue

        popular = agg.get("top_popular", [])
        growing = agg.get("top_growing", [])

        week_datetimes = sorted(store.col.distinct("week_start", {"domain": dname}))
        if _since is not None:
            week_datetimes = [w for w in week_datetimes if w >= _since]
        if not week_datetimes:
            logger.warning("Домен '%s': нет данных keyword_counts, пропускаем", dname)
            results[dname] = {"plots": 0, "skipped": True}
            continue

        rows = store.get_counts_last_weeks(dname, week_datetimes)
        df = to_frame(rows)
        pivot = pivot_week_keyword(df)

        slug = slugify(dname)
        base = Path(out_dir) / "plots" / slug
        base.mkdir(parents=True, exist_ok=True)

        ext_label = agg.get("extractor_key") or ACTIVE_EXTRACTOR_KEY
        styles = build_keyword_styles(list(dict.fromkeys(popular + growing)))
        plot_keywords_over_time(
            pivot, popular,
            f"{domain['title']} — Top-{TOP_N} popular (last week)  [{ext_label}]",
            base / "top_popular.png",
            keyword_styles=styles,
        )
        plot_keywords_over_time(
            pivot, growing,
            f"{domain['title']} — Top-{TOP_N} growing (last {GROWTH_WINDOW_WEEKS} weeks)  [{ext_label}]",
            base / "top_growing.png",
            keyword_styles=styles,
            regression_window=GROWTH_WINDOW_WEEKS,
        )
        art_counts = store.get_article_counts_by_week(dname)
        if _since is not None:
            art_counts = {k: v for k, v in art_counts.items() if k >= _since}
        plot_article_counts(
            art_counts,
            f"{domain['title']} — Articles per week",
            base / "articles_per_week.png",
        )

        logger.info("  Графики сохранены → %s", base)
        results[dname] = {"plots": 3, "skipped": False}

    # Суммарные графики по всем доменам
    agg_all = store.get_aggregated("_all")
    if agg_all:
        all_week_datetimes = store.get_all_week_starts()
        if _since is not None:
            all_week_datetimes = [w for w in all_week_datetimes if w >= _since]
        if all_week_datetimes:
            all_rows = store.get_counts_all_domains(all_week_datetimes)
            all_df = to_frame(all_rows)
            all_pivot = pivot_week_keyword(all_df)
            all_popular = agg_all.get("top_popular", [])
            all_growing = agg_all.get("top_growing", [])

            base_all = Path(out_dir) / "plots" / "_all"
            base_all.mkdir(parents=True, exist_ok=True)

            all_ext_label = agg_all.get("extractor_key") or ACTIVE_EXTRACTOR_KEY
            styles = build_keyword_styles(list(dict.fromkeys(all_popular + all_growing)))
            plot_keywords_over_time(
                all_pivot, all_popular,
                f"All domains — Top-{TOP_N} popular (last week)  [{all_ext_label}]",
                base_all / "top_popular.png",
                keyword_styles=styles,
            )
            plot_keywords_over_time(
                all_pivot, all_growing,
                f"All domains — Top-{TOP_N} growing (last {GROWTH_WINDOW_WEEKS} weeks)  [{all_ext_label}]",
                base_all / "top_growing.png",
                keyword_styles=styles,
                regression_window=GROWTH_WINDOW_WEEKS,
            )
            all_art_counts = store.get_article_counts_all_domains()
            if _since is not None:
                all_art_counts = {k: v for k, v in all_art_counts.items() if k >= _since}
            plot_article_counts(
                all_art_counts,
                "All domains — Articles per week",
                base_all / "articles_per_week.png",
            )
            logger.info("  Суммарные графики сохранены → %s", base_all)
            results["_all"] = {"plots": 3, "skipped": False}
    else:
        logger.warning("Суммарные агрегаты не найдены — запустите сначала скрипт 3.")
        results["_all"] = {"plots": 0, "skipped": True}

    return results


# Обратная совместимость для recompute_plots.py
def recompute_plots(
    domains: List[dict],
    mongo_uri: str,
    mongo_db: str,
    out_dir: str,
    force: bool = False,
) -> dict:
    agg_results = recompute_aggregates(domains, mongo_uri, mongo_db, force=force)
    plot_results = render_plots(domains, mongo_uri, mongo_db, out_dir)
    merged = {}
    for domain in domains:
        dname = domain["domain"]
        merged[dname] = {**agg_results.get(dname, {}), **plot_results.get(dname, {})}
    return merged


def run_pipeline(
    domains: List[dict],
    week_from: dt.date,
    week_to: dt.date,
    mongo_uri: str,
    mongo_db: str,
    api_url: str,
    user_agent: str,
    overwrite: bool = False,
    max_articles: int = -1,
    recompute_aggregates: bool = False,
) -> dict:
    """Запуск пайплайна за произвольный диапазон недель с контролем повторной обработки.

    Args:
        domains:              список доменов (dicts из domains.json) для обработки
        week_from:            начало диапазона (включительно)
        week_to:              конец диапазона (включительно)
        overwrite:            False — пропускать уже обработанные статьи;
                              True  — удалить старые данные только за указанные
                                      недели и домены и обработать заново
        max_articles:         максимум статей на домен (-1 = без ограничений)
        recompute_aggregates: пересчитать топ-популярные/растущие после обработки
    Returns:
        dict со статистикой прогона по доменам
    """
    from utils import iter_weeks_between

    store = MongoStore(mongo_uri, mongo_db)
    api = ArxivApiClient(api_url, user_agent=user_agent, sleep_sec=REQUEST_SLEEP_SEC)
    fetcher = ArxivHtmlFetcher(user_agent=user_agent, sleep_sec=REQUEST_SLEEP_SEC)

    weeks = iter_weeks_between(week_from, week_to)
    week_datetimes = [to_week_datetime(w) for w in weeks]

    lo = weeks[0].strftime("%Y%m%d0000")
    hi = (weeks[-1] + dt.timedelta(days=6)).strftime("%Y%m%d2359")

    stats: dict[str, dict] = {}

    for domain in domains:
        dname = domain["domain"]
        logger.info("=== Домен '%s': недели %s … %s, max_articles=%s ===",
                    dname, weeks[0], weeks[-1], max_articles if max_articles != -1 else "∞")

        if overwrite:
            n_kw = store.clear_week_counts(dname, week_datetimes)
            logger.info("  overwrite: удалено %d keyword-docs", n_kw)

        # Запрос к arXiv API — страницами
        entries = []
        api_start = 0
        api_truncated = False
        while True:
            page_size = ARXIV_PAGE_SIZE
            if max_articles != -1:
                remaining = max_articles - len(entries)
                if remaining <= 0:
                    break
                page_size = min(ARXIV_PAGE_SIZE, remaining)

            if api_start >= ARXIV_MAX_OFFSET:
                logger.warning("  Достигнут лимит arXiv API (start=%d >= %d)", api_start, ARXIV_MAX_OFFSET)
                api_truncated = True
                break

            try:
                feed = api.query(
                    search_query=domain["arxiv_search_query"],
                    start=api_start,
                    max_results=page_size,
                    sort_by="submittedDate",
                    sort_order="descending",
                    submitted_date_range=(lo, hi),
                )
            except Exception as exc:
                logger.warning("  Пагинация прервана на start=%d: %s — обрабатываем что есть", api_start, exc)
                api_truncated = True
                break
            batch = api.parse_entries(feed)
            if not batch:
                break
            entries.extend(batch)
            api_start += len(batch)
            if len(batch) < page_size:
                break

        logger.info("  Получено статей из arXiv: %d%s", len(entries), " (прервано rate-limit)" if api_truncated else "")

        weekly_counts: dict[dt.date, dict[str, int]] = {ws: {} for ws in weeks}

        skipped_processed = 0
        skipped_error = 0
        processed_now = 0
        now = dt.datetime.now(dt.timezone.utc)

        for i, e in enumerate(tqdm(entries, desc=dname, leave=False)):
            # Пауза между батчами
            if i > 0 and i % ARXIV_BATCH_SIZE == 0:
                logger.debug("  Батч %d/%d — пауза %.1f сек", i, len(entries), ARXIV_BATCH_SLEEP_SEC)
                time.sleep(ARXIV_BATCH_SLEEP_SEC)

            arxiv_id = _arxiv_id_from_entry_id(e.get("id", ""))
            if not arxiv_id:
                skipped_error += 1
                continue

            pub = e.get("published", "")
            try:
                d = pd.to_datetime(pub, utc=True).date()
            except Exception:
                d = week_from
            ws = week_start(d)
            if ws not in weekly_counts:
                continue

            if store.article_exists(arxiv_id, dname):
                skipped_processed += 1
                continue

            try:
                html = fetcher.fetch_abs_html(arxiv_id)
            except Exception as exc:
                logger.warning("  Пропуск %s — ошибка загрузки: %s", arxiv_id, exc)
                skipped_error += 1
                continue

            abstract = fetcher.extract_abstract(html)
            if not abstract:
                skipped_error += 1
                continue

            ws_dt = to_week_datetime(ws)
            store.upsert_article(
                arxiv_id=arxiv_id,
                domain=dname,
                week_start=ws_dt,
                title=e.get("title", ""),
                published=pub,
                abstract=abstract,
                fetched_at=now,
            )

            kws = extract_keywords(abstract)
            bucket = weekly_counts.setdefault(ws, {})
            for k, c in kws.items():
                bucket[k] = bucket.get(k, 0) + int(c)

            processed_now += 1

        # Запись в MongoDB
        for ws in weeks:
            ws_dt = to_week_datetime(ws)
            if weekly_counts.get(ws):
                store.upsert_week_counts(dname, ws_dt, weekly_counts[ws])

        stats[dname] = {
            "total_fetched": len(entries),
            "api_truncated": api_truncated,
            "processed_now": processed_now,
            "skipped_already_done": skipped_processed,
            "skipped_error": skipped_error,
        }
        logger.info(
            "  Готово: обработано %d, пропущено (уже есть) %d, ошибок %d",
            processed_now, skipped_processed, skipped_error,
        )

        if recompute_aggregates:
            logger.info("  Пересчёт агрегатов для '%s'...", dname)
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
            )
            logger.info("  Агрегаты сохранены: популярные=%s, растущие=%s", popular, growing)

    return stats


def run_all(domains: List[dict], mongo_uri: str, mongo_db: str, api_url: str, user_agent: str, out_dir: str):
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    logger.info("Starting pipeline: %d domains, output → %s", len(domains), out_dir)

    store = MongoStore(mongo_uri, mongo_db)
    api = ArxivApiClient(api_url, user_agent=user_agent, sleep_sec=REQUEST_SLEEP_SEC)
    fetcher = ArxivHtmlFetcher(user_agent=user_agent, sleep_sec=REQUEST_SLEEP_SEC)

    for d in domains:
        try:
            run_for_domain(d, store, api, fetcher, out_dir=out_dir)
        except Exception as exc:
            logger.error("Domain '%s' failed: %s", d.get("domain"), exc, exc_info=True)

    logger.info("Pipeline complete.")


# ──────────────────────────────────────────────────────────────────────────────
# Сервис 1: загрузка абстрактов из arXiv → articles
# ──────────────────────────────────────────────────────────────────────────────

def _date_ranges_for_period(date_from: dt.date, date_to: dt.date) -> List[tuple[dt.date, dt.date]]:
    """Разбить диапазон на недели (пн–вс). Используется для разбивки запросов к arXiv."""
    ranges = []
    cur = date_from
    while cur <= date_to:
        # конец недели = воскресенье
        end = cur + dt.timedelta(days=6 - cur.weekday())
        ranges.append((cur, min(end, date_to)))
        cur = end + dt.timedelta(days=1)
    return ranges


def _fetch_range(
    api: "ArxivApiClient",
    search_query: str,
    date_from: dt.date,
    date_to: dt.date,
    max_articles: int = -1,
    prefix: str = "",
) -> tuple[List[dict], bool]:
    """Загрузить статьи за один диапазон дат с пагинацией.

    Если при пагинации start достигает ARXIV_OFFSET_LIMIT — автоматически
    разбивает диапазон по дням и рекурсивно вызывает себя для каждого дня.

    Returns:
        (entries, truncated)
    """
    lo = date_from.strftime("%Y%m%d0000")
    hi = date_to.strftime("%Y%m%d2359")

    entries: List[dict] = []
    api_start = 0
    truncated = False

    while True:
        page_size = ARXIV_PAGE_SIZE
        if max_articles != -1:
            remaining = max_articles - len(entries)
            if remaining <= 0:
                break
            page_size = min(ARXIV_PAGE_SIZE, remaining)

        if api_start >= ARXIV_OFFSET_LIMIT:
            # Лимит offset достигнут — дробим диапазон по дням
            if date_from == date_to:
                # один день уже, дальше дробить некуда
                logger.warning("  Лимит offset при запросе одного дня %s, прерываем", date_from)
                truncated = True
                break

            logger.info("  Лимит offset start=%d для %s…%s — разбиваем по дням",
                        api_start, date_from, date_to)
            n_days = (date_to - date_from).days + 1
            day = date_from
            while day <= date_to:
                d_idx = (day - date_from).days + 1
                day_entries, day_trunc = _fetch_range(
                    api, search_query, day, day, max_articles,
                    prefix=f"{prefix}день {d_idx}/{n_days} ",
                )
                entries.extend(day_entries)
                if day_trunc:
                    truncated = True
                if max_articles != -1 and len(entries) >= max_articles:
                    truncated = True
                    break
                day += dt.timedelta(days=1)
            break

        try:
            feed = api.query(
                search_query=search_query,
                start=api_start,
                max_results=page_size,
                sort_by="submittedDate",
                sort_order="descending",
                submitted_date_range=(lo, hi),
            )
        except Exception as exc:
            logger.warning("  Пагинация прервана на start=%d (%s…%s): %s",
                           api_start, date_from, date_to, exc)
            truncated = True
            break

        batch = api.parse_entries(feed)
        if not batch:
            break

        entries.extend(batch)
        api_start += len(batch)

        total_results = int(feed.get("feed", {}).get("opensearch_totalresults", 0) or 0)
        if total_results:
            logger.info("  %s[%s…%s] start=%d  получено %d, итого %d из %d",
                        prefix, date_from, date_to, api_start - len(batch),
                        len(batch), len(entries), total_results)
        else:
            logger.info("  %s[%s…%s] start=%d  получено %d, итого %d",
                        prefix, date_from, date_to, api_start - len(batch), len(batch), len(entries))

        if len(batch) < page_size:
            break

    return entries, truncated

def fetch_abstracts(
    domains: List[dict],
    week_from: dt.date,
    week_to: dt.date,
    mongo_uri: str,
    mongo_db: str,
    api_url: str,
    user_agent: str,
    max_articles: int = -1,
) -> dict:
    """Сервис 1: читает список статей из arXiv API, сохраняет абстракты в articles.

    Больше никакая функция пайплайна не обращается к arXiv напрямую.
    Если статья уже есть в articles — пропускается.

    Args:
        max_articles: максимум статей на домен (-1 = без ограничений)

    Returns:
        dict {domain: {"fetched": int, "new": int, "skipped": int, "truncated": bool}}
    """
    store = MongoStore(mongo_uri, mongo_db)
    api = ArxivApiClient(api_url, user_agent=user_agent, sleep_sec=REQUEST_SLEEP_SEC)

    weeks = iter_weeks_between(week_from, week_to)
    lo = weeks[0].strftime("%Y%m%d0000")
    hi = (weeks[-1] + dt.timedelta(days=6)).strftime("%Y%m%d2359")

    stats: dict[str, dict] = {}

    for domain in domains:
        dname = domain["domain"]
        logger.info("=== fetch_abstracts '%s': %s … %s, max=%s ===",
                    dname, weeks[0], weeks[-1], max_articles if max_articles != -1 else "∞")

        # Пагинация arXiv API — батчами по неделям, при превышении лимита — по дням
        entries: List[dict] = []
        truncated = False
        week_ranges = _date_ranges_for_period(week_from, week_to)
        n_weeks = len(week_ranges)
        logger.info("  Запрос к arXiv API: %d недел(ь) (пауза %gs между страницами)...",
                    n_weeks, REQUEST_SLEEP_SEC)

        fetch_start = time.time()
        for w_idx, (w_from, w_to) in enumerate(week_ranges, 1):
            if max_articles != -1 and len(entries) >= max_articles:
                truncated = True
                break
            remaining = (max_articles - len(entries)) if max_articles != -1 else -1
            w_entries, w_trunc = _fetch_range(
                api, domain["arxiv_search_query"], w_from, w_to, remaining,
                prefix=f"({w_idx}/{n_weeks}) ",
            )
            entries.extend(w_entries)
            if w_trunc:
                truncated = True

            elapsed_sec = time.time() - fetch_start
            weeks_left = n_weeks - w_idx
            if weeks_left > 0:
                avg_sec = elapsed_sec / w_idx
                eta_sec = avg_sec * weeks_left
                eta_clock = (dt.datetime.now() + dt.timedelta(seconds=eta_sec)).strftime("%H:%M")
                logger.info(
                    "  (%d/%d) прошло %s, осталось ~%s (ETA ~%s)",
                    w_idx, n_weeks,
                    str(dt.timedelta(seconds=int(elapsed_sec))),
                    str(dt.timedelta(seconds=int(eta_sec))),
                    eta_clock,
                )

        logger.info("  Итого из arXiv: %d статей%s", len(entries), " (прервано)" if truncated else "")

        new_count = 0
        skipped_count = 0
        now = dt.datetime.now(dt.timezone.utc)

        for i, e in enumerate(tqdm(entries, desc=dname, leave=False)):
            arxiv_id = _arxiv_id_from_entry_id(e.get("id", ""))
            if not arxiv_id:
                skipped_count += 1
                continue

            # Определяем неделю
            pub = e.get("published", "")
            try:
                d = pd.to_datetime(pub, utc=True).date()
            except Exception:
                d = week_from
            ws = week_start(d)
            ws_dt = to_week_datetime(ws)

            # Если уже есть в articles — пропускаем
            if store.article_exists(arxiv_id, dname):
                skipped_count += 1
                continue

            abstract = e.get("abstract", "")
            if not abstract:
                skipped_count += 1
                continue

            store.upsert_article(
                arxiv_id=arxiv_id,
                domain=dname,
                week_start=ws_dt,
                title=e.get("title", ""),
                published=pub,
                abstract=abstract,
                fetched_at=now,
            )
            new_count += 1

        logger.info("  Готово: новых=%d, пропущено=%d", new_count, skipped_count)
        stats[dname] = {
            "fetched": len(entries),
            "new": new_count,
            "skipped": skipped_count,
            "truncated": truncated,
        }

    return stats


# ──────────────────────────────────────────────────────────────────────────────
# Сервис 2: извлечение ключевых слов из articles → articles + weekly_keyword_counts
# ──────────────────────────────────────────────────────────────────────────────

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

    return stats
