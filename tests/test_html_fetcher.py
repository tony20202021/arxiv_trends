from __future__ import annotations
from unittest.mock import MagicMock, patch

import pytest
import requests

from arxiv.html_fetcher import ArxivHtmlFetcher


ABSTRACT_HTML = """
<html><body>
<blockquote class="abstract mathjax">
  <span class="descriptor">Abstract:</span>
  We propose a novel  method for   deep learning.
  It achieves state-of-the-art results.
</blockquote>
</body></html>
"""

NO_ABSTRACT_HTML = "<html><body><p>No abstract here.</p></body></html>"


def _make_fetcher(**kwargs) -> ArxivHtmlFetcher:
    return ArxivHtmlFetcher(user_agent="test/0.1", sleep_sec=0, **kwargs)


def _mock_response(html: str = ABSTRACT_HTML, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.text = html
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError()
    return resp


class TestArxivHtmlFetcherFetch:
    def test_returns_html_string(self):
        fetcher = _make_fetcher()
        with patch("requests.get", return_value=_mock_response()):
            result = fetcher.fetch_abs_html("2401.00001")
        assert isinstance(result, str)
        assert "abstract" in result.lower()

    def test_correct_url_built(self):
        fetcher = _make_fetcher()
        with patch("requests.get", return_value=_mock_response()) as mock_get:
            fetcher.fetch_abs_html("2401.00001")
        url = mock_get.call_args[0][0]
        assert url == "https://arxiv.org/abs/2401.00001"

    def test_user_agent_sent(self):
        fetcher = _make_fetcher()
        with patch("requests.get", return_value=_mock_response()) as mock_get:
            fetcher.fetch_abs_html("2401.00001")
        assert mock_get.call_args[1]["headers"]["User-Agent"] == "test/0.1"

    def test_retries_on_connection_error_then_succeeds(self):
        fetcher = _make_fetcher(max_retries=3)
        ok = _mock_response()
        effects = [requests.ConnectionError(), requests.ConnectionError(), ok]
        with patch("requests.get", side_effect=effects) as mock_get:
            result = fetcher.fetch_abs_html("2401.00001")
        assert mock_get.call_count == 3
        assert "abstract" in result.lower()

    def test_raises_after_max_retries(self):
        fetcher = _make_fetcher(max_retries=2)
        with patch("requests.get", side_effect=requests.ConnectionError("fail")):
            with pytest.raises(requests.ConnectionError):
                fetcher.fetch_abs_html("2401.00001")

    def test_http_error_triggers_retry_and_raises(self):
        fetcher = _make_fetcher(max_retries=2)
        bad = _mock_response(status_code=429)
        with patch("requests.get", return_value=bad):
            with pytest.raises(requests.HTTPError):
                fetcher.fetch_abs_html("2401.00001")


class TestArxivHtmlFetcherExtractAbstract:
    def test_extracts_abstract_text(self):
        fetcher = _make_fetcher()
        text = fetcher.extract_abstract(ABSTRACT_HTML)
        assert "novel" in text
        assert "deep learning" in text

    def test_descriptor_span_removed(self):
        fetcher = _make_fetcher()
        text = fetcher.extract_abstract(ABSTRACT_HTML)
        assert "Abstract:" not in text

    def test_whitespace_normalized(self):
        fetcher = _make_fetcher()
        text = fetcher.extract_abstract(ABSTRACT_HTML)
        assert "  " not in text  # двойные пробелы убраны

    def test_missing_abstract_returns_empty(self):
        fetcher = _make_fetcher()
        assert fetcher.extract_abstract(NO_ABSTRACT_HTML) == ""

    def test_empty_html_returns_empty(self):
        fetcher = _make_fetcher()
        assert fetcher.extract_abstract("") == ""
