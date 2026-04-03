from __future__ import annotations
import time
import re

import requests
from bs4 import BeautifulSoup


class ArxivHtmlFetcher:
    def __init__(self, user_agent: str, sleep_sec: float = 0.5, timeout: int = 30):
        self.headers = {"User-Agent": user_agent}
        self.sleep_sec = sleep_sec
        self.timeout = timeout

    def fetch_abs_html(self, arxiv_id: str) -> str:
        url = f"https://arxiv.org/abs/{arxiv_id}"
        r = requests.get(url, headers=self.headers, timeout=self.timeout)
        r.raise_for_status()
        time.sleep(self.sleep_sec)
        return r.text

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
