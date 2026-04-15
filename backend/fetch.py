"""Сервис 1: загрузка абстрактов из arXiv API → коллекция articles.

Публичный API:
    fetch_abstracts(domains, week_from, week_to, mongo_uri, mongo_db, api_url, user_agent)
"""
from __future__ import annotations
import datetime as dt
import logging
import time
from typing import List

import pandas as pd
from tqdm import tqdm

from config.constants import (
    ARXIV_PAGE_SIZE, ARXIV_OFFSET_LIMIT,
    REQUEST_SLEEP_SEC,
)
from utils import iter_weeks_between, week_start, to_week_datetime
from arxiv.api_client import ArxivApiClient
from storage.mongo import MongoStore

logger = logging.getLogger(__name__)


def _arxiv_id_from_entry_id(entry_id: str) -> str:
    return (entry_id or "").rstrip("/").split("/")[-1]


def _date_ranges_for_period(date_from: dt.date, date_to: dt.date) -> list[tuple[dt.date, dt.date]]:
    """Разбить диапазон на недели (пн–вс). Используется для разбивки запросов к arXiv."""
    ranges = []
    cur = date_from
    while cur <= date_to:
        end = cur + dt.timedelta(days=6 - cur.weekday())
        ranges.append((cur, min(end, date_to)))
        cur = end + dt.timedelta(days=1)
    return ranges


def _fetch_range(
    api: ArxivApiClient,
    search_query: str,
    date_from: dt.date,
    date_to: dt.date,
    max_articles: int = -1,
    prefix: str = "",
) -> tuple[list[dict], bool]:
    """Загрузить статьи за один диапазон дат с пагинацией.

    Если при пагинации start достигает ARXIV_OFFSET_LIMIT — автоматически
    разбивает диапазон по дням и рекурсивно вызывает себя для каждого дня.

    Глубина рекурсии: максимум 1 уровень. Повторный вызов происходит только
    когда date_from == date_to (один день), и в этом случае рекурсия не входит
    в ветку day-by-day — она сразу выходит с truncated=True. Переполнения стека
    не возникает при любом количестве недель.

    Returns:
        (entries, truncated)
    """
    lo = date_from.strftime("%Y%m%d0000")
    hi = date_to.strftime("%Y%m%d2359")

    entries: list[dict] = []
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
            if date_from == date_to:
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

    stats: dict[str, dict] = {}

    for domain in domains:
        dname = domain["domain"]
        logger.info("=== fetch_abstracts '%s': %s … %s, max=%s ===",
                    dname, weeks[0], weeks[-1], max_articles if max_articles != -1 else "∞")

        entries: list[dict] = []
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

        for e in tqdm(entries, desc=dname, leave=False):
            arxiv_id = _arxiv_id_from_entry_id(e.get("id", ""))
            if not arxiv_id:
                skipped_count += 1
                continue

            pub = e.get("published", "")
            try:
                d = pd.to_datetime(pub, utc=True).date()
            except Exception:
                d = week_from
            ws = week_start(d)
            ws_dt = to_week_datetime(ws)

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
