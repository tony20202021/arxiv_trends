"""Generic OpenAI-compatible LLM client.

Переменные окружения:
    OPENAI_LLM_URL      — base_url API
    OPENAI_LLM_API_KEY  — API ключ
    OPENAI_LLM_MODEL    — модель по умолчанию
"""
from __future__ import annotations
import os
from typing import Type, TypeVar

from openai import OpenAI
from pydantic import BaseModel

TEMPERATURE_DEFAULT = 0
SEED_DEFAULT = 42

T = TypeVar("T", bound=BaseModel)


def _client() -> OpenAI:
    return OpenAI(
        base_url=os.getenv("OPENAI_LLM_URL"),
        api_key=os.getenv("OPENAI_LLM_API_KEY", ""),
    )


def _default_model() -> str:
    return os.getenv("OPENAI_LLM_MODEL", "")


def make_ai_request(messages: list, return_type: Type[T], model_name: str | None = None) -> T:
    """Структурированный запрос — возвращает распарсенный Pydantic-объект."""
    return _client().beta.chat.completions.parse(
        model=model_name or _default_model(),
        messages=messages,
        response_format=return_type,
        temperature=TEMPERATURE_DEFAULT,
        seed=SEED_DEFAULT,
    )


def make_simple_ai_request(messages: list, model_name: str | None = None):
    """Простой запрос — возвращает ChatCompletion с plain text."""
    return _client().chat.completions.create(
        model=model_name or _default_model(),
        messages=messages,
        temperature=TEMPERATURE_DEFAULT,
        seed=SEED_DEFAULT,
    )
