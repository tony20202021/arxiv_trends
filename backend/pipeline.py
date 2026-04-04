from __future__ import annotations
import datetime as dt
import logging
from pathlib import Path
from typing import Dict, List

import pandas as pd
from tqdm import tqdm
from slugify import slugify

from config.constants import (
    HISTORY_WEEKS, TOP_N, GROWTH_WINDOW_WEEKS,
    MAX_RESULTS_PER_DOMAIN, ARXIV_PAGE_SIZE, REQUEST_SLEEP_SEC,
)
from utils import utc_today, iter_week_starts, week_start, to_week_datetime
from arxiv.api_client import ArxivApiClient
from arxiv.html_fetcher import ArxivHtmlFetcher
from keywords.extractor import extract_keywords_from_abstract
from storage.mongo import MongoStore
from analytics.trends import to_frame, pivot_week_keyword, top_popular_now, top_growing_last_window
from plots.plotter import plot_keywords_over_time

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
            max_results=min(ARXIV_PAGE_SIZE, MAX_RESULTS_PER_DOMAIN - start),
            sort_by="submittedDate",
            sort_order="descending",
            submitted_date_range=(lo, hi),
        )
        batch = api.parse_entries(feed)
        if not batch:
            break
        entries.extend(batch)
        start += len(batch)
        if start >= MAX_RESULTS_PER_DOMAIN or len(batch) < ARXIV_PAGE_SIZE:
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
        kws = extract_keywords_from_abstract(abstract)

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
    )

    slug = slugify(domain["domain"])
    base = Path(out_dir) / "plots" / slug
    base.mkdir(parents=True, exist_ok=True)

    plot_keywords_over_time(pivot, popular, f"{domain['title']} — Top-{TOP_N} popular (last week)", base / "top_popular.png")
    plot_keywords_over_time(pivot, growing, f"{domain['title']} — Top-{TOP_N} growing (last {GROWTH_WINDOW_WEEKS} weeks)", base / "top_growing.png")

    logger.info("Domain '%s': plots saved to %s", domain["domain"], base)


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
