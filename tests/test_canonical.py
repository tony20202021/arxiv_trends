"""Тесты канонизации синонимов."""
from __future__ import annotations

from keywords.canonical import canonicalize_keyword


class TestCanonicalize:
    def test_llm_variants(self):
        assert canonicalize_keyword("Large Language Models") == "llm"
        assert canonicalize_keyword("large language model") == "llm"

    def test_moe(self):
        assert canonicalize_keyword("mixture of experts") == "moe"

    def test_unknown_passthrough(self):
        assert canonicalize_keyword("Transformer") == "transformer"
