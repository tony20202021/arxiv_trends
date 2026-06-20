"""Реестр алгоритмов извлечения ключевых слов.

Ключ — строка формата "N_name":
  N    — целое число (записывается в articles.keyword_extractor_version, индексируется в БД)
  name — короткий идентификатор алгоритма

Для смены активного алгоритма: изменить ACTIVE_EXTRACTOR_KEY.
"""
from __future__ import annotations
from typing import Callable, Dict

from keywords.ensemble import merge_extractors


class ExtractorSpec:
    def __init__(self, db_id: int, label: str, fn: Callable[[str], Dict[str, int]], max_score: int = 1):
        self.db_id = db_id
        self.label = label
        self.fn = fn
        self.max_score = max_score

    def __repr__(self) -> str:
        return f"ExtractorSpec(db_id={self.db_id}, label={self.label!r})"


# ------------------------------------------------------------------ loaders

def _v1(abstract: str) -> Dict[str, int]:
    from keywords.extractor import _regex_extract
    return _regex_extract(abstract)


def _v2(abstract: str) -> Dict[str, int]:
    from keywords.llm_extractor import extract_keywords_llm
    result = extract_keywords_llm(abstract)
    if result is None:
        raise RuntimeError(
            "2_llm: LLM недоступен. Убедитесь что USE_LLM_EXTRACTOR=1 и API настроен в .env"
        )
    return result


_sklearn_extractor = None


def _get_sklearn_extractor():
    global _sklearn_extractor
    if _sklearn_extractor is None:
        from sklearn.feature_extraction.text import CountVectorizer
        from config.constants import STOPWORDS_EN, TOKEN_PATTERN
        _sklearn_extractor = CountVectorizer(
            stop_words=list(STOPWORDS_EN),
            ngram_range=(1, 2),
            min_df=1,
            max_features=500,
            token_pattern=TOKEN_PATTERN,
        )
    return _sklearn_extractor


def _v3(abstract: str) -> Dict[str, int]:
    from config.constants import STOPWORDS_EN
    vec = _get_sklearn_extractor()
    try:
        count_matrix = vec.fit_transform([abstract or ""])
    except ValueError:
        return {}
    counts_arr = count_matrix.toarray()[0]
    feature_names = vec.get_feature_names_out()
    result: Dict[str, int] = {}
    for i, count in enumerate(counts_arr):
        if count == 0:
            continue
        term = feature_names[i]
        if any(p in STOPWORDS_EN for p in term.split()):
            continue
        if len(term) < 3:
            continue
        result[term] = int(count)
    return result


def _v4(abstract: str) -> Dict[str, int]:
    from keywords.gensim_extractor import extract_keywords_gensim
    return extract_keywords_gensim(abstract)


def _v8(abstract: str) -> Dict[str, int]:
    raise NotImplementedError("8_ensemble_137: не реализован")


def _v9(abstract: str) -> Dict[str, int]:
    from keywords.keybert_extractor import extract_keywords_keybert
    return extract_keywords_keybert(abstract)


_yake_extractor_v7 = None
_yake_extractor_v11 = None


def _get_yake_extractor_v7():
    global _yake_extractor_v7
    if _yake_extractor_v7 is None:
        import yake
        _yake_extractor_v7 = yake.KeywordExtractor(lan="en", n=3, dedupLim=0.7, top=30, features=None)
    return _yake_extractor_v7


def _get_yake_extractor_v11():
    global _yake_extractor_v11
    if _yake_extractor_v11 is None:
        import yake
        _yake_extractor_v11 = yake.KeywordExtractor(lan="en", n=3, dedupLim=0.5, top=30, features=None)
    return _yake_extractor_v11


def _yake_extract(abstract: str, get_extractor) -> Dict[str, int]:
    from config.constants import STOPWORDS_EN
    extractor = get_extractor()
    try:
        keywords = extractor.extract_keywords(abstract or "")
    except Exception:
        return {}
    result: Dict[str, int] = {}
    rank = len(keywords)
    for phrase, _score in keywords:
        phrase_lower = phrase.lower().strip()
        words = phrase_lower.split()
        if not words or all(w in STOPWORDS_EN for w in words):
            continue
        if len(phrase_lower) < 3:
            continue
        result[phrase_lower] = max(1, rank)
        rank -= 1
    return result


def _v7(abstract: str) -> Dict[str, int]:
    return _yake_extract(abstract, _get_yake_extractor_v7)


def _v11(abstract: str) -> Dict[str, int]:
    return _yake_extract(abstract, _get_yake_extractor_v11)


def _v20(abstract: str) -> Dict[str, int]:
    """20_ensemble: v1+v3+v11 без пост-нормализации (legacy)."""
    weights = {"v1": 0.5, "v3": 1.0, "v11": 2.0}
    raw = {"v1": _v1(abstract), "v3": _v3(abstract), "v11": _v11(abstract)}
    merged: Dict[str, float] = {}
    for src, result in raw.items():
        if not result:
            continue
        max_val = max(result.values())
        w = weights[src]
        for kw, score in result.items():
            merged[kw] = merged.get(kw, 0.0) + w * score / max_val
    if not merged:
        return {}
    max_merged = max(merged.values())
    return {kw: max(1, int(v / max_merged * 100)) for kw, v in merged.items()}


def _v30(abstract: str) -> Dict[str, int]:
    """30_ensemble: v1+v3+v11+v4(gensim)+v9(KeyBERT) с пост-нормализацией.

    Веса: v1=0.5, v3=1.0, v11=2.0 (статистика), v4=1.0 (corpus IDF), v9=0.75 (semantic).
    Если gensim/KeyBERT недоступны — ветка даёт {} и не ломает ансамбль.
    """
    return merge_extractors(
        abstract,
        branches={
            "v1":  (_v1, 0.5),
            "v3":  (_v3, 1.0),
            "v11": (_v11, 2.0),
            "v4":  (_v4, 1.0),
            "v9":  (_v9, 0.75),
        },
        scale=100,
    )


EXTRACTORS: Dict[str, ExtractorSpec] = {
    "1_count_stopwords": ExtractorSpec(1,  "count+stopwords",       _v1),
    "2_llm":             ExtractorSpec(2,  "LLM",                   _v2),
    "3_tfidf_sklearn":   ExtractorSpec(3,  "bigram-TF/sklearn",     _v3),
    "4_tfidf_gensim":    ExtractorSpec(4,  "TF-IDF/gensim",         _v4,  max_score=100),
    "7_yake":            ExtractorSpec(7,  "YAKE+trigrams",         _v7,  max_score=30),
    "8_ensemble_137":    ExtractorSpec(8,  "ensemble(1+3+7)",       _v8),
    "9_keybert":         ExtractorSpec(9,  "KeyBERT",               _v9,  max_score=100),
    "11_yake":           ExtractorSpec(11, "YAKE+trigrams,d0.5",    _v11, max_score=30),
    "20_ensemble":       ExtractorSpec(20, "ensemble(1+3+11)",      _v20, max_score=100),
    "30_ensemble":       ExtractorSpec(30, "ensemble(1+3+4+9+11)",  _v30, max_score=100),
}

ACTIVE_EXTRACTOR_KEY: str = "30_ensemble"
ACTIVE_EXTRACTOR: ExtractorSpec = EXTRACTORS[ACTIVE_EXTRACTOR_KEY]

# Экстракторы, использующие corpus gensim (v4) — при смене gensim_model_version нужен re-extract
_GENSIM_EXTRACTOR_KEYS = frozenset({"4_tfidf_gensim", "30_ensemble"})


def active_extractor_uses_gensim() -> bool:
    return ACTIVE_EXTRACTOR_KEY in _GENSIM_EXTRACTOR_KEYS


def extract_keywords(abstract: str) -> Dict[str, int]:
    return ACTIVE_EXTRACTOR.fn(abstract)


def extractor_info() -> str:
    return f"v{ACTIVE_EXTRACTOR.db_id} ({ACTIVE_EXTRACTOR.label})"
