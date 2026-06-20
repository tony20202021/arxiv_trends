"""Лемматизация и пост-нормализация ключевых слов через spaCy.

Приоритет моделей:
1. en_core_sci_sm (scispacy) — специализирована для научных текстов, если установлена
2. en_core_web_sm — стандартная модель spaCy (fallback)

Установка scispacy (опционально):
    pip install scispacy
    pip install https://s3-us-west-2.amazonaws.com/ai2-s3-public/scispacy/releases/v0.5.4/en_core_sci_sm-0.5.4.tar.gz
"""
from __future__ import annotations
import logging
from typing import Dict

import spacy

from config.constants import MIN_TOKEN_LEN, STOPWORDS_EN
from keywords.canonical import canonicalize_keyword

logger = logging.getLogger(__name__)

_nlp = None


def _get_nlp():
    global _nlp
    if _nlp is None:
        try:
            import scispacy  # noqa: F401
            _nlp = spacy.load("en_core_sci_sm", disable=["parser", "ner"])
            logger.debug("Лемматизатор: en_core_sci_sm (scispacy)")
        except (ImportError, OSError):
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


def lemmatize_phrase(phrase: str) -> str:
    """Лемматизирует каждое слово фразы, сохраняя пробелы."""
    words = phrase.lower().split()
    if not words:
        return ""
    return " ".join(lemmatize(w) for w in words)


def lemmatize_batch(words: list[str]) -> list[str]:
    """Батч-лемматизация: быстрее чем вызывать lemmatize() по одному."""
    nlp = _get_nlp()
    results = []
    for doc in nlp.pipe([w.lower() for w in words], batch_size=256):
        results.append(doc[0].lemma_ if doc else doc.text)
    return results


def normalize_keyword(keyword: str) -> str:
    """Канонизация синонимов + лемматизация (уни- или многословная фраза)."""
    kw = canonicalize_keyword(keyword)
    if not kw:
        return ""
    if " " in kw:
        return lemmatize_phrase(kw)
    return lemmatize(kw)


def normalize_keywords_dict(keywords: Dict[str, int]) -> Dict[str, int]:
    """Пост-нормализация словаря keywords: леммы, синонимы, merge дублей, фильтр стоп-слов."""
    merged: Dict[str, int] = {}
    for kw, count in keywords.items():
        if count <= 0:
            continue
        norm = normalize_keyword(kw)
        if not norm or len(norm) < MIN_TOKEN_LEN:
            continue
        parts = norm.split()
        if not parts or all(p in STOPWORDS_EN for p in parts):
            continue
        merged[norm] = merged.get(norm, 0) + int(count)
    return merged
