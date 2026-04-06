"""Тесты для keywords/registry.py — реестра алгоритмов экстракции."""
from __future__ import annotations
import re
import pytest
from unittest.mock import patch


class TestExtractorsDict:
    def test_has_all_six_keys(self):
        from keywords.registry import EXTRACTORS
        assert len(EXTRACTORS) == 6

    def test_key_format_is_n_name(self):
        from keywords.registry import EXTRACTORS
        pattern = re.compile(r"^\d+_\w+$")
        for key in EXTRACTORS:
            assert pattern.match(key), f"Ключ {key!r} не соответствует формату 'N_name'"

    def test_db_ids_are_unique(self):
        from keywords.registry import EXTRACTORS
        ids = [spec.db_id for spec in EXTRACTORS.values()]
        assert len(ids) == len(set(ids)), "db_id должны быть уникальными"

    def test_db_ids_match_key_prefix(self):
        from keywords.registry import EXTRACTORS
        for key, spec in EXTRACTORS.items():
            expected = int(key.split("_")[0])
            assert spec.db_id == expected, f"{key}: db_id={spec.db_id}, ожидалось {expected}"

    def test_all_specs_have_label(self):
        from keywords.registry import EXTRACTORS
        for key, spec in EXTRACTORS.items():
            assert spec.label, f"{key}: label не задан"

    def test_all_specs_have_callable(self):
        from keywords.registry import EXTRACTORS
        for key, spec in EXTRACTORS.items():
            assert callable(spec.fn), f"{key}: fn не callable"


class TestActiveExtractor:
    def test_active_key_exists_in_extractors(self):
        from keywords.registry import EXTRACTORS, ACTIVE_EXTRACTOR_KEY
        assert ACTIVE_EXTRACTOR_KEY in EXTRACTORS

    def test_active_extractor_is_v1(self):
        from keywords.registry import ACTIVE_EXTRACTOR
        assert ACTIVE_EXTRACTOR.db_id == 1

    def test_active_extractor_label_nonempty(self):
        from keywords.registry import ACTIVE_EXTRACTOR
        assert ACTIVE_EXTRACTOR.label

    def test_extract_keywords_returns_dict(self):
        from keywords.registry import extract_keywords
        result = extract_keywords("transformer neural network architecture")
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_extract_keywords_empty_abstract(self):
        from keywords.registry import extract_keywords
        result = extract_keywords("")
        assert result == {}

    def test_extractor_info_format(self):
        from keywords.registry import extractor_info, ACTIVE_EXTRACTOR
        info = extractor_info()
        assert f"v{ACTIVE_EXTRACTOR.db_id}" in info
        assert ACTIVE_EXTRACTOR.label in info


class TestUnimplementedExtractors:
    @pytest.mark.parametrize("key", ["3_tfidf_sklearn", "4_tfidf_gensim", "5_keybert", "6_yake"])
    def test_raises_not_implemented(self, key):
        from keywords.registry import EXTRACTORS
        spec = EXTRACTORS[key]
        with pytest.raises(NotImplementedError):
            spec.fn("any abstract text")

    def test_v2_raises_when_llm_unavailable(self):
        """_v2 без LLM должен бросить RuntimeError (не NotImplementedError)."""
        from keywords.registry import EXTRACTORS
        with patch("keywords.llm_extractor.extract_keywords_llm", return_value=None):
            with pytest.raises(RuntimeError, match="LLM недоступен"):
                EXTRACTORS["2_llm"].fn("any text")
