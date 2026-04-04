"""LLM-based keyword extractor.

Использует openai_llm.py (OpenAI-совместимый клиент).
При недоступности LLM автоматически переключается на regex-fallback.

Переменные окружения (задаются в .env):
    OPENAI_LLM_URL      — base_url OpenAI-совместимого API
    OPENAI_LLM_API_KEY  — API ключ
    OPENAI_LLM_MODEL    — модель (например, gpt-4o-mini)
    USE_LLM_EXTRACTOR   — "1" чтобы включить LLM (по умолчанию выключен)
"""
from __future__ import annotations
import logging
import os
from typing import Dict

from pydantic import BaseModel

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a scientific keyword extractor. "
    "Given an abstract from an arXiv paper, extract the most important technical keywords and concepts. "
    "Focus on methods, architectures, tasks, and domain-specific terms. "
    "Exclude generic words and stopwords. "
    "Return each keyword in lowercase."
)

_USER_PROMPT_TEMPLATE = (
    "Extract up to 20 technical keywords from this abstract. "
    "Return them as a JSON list of strings.\n\nAbstract:\n{abstract}"
)


class KeywordList(BaseModel):
    keywords: list[str]


def extract_keywords_llm(abstract: str) -> Dict[str, int] | None:
    """Попытаться извлечь ключевые слова через LLM.

    Возвращает Dict[keyword, count=1] или None если LLM недоступен/отключён.
    """
    if os.getenv("USE_LLM_EXTRACTOR", "").strip() != "1":
        return None

    try:
        from llm.client import make_ai_request

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _USER_PROMPT_TEMPLATE.format(abstract=abstract)},
        ]
        response = make_ai_request(messages, KeywordList)
        parsed: KeywordList = response.choices[0].message.parsed
        keywords = [kw.strip().lower() for kw in parsed.keywords if kw.strip()]
        logger.debug("LLM extracted %d keywords", len(keywords))
        return {kw: 1 for kw in keywords if kw}
    except Exception as exc:
        logger.warning("LLM extraction failed, falling back to regex: %s", exc)
        return None
