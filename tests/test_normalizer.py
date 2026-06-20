"""Тесты пост-нормализации keywords."""
from __future__ import annotations

from keywords.normalizer import normalize_keywords_dict, normalize_keyword


class TestNormalizeKeywords:
    def test_merge_lemma_forms(self):
        raw = {"transformers": 2, "transformer": 3}
        result = normalize_keywords_dict(raw)
        assert "transformer" in result
        assert result["transformer"] == 5
        assert "transformers" not in result

    def test_canonical_llm(self):
        assert normalize_keyword("large language models") == "llm"

    def test_stopwords_filtered(self):
        result = normalize_keywords_dict({"the": 1, "transformer": 2})
        assert "the" not in result
        assert "transformer" in result
