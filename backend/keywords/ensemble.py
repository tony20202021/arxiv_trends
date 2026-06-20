"""Объединение выходов нескольких экстракторов с пост-нормализацией."""
from __future__ import annotations
from typing import Callable, Dict

from keywords.normalizer import normalize_keywords_dict


def merge_extractors(
    abstract: str,
    branches: Dict[str, tuple[Callable[[str], Dict[str, int]], float]],
    scale: int = 100,
) -> Dict[str, int]:
    """Взвешенный ансамбль: каждая ветка нормализуется (леммы + синонимы), затем merge.

    Args:
        abstract: текст абстракта
        branches: {имя: (fn, weight)} — fn(abstract) -> {keyword: score}
        scale: итоговый диапазон score (1..scale)
    """
    merged: Dict[str, float] = {}
    for _name, (fn, weight) in branches.items():
        if weight <= 0:
            continue
        try:
            raw = fn(abstract)
        except Exception:
            continue
        if not raw:
            continue
        normalized = normalize_keywords_dict(raw)
        if not normalized:
            continue
        max_val = max(normalized.values())
        for kw, score in normalized.items():
            merged[kw] = merged.get(kw, 0.0) + weight * score / max_val

    if not merged:
        return {}
    max_merged = max(merged.values())
    return {kw: max(1, int(v / max_merged * scale)) for kw, v in merged.items()}
