from __future__ import annotations

import pytest

from keywords.extractor import extract_keywords_from_abstract


class TestExtractKeywordsFromAbstract:
    def test_empty_string(self):
        result = extract_keywords_from_abstract("")
        assert result == {}

    def test_none_like_empty(self):
        # функция принимает пустую строку (None обрабатывается через `abstract or ""`)
        result = extract_keywords_from_abstract("")
        assert isinstance(result, dict)

    def test_returns_dict_of_counts(self):
        text = "neural neural network"
        result = extract_keywords_from_abstract(text)
        assert "neural" in result
        assert result["neural"] == 2
        assert "network" in result

    def test_stopwords_excluded(self):
        text = "the and for are was with this"
        result = extract_keywords_from_abstract(text)
        for sw in ["the", "and", "for", "are", "was", "with", "this"]:
            assert sw not in result

    def test_short_tokens_excluded(self):
        # MIN_TOKEN_LEN == 3, поэтому 1-2 символьные слова должны быть отброшены
        text = "ab cd ef transformer"
        result = extract_keywords_from_abstract(text)
        assert "ab" not in result
        assert "cd" not in result
        assert "transformer" in result

    def test_case_insensitive(self):
        text = "Transformer transformer TRANSFORMER"
        result = extract_keywords_from_abstract(text)
        assert result.get("transformer", 0) == 3

    def test_real_abstract(self):
        abstract = (
            "We propose a novel transformer-based architecture for multi-label "
            "classification of scientific documents. Our model achieves state-of-the-art "
            "performance on benchmark datasets for natural language processing tasks."
        )
        result = extract_keywords_from_abstract(abstract)
        assert isinstance(result, dict)
        assert len(result) > 0
        # ключевые слова предметной области должны присутствовать
        assert "transformer" in result or "architecture" in result or "classification" in result
