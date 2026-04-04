"""Лемматизация ключевых слов через spaCy en_core_web_sm (CPU)."""
from __future__ import annotations
import spacy

_nlp = None


def _get_nlp():
    global _nlp
    if _nlp is None:
        # Загружаем только лемматизатор — быстро, без parser/ner
        _nlp = spacy.load("en_core_web_sm", disable=["parser", "ner"])
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
