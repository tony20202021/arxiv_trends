from __future__ import annotations
import datetime as dt
from pathlib import Path
from typing import Dict, List

import pandas as pd
from tqdm import tqdm
from slugify import slugify

from config.constants import (
    HISTORY_WEEKS, TOP_N, GROWTH_WINDOW_WEEKS,
    MAX_RESULTS_PER_DOMAIN, ARXIV_PAGE_SIZE, REQUEST_SLEEP_SEC,
)
from src.arxiv_trends.utils import utc_today, iter_week_starts, week_start, to_week_datetime
from src.arxiv_trends.arxiv.api_client import ArxivApiClient
from src.arxiv_trends.arxiv.html_fetcher import ArxivHtmlFetcher
from src.arxiv_trends.keywords.extractor import extract_keywords_from_abstract
from src.arxiv_trends.storage.mongo import MongoStore
from src.arxiv_trends.analytics.trends import to_frame, pivot_week_keyword, top_popular_now, top_growing_last_window
from src.arxiv_trends.plots.plotter import plot_keywords_over_time


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

    weekly_counts: Dict[dt.date, Dict[str, int]] = {ws: {} for ws in weeks}

    def add_counts(ws: dt.date, kws: Dict[str, int]):
        b = weekly_counts.setdefault(ws, {})
        for k, c in kws.items():
            b[k] = b.get(k, 0) + int(c)

    for e in tqdm(entries, desc=f"{domain['domain']} abstracts", leave=False):
        arxiv_id = _arxiv_id_from_entry_id(e.get("id", ""))
        if not arxiv_id:
            continue
        html = fetcher.fetch_abs_html(arxiv_id)
        abstract = fetcher.extract_abstract(html)
        if not abstract:
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

    # write to Mongo
    for ws in weeks:
        store.upsert_week_counts(domain["domain"], to_week_datetime(ws), weekly_counts.get(ws, {}))

    # read back and plot
    rows = store.get_counts_last_weeks(domain["domain"], [to_week_datetime(w) for w in weeks])
    df = to_frame(rows)
    pivot = pivot_week_keyword(df)

    popular = top_popular_now(pivot, TOP_N)
    growing = top_growing_last_window(pivot, GROWTH_WINDOW_WEEKS, TOP_N)

    slug = slugify(domain["domain"])
    base = Path(out_dir) / "plots" / slug
    plot_keywords_over_time(pivot, popular, f"{domain['title']} — Top-{TOP_N} popular (last week)", base / "top_popular.png")
    plot_keywords_over_time(pivot, growing, f"{domain['title']} — Top-{TOP_N} growing (last {GROWTH_WINDOW_WEEKS} weeks)", base / "top_growing.png")


def run_all(domains: List[dict], mongo_uri: str, mongo_db: str, api_url: str, user_agent: str, out_dir: str):
    store = MongoStore(mongo_uri, mongo_db)
    api = ArxivApiClient(api_url, user_agent=user_agent, sleep_sec=REQUEST_SLEEP_SEC)
    fetcher = ArxivHtmlFetcher(user_agent=user_agent, sleep_sec=REQUEST_SLEEP_SEC)

    for d in domains:
        run_for_domain(d, store, api, fetcher, out_dir=out_dir)
