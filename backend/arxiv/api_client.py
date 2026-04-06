from __future__ import annotations
import logging
import time
import urllib.parse
from typing import Dict, List, Optional, Tuple

import feedparser
import requests

logger = logging.getLogger(__name__)


class ArxivApiClient:
    def __init__(
        self,
        base_url: str,
        user_agent: str,
        sleep_sec: float = 0.5,
        timeout: int = 60,
        max_retries: int = 5,
        retry_backoff: float = 2.0,
        rate_limit_sleep_sec: float = 60.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.headers = {"User-Agent": user_agent}
        self.sleep_sec = sleep_sec
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.rate_limit_sleep_sec = rate_limit_sleep_sec
        self._last_request_at: float = 0.0

    def query(
        self,
        search_query: str,
        start: int = 0,
        max_results: int = 100,
        sort_by: str = "submittedDate",
        sort_order: str = "descending",
        submitted_date_range: Optional[Tuple[str, str]] = None,
    ) -> feedparser.FeedParserDict:
        if submitted_date_range:
            lo, hi = submitted_date_range
            query = f"({search_query}) AND submittedDate:[{lo} TO {hi}]"
        else:
            query = search_query
        params = {
            "search_query": query,
            "start": start,
            "max_results": max_results,
            "sortBy": sort_by,
            "sortOrder": sort_order,
        }
        url = self.base_url + "?" + urllib.parse.urlencode(params, safe=":+[]")

        # Соблюдаем минимальный интервал между запросами
        elapsed = time.time() - self._last_request_at
        if elapsed < self.sleep_sec:
            time.sleep(self.sleep_sec - elapsed)

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                logger.debug("arXiv API request (attempt %d): %s", attempt, url)
                resp = requests.get(url, headers=self.headers, timeout=self.timeout)
                self._last_request_at = time.time()
                resp.raise_for_status()
                return feedparser.parse(resp.text)
            except requests.HTTPError as exc:
                last_exc = exc
                if exc.response is not None and exc.response.status_code == 429:
                    wait = self.rate_limit_sleep_sec * attempt  # 60, 120, 180...
                    logger.warning("arXiv API rate limit (attempt %d/%d) — retrying in %.0fs",
                                   attempt, self.max_retries, wait)
                else:
                    wait = self.retry_backoff ** attempt
                    logger.warning("arXiv API request failed (attempt %d/%d): %s — retrying in %.1fs",
                                   attempt, self.max_retries, exc, wait)
                time.sleep(wait)
            except requests.RequestException as exc:
                last_exc = exc
                wait = self.retry_backoff ** attempt
                logger.warning("arXiv API request failed (attempt %d/%d): %s — retrying in %.1fs",
                               attempt, self.max_retries, exc, wait)
                time.sleep(wait)

        logger.error("arXiv API request failed after %d attempts: %s", self.max_retries, last_exc)
        raise last_exc  # type: ignore[misc]

    @staticmethod
    def parse_entries(feed: feedparser.FeedParserDict) -> List[Dict]:
        out = []
        for e in feed.entries:
            # arxiv_primary_category — первичная категория
            # published — дата появления на arXiv (может быть позже submittedDate)
            # arxiv_journal_ref и tags содержат submittedDate через updated/published
            out.append({
                "id": e.get("id", ""),
                "title": (e.get("title", "") or "").strip().replace("\n", " "),
                "published": e.get("published", ""),
                "updated": e.get("updated", ""),
                "abstract": " ".join((e.get("summary", "") or "").split()),
            })
        return out
