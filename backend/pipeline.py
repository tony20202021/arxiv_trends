"""Публичный API пайплайна arXiv Trends.

Импортирует и реэкспортирует сервисы из отдельных модулей:
    fetch.py        — Сервис 1: загрузка абстрактов из arXiv API
    extract.py      — Сервис 2: извлечение ключевых слов
    aggregate.py    — Сервис 3: пересчёт агрегатов
    plot_service.py — Сервис 4: построение графиков

Обратная совместимость: все имена доступны через `from pipeline import ...`
"""
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
    ARXIV_PAGE_SIZE, ARXIV_MAX_OFFSET, ARXIV_BATCH_SIZE, ARXIV_BATCH_SLEEP_SEC, REQUEST_SLEEP_SEC,
)
from utils import utc_today, iter_week_starts, week_start, to_week_datetime, iter_weeks_between
from arxiv.api_client import ArxivApiClient
from arxiv.html_fetcher import ArxivHtmlFetcher
from keywords.registry import extract_keywords, ACTIVE_EXTRACTOR, ACTIVE_EXTRACTOR_KEY, extractor_info
from storage.mongo import MongoStore
from analytics.trends import to_frame, pivot_week_keyword, top_popular_now, top_growing_last_window
from plots.plotter import plot_keywords_over_time, plot_article_counts, build_keyword_styles

# ── публичный API сервисов ──────────────────────────────────────────────────
from fetch import fetch_abstracts, _date_ranges_for_period  # noqa: F401  сервис 1
from extract import extract_keywords_batch                  # noqa: F401  сервис 2
from aggregate import recompute_aggregates                  # noqa: F401  сервис 3
from plot_service import render_plots                       # noqa: F401  сервис 4

logger = logging.getLogger(__name__)


def _arxiv_id_from_entry_id(entry_id: str) -> str:
    return (entry_id or "").rstrip("/").split("/")[-1]


# ──────────────────────────────────────────────────────────────────────────────
# Обратная совместимость
# ──────────────────────────────────────────────────────────────────────────────

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


# ──────────────────────────────────────────────────────────────────────────────
# Устаревшие функции (оставлены для совместимости)
# ──────────────────────────────────────────────────────────────────────────────

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

    for ws in weeks:
        store.upsert_week_counts(domain["domain"], to_week_datetime(ws), weekly_counts.get(ws, {}))

    rows = store.get_counts_last_weeks(domain["domain"], [to_week_datetime(w) for w in weeks])
    df = to_frame(rows)
    pivot = pivot_week_keyword(df)

    popular = top_popular_now(pivot, TOP_N)
    growing = top_growing_last_window(pivot, GROWTH_WINDOW_WEEKS, TOP_N)

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
    """Запуск пайплайна за произвольный диапазон недель с контролем повторной обработки."""
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
