"""KeyBERT extractor (v9) — zero-shot, без обучения на корпусе."""
from __future__ import annotations
import logging
import os
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_kw_model = None


def _get_keybert():
    global _kw_model
    if _kw_model is not None:
        return _kw_model
    try:
        from keybert import KeyBERT

        model_name = os.getenv("KEYBERT_MODEL", "all-MiniLM-L6-v2")
        _kw_model = KeyBERT(model=model_name)
        logger.debug("KeyBERT loaded: %s", model_name)
        return _kw_model
    except Exception as exc:
        logger.debug("KeyBERT unavailable: %s", exc)
        return None


def extract_keywords_keybert(abstract: str, top_n: int = 20) -> Dict[str, int]:
    """Извлечь ключевые слова через KeyBERT. Пустой dict если библиотека недоступна."""
    if os.getenv("USE_KEYBERT", "1").strip() == "0":
        return {}

    model = _get_keybert()
    if model is None:
        return {}

    text = (abstract or "").strip()
    if not text:
        return {}

    try:
        keywords = model.extract_keywords(
            text,
            keyphrase_ngram_range=(1, 3),
            stop_words="english",
            top_n=top_n,
            use_mmr=True,
            diversity=0.4,
        )
    except Exception as exc:
        logger.warning("KeyBERT extraction failed: %s", exc)
        return {}

    if not keywords:
        return {}

    result: Dict[str, int] = {}
    for phrase, score in keywords:
        phrase_lower = phrase.lower().strip()
        if len(phrase_lower) < 3:
            continue
        result[phrase_lower] = max(1, int(float(score) * 100))
    return result
