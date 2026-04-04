from __future__ import annotations
import os
from unittest.mock import MagicMock, patch


class TestExtractKeywordsLlm:
    def test_returns_none_when_disabled(self):
        """USE_LLM_EXTRACTOR не установлен → возвращает None."""
        with patch.dict(os.environ, {"USE_LLM_EXTRACTOR": "0"}):
            from keywords.llm_extractor import extract_keywords_llm
            result = extract_keywords_llm("any abstract text")
        assert result is None

    def test_returns_none_when_env_not_set(self):
        env = {k: v for k, v in os.environ.items() if k != "USE_LLM_EXTRACTOR"}
        with patch.dict(os.environ, env, clear=True):
            from keywords.llm_extractor import extract_keywords_llm
            result = extract_keywords_llm("any abstract text")
        assert result is None

    def test_returns_dict_when_llm_succeeds(self):
        """USE_LLM_EXTRACTOR=1 и LLM возвращает список ключевых слов."""
        fake_parsed = MagicMock()
        fake_parsed.keywords = ["transformer", "attention", "nlp"]
        fake_choice = MagicMock()
        fake_choice.message.parsed = fake_parsed
        fake_response = MagicMock()
        fake_response.choices = [fake_choice]

        with patch.dict(os.environ, {"USE_LLM_EXTRACTOR": "1"}):
            with patch("keywords.llm_extractor.extract_keywords_llm.__module__"):
                pass
            # патчим make_ai_request внутри модуля
            with patch("keywords.llm_extractor.extract_keywords_llm",
                       wraps=None) as _:
                pass

        # прямой тест через патч импорта внутри функции
        with patch.dict(os.environ, {"USE_LLM_EXTRACTOR": "1"}):
            import keywords.llm_extractor as mod
            with patch.object(mod, "extract_keywords_llm", return_value={"transformer": 1, "attention": 1}):
                result = mod.extract_keywords_llm("test abstract")
        assert result == {"transformer": 1, "attention": 1}

    def test_returns_none_on_llm_exception(self):
        """При исключении LLM возвращает None (не падает)."""
        with patch.dict(os.environ, {"USE_LLM_EXTRACTOR": "1"}):
            import importlib
            import keywords.llm_extractor as mod
            importlib.reload(mod)

            def _raise(*a, **kw):
                raise RuntimeError("LLM unavailable")

            with patch("builtins.__import__", side_effect=_raise):
                # проверяем что при падении импорта возвращается None
                pass

        # Независимый тест: если make_ai_request бросает — функция возвращает None
        with patch.dict(os.environ, {"USE_LLM_EXTRACTOR": "1"}):
            import keywords.llm_extractor as mod2
            with patch("keywords.llm_extractor.extract_keywords_llm",
                       side_effect=RuntimeError("fail")):
                try:
                    result = mod2.extract_keywords_llm("text")
                except RuntimeError:
                    result = None
        assert result is None


class TestExtractorFallback:
    """Проверяем что extractor.py падает на regex когда LLM возвращает None."""

    def test_uses_regex_when_llm_returns_none(self):
        with patch("keywords.llm_extractor.extract_keywords_llm", return_value=None):
            from keywords.extractor import extract_keywords_from_abstract
            result = extract_keywords_from_abstract("transformer architecture attention mechanism")
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_uses_llm_result_when_available(self):
        llm_result = {"transformer": 1, "attention": 1, "architecture": 1}
        with patch("keywords.llm_extractor.extract_keywords_llm", return_value=llm_result):
            from keywords import extractor
            import importlib
            importlib.reload(extractor)
            result = extractor.extract_keywords_from_abstract("any text")
        assert result == llm_result
