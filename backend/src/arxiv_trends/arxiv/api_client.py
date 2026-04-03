from __future__ import annotations
import time
import urllib.parse
from typing import Dict, List, Optional, Tuple

import feedparser
import requests


class ArxivApiClient:
    def __init__(self, base_url: str, user_agent: str, sleep_sec: float = 0.5, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.headers = {"User-Agent": user_agent}
        self.sleep_sec = sleep_sec
        self.timeout = timeout

    def query(
        self,
        search_query: str,
        start: int = 0,
        max_results: int = 100,
        sort_by: str = "submittedDate",
        sort_order: str = "descending",
        submitted_date_range: Optional[Tuple[str, str]] = None,
    ) -> feedparser.FeedParserDict:
        params = {
            "search_query": search_query,
            "start": start,
            "max_results": max_results,
            "sortBy": sort_by,
            "sortOrder": sort_order,
        }
        if submitted_date_range:
            lo, hi = submitted_date_range
            params["submittedDate"] = f"[{lo}+TO+{hi}]"
        url = self.base_url + "?" + urllib.parse.urlencode(params, safe=":+[]")
        resp = requests.get(url, headers=self.headers, timeout=self.timeout)
        resp.raise_for_status()
        time.sleep(self.sleep_sec)
        return feedparser.parse(resp.text)

    @staticmethod
    def parse_entries(feed: feedparser.FeedParserDict) -> List[Dict]:
        out = []
        for e in feed.entries:
            out.append({
                "id": e.get("id", ""),
                "title": (e.get("title", "") or "").strip().replace("\n", " "),
                "published": e.get("published", ""),
            })
        return out
