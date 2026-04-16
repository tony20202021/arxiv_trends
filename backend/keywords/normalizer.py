"""Лемматизация ключевых слов через spaCy.

Приоритет моделей:
1. en_core_sci_sm (scispacy) — специализирована для научных текстов, если установлена
2. en_core_web_sm — стандартная модель spaCy (fallback)

Установка scispacy (опционально):
    pip install scispacy
    pip install https://s3-us-west-2.amazonaws.com/ai2-s3-public/scispacy/releases/v0.5.4/en_core_sci_sm-0.5.4.tar.gz
"""
from __future__ import annotations
import logging

import spacy

logger = logging.getLogger(__name__)

_nlp = None


def _get_nlp():
    global _nlp
    if _nlp is None:
        # Пробуем scispacy — лучше лемматизирует научные термины
        try:
            import scispacy  # noqa: F401 — проверяем наличие пакета
            _nlp = spacy.load("en_core_sci_sm", disable=["parser", "ner"])
            logger.debug("Лемматизатор: en_core_sci_sm (scispacy)")
        except (ImportError, OSError):
            # scispacy не установлен или модель не загружена — используем стандартную
            _nlp = spacy.load("en_core_web_sm", disable=["parser", "ner"])
            logger.debug("Лемматизатор: en_core_web_sm (spaCy)")
    return _nlp


def lemmatize(word: str) -> str:
    """Возвращает лемму слова в нижнем регистре."""
    nlp = _get_nlp()
    doc = nlp(word.lower())
    if not doc:
        return word.lower()
    return doc[0].lemma_


def lemmatize_batch(words: list[str]) -> list[str]:
    """Батч-лемматизация: быстрее чем вызывать lemmatize() по одному."""
    nlp = _get_nlp()
    results = []
    for doc in nlp.pipe([w.lower() for w in words], batch_size=256):
        results.append(doc[0].lemma_ if doc else doc.text)
    return results
