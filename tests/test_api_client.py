from __future__ import annotations
from unittest.mock import MagicMock, patch, call
import time

import pytest
import requests

from arxiv.api_client import ArxivApiClient


FAKE_ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <title>Test Paper One</title>
    <published>2024-01-01T00:00:00Z</published>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2401.00002v1</id>
    <title>Test Paper\nTwo</title>
    <published>2024-01-02T00:00:00Z</published>
  </entry>
</feed>"""


def _make_client(**kwargs) -> ArxivApiClient:
    kwargs.setdefault("sleep_sec", 0)
    return ArxivApiClient(
        base_url="https://export.arxiv.org/api/query",
        user_agent="test-agent/0.1",
        **kwargs,
    )


def _mock_response(text: str = FAKE_ATOM, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
    return resp


class TestArxivApiClientQuery:
    def test_returns_feedparser_dict(self):
        client = _make_client()
        with patch("requests.get", return_value=_mock_response()) as mock_get:
            feed = client.query("cat:cs.LG")
        assert hasattr(feed, "entries")
        mock_get.assert_called_once()

    def test_url_contains_search_query(self):
        client = _make_client()
        with patch("requests.get", return_value=_mock_response()) as mock_get:
            client.query("cat:cs.LG", start=10, max_results=50)
        url = mock_get.call_args[0][0]
        assert "cat%3Acs.LG" in url or "cat:cs.LG" in url
        assert "start=10" in url
        assert "max_results=50" in url

    def test_submitted_date_range_appended(self):
        client = _make_client()
        with patch("requests.get", return_value=_mock_response()) as mock_get:
            client.query("cat:cs.LG", submitted_date_range=("202401010000", "202401072359"))
        url = mock_get.call_args[0][0]
        assert "submittedDate" in url

    def test_user_agent_header_sent(self):
        client = _make_client()
        with patch("requests.get", return_value=_mock_response()) as mock_get:
            client.query("cat:cs.LG")
        headers = mock_get.call_args[1]["headers"]
        assert headers["User-Agent"] == "test-agent/0.1"

    def test_raises_after_max_retries(self):
        client = _make_client(max_retries=2, sleep_sec=0)
        with patch("requests.get", side_effect=requests.ConnectionError("timeout")):
            with pytest.raises(requests.ConnectionError):
                client.query("cat:cs.LG")

    def test_retries_on_connection_error_then_succeeds(self):
        client = _make_client(max_retries=3, sleep_sec=0)
        ok = _mock_response()
        side_effects = [requests.ConnectionError("err"), requests.ConnectionError("err"), ok]
        with patch("requests.get", side_effect=side_effects) as mock_get:
            feed = client.query("cat:cs.LG")
        assert mock_get.call_count == 3
        assert hasattr(feed, "entries")

    def test_http_error_triggers_retry(self):
        client = _make_client(max_retries=2, sleep_sec=0)
        bad = _mock_response(status_code=503)
        with patch("requests.get", return_value=bad):
            with pytest.raises(requests.HTTPError):
                client.query("cat:cs.LG")


class TestArxivApiClientParseEntries:
    def test_parses_ids_and_titles(self):
        client = _make_client()
        with patch("requests.get", return_value=_mock_response()):
            feed = client.query("cat:cs.LG")
        entries = client.parse_entries(feed)
        assert len(entries) == 2
        assert entries[0]["id"] == "http://arxiv.org/abs/2401.00001v1"
        assert entries[0]["title"] == "Test Paper One"

    def test_newlines_stripped_from_title(self):
        client = _make_client()
        with patch("requests.get", return_value=_mock_response()):
            feed = client.query("cat:cs.LG")
        entries = client.parse_entries(feed)
        assert "\n" not in entries[1]["title"]

    def test_empty_feed_returns_empty_list(self):
        empty_feed = MagicMock()
        empty_feed.entries = []
        assert ArxivApiClient.parse_entries(empty_feed) == []
