from __future__ import annotations
import logging
import time
import re

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class ArxivHtmlFetcher:
    def __init__(
        self,
        user_agent: str,
        sleep_sec: float = 0.5,
        timeout: int = 30,
        max_retries: int = 3,
        retry_backoff: float = 2.0,
    ):
        self.headers = {"User-Agent": user_agent}
        self.sleep_sec = sleep_sec
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff

    def fetch_abs_html(self, arxiv_id: str) -> str:
        url = f"https://arxiv.org/abs/{arxiv_id}"
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                logger.debug("Fetching abstract HTML (attempt %d): %s", attempt, url)
                r = requests.get(url, headers=self.headers, timeout=self.timeout)
                r.raise_for_status()
                time.sleep(self.sleep_sec)
                return r.text
            except requests.RequestException as exc:
                last_exc = exc
                wait = self.retry_backoff ** (attempt - 1) * self.sleep_sec
                logger.warning("HTML fetch failed (attempt %d/%d) for %s: %s — retrying in %.1fs",
                               attempt, self.max_retries, arxiv_id, exc, wait)
                time.sleep(wait)

        logger.error("HTML fetch failed after %d attempts for %s", self.max_retries, arxiv_id)
        raise last_exc  # type: ignore[misc]

    def extract_abstract(self, html: str) -> str:
        soup = BeautifulSoup(html, "lxml")
        block = soup.select_one("blockquote.abstract")
        if not block:
            return ""
        descriptor = block.select_one("span.descriptor")
        if descriptor:
            descriptor.extract()
        text = block.get_text(" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        return text
