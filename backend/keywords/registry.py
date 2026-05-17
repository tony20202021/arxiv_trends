"""Реестр алгоритмов извлечения ключевых слов.

Ключ — строка формата "N_name":
  N    — целое число (записывается в articles.keyword_extractor_version, индексируется в БД)
  name — короткий идентификатор алгоритма

Для смены активного алгоритма: изменить ACTIVE_EXTRACTOR_KEY.
Для добавления нового алгоритма: добавить запись в EXTRACTORS и функцию-загрузчик.
"""
from __future__ import annotations
from typing import Callable, Dict


# ------------------------------------------------------------------ spec

class ExtractorSpec:
    def __init__(self, db_id: int, label: str, fn: Callable[[str], Dict[str, int]]):
        self.db_id = db_id   # число в articles.keyword_extractor_version
        self.label = label   # человекочитаемое имя (для логов и графиков)
        self.fn = fn         # функция (abstract: str) -> Dict[keyword, count]

    def __repr__(self) -> str:
        return f"ExtractorSpec(db_id={self.db_id}, label={self.label!r})"


# ------------------------------------------------------------------ loaders (lazy imports, чтобы не тянуть зависимости при старте)

def _v1(abstract: str) -> Dict[str, int]:
    """1_count_stopwords: токенизация regex + лемматизация + стоп-слова."""
    from keywords.extractor import _regex_extract
    return _regex_extract(abstract)


def _v2(abstract: str) -> Dict[str, int]:
    """2_llm: извлечение через OpenAI-совместимый LLM (требует USE_LLM_EXTRACTOR=1)."""
    from keywords.llm_extractor import extract_keywords_llm
    result = extract_keywords_llm(abstract)
    if result is None:
        raise RuntimeError(
            "2_llm: LLM недоступен. Убедитесь что USE_LLM_EXTRACTOR=1 и API настроен в .env"
        )
    return result


_sklearn_extractor = None


def _get_sklearn_extractor():
    """Ленивая инициализация TfidfVectorizer."""
    global _sklearn_extractor
    if _sklearn_extractor is None:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from config.constants import STOPWORDS_EN
        _sklearn_extractor = TfidfVectorizer(
            stop_words=list(STOPWORDS_EN),
            ngram_range=(1, 2),   # уни- и биграммы (ловит "neural network", "diffusion model")
            min_df=1,
            max_features=500,
            token_pattern=r"[a-zA-Z][a-zA-Z0-9\-]{2,}",
        )
    return _sklearn_extractor


def _v3(abstract: str) -> Dict[str, int]:
    """3_tfidf_sklearn: TF-IDF (sklearn) с биграммами для одного абстракта.

    Использует per-document TF-IDF (fit+transform на одном тексте).
    Главное преимущество перед v1 — захватывает биграммы типа
    «neural network», «diffusion model», «attention mechanism».
    Веса масштабируются в диапазон 1–100.
    """
    import numpy as np
    from config.constants import STOPWORDS_EN

    vec = _get_sklearn_extractor()
    try:
        tfidf_matrix = vec.fit_transform([abstract or ""])
    except ValueError:
        return {}

    scores = tfidf_matrix.toarray()[0]
    feature_names = vec.get_feature_names_out()

    pairs = [(feature_names[i], scores[i]) for i in np.nonzero(scores)[0]]
    if not pairs:
        return {}

    max_score = max(s for _, s in pairs)
    result: Dict[str, int] = {}
    for term, score in pairs:
        # Фильтруем одиночные стоп-слова и слишком короткие термины
        parts = term.split()
        if any(p in STOPWORDS_EN for p in parts):
            continue
        if len(term) < 3:
            continue
        # Масштабируем: 1..100
        count = max(1, int(score / max_score * 100))
        result[term] = count

    return result


def _v4(abstract: str) -> Dict[str, int]:
    """4_tfidf_gensim: TF-IDF через gensim Dictionary + TfidfModel."""
    # TODO: обучить gensim.models.TfidfModel на корпусе,
    #       применить к токенам абстракта.
    # Пример:
    #   from gensim import corpora, models
    #   dictionary = corpora.Dictionary(corpus_tokens)
    #   tfidf = models.TfidfModel(corpus_bow)
    #   bow = dictionary.doc2bow(tokens)
    #   scores = tfidf[bow]
    raise NotImplementedError("4_tfidf_gensim: не реализован")


def _v7(abstract: str) -> Dict[str, int]:
    """7_ensemble_136: ансамбль v1 + v3 + v6 с нормализацией по максимуму.

    Каждый экстрактор нормализуется к [0, 1] по максимальному баллу в своём выводе,
    затем берётся взвешенная сумма (веса равные). Результат масштабируется в 1–100.
    Новый db_id = 7, несовместим с v1/v3/v6 по отдельности.
    """
    # TODO: реализовать
    # weights = {"v1": 1.0, "v3": 1.0, "v6": 1.0}
    # raw = {
    #     "v1": _v1(abstract),
    #     "v3": _v3(abstract),
    #     "v6": _v6(abstract),
    # }
    # merged: Dict[str, float] = {}
    # for src, result in raw.items():
    #     if not result:
    #         continue
    #     max_val = max(result.values())
    #     w = weights[src]
    #     for kw, score in result.items():
    #         merged[kw] = merged.get(kw, 0.0) + w * score / max_val
    # if not merged:
    #     return {}
    # max_merged = max(merged.values())
    # return {kw: max(1, int(v / max_merged * 100)) for kw, v in merged.items()}
    raise NotImplementedError("7_ensemble_136: не реализован")


def _v8(abstract: str) -> Dict[str, int]:
    """8_keybert: извлечение через KeyBERT (требует sentence-transformers)."""
    # TODO: инициализировать KeyBERT один раз (глобальный объект),
    #       вернуть слова со скором как целое число (score * 100).
    # Пример:
    #   from keybert import KeyBERT
    #   kw_model = KeyBERT()
    #   keywords = kw_model.extract_keywords(abstract, top_n=20)
    #   return {kw: int(score * 100) for kw, score in keywords}
    raise NotImplementedError("8_keybert: не реализован")


_yake_extractor = None


def _get_yake_extractor():
    """Ленивая инициализация YAKE."""
    global _yake_extractor
    if _yake_extractor is None:
        import yake
        _yake_extractor = yake.KeywordExtractor(
            lan="en",
            n=2,       # макс. длина n-граммы (биграммы)
            dedupLim=0.7,
            top=30,
            features=None,
        )
    return _yake_extractor


def _v6(abstract: str) -> Dict[str, int]:
    """6_yake: статистическое извлечение через YAKE (без обучения на корпусе).

    YAKE возвращает score где меньше = важнее. Конвертируем в rank-based счётчики:
    топ-1 → 30, ..., топ-30 → 1. Стоп-слова фильтруются дополнительно.
    """
    from config.constants import STOPWORDS_EN

    extractor = _get_yake_extractor()
    try:
        keywords = extractor.extract_keywords(abstract or "")
    except Exception:
        return {}

    result: Dict[str, int] = {}
    rank = len(keywords)
    for phrase, _score in keywords:
        phrase_lower = phrase.lower().strip()
        # Убрать фразы где все слова — стоп-слова
        words = phrase_lower.split()
        if not words or all(w in STOPWORDS_EN for w in words):
            continue
        if len(phrase_lower) < 3:
            continue
        result[phrase_lower] = max(1, rank)
        rank -= 1

    return result


# ------------------------------------------------------------------ реестр

EXTRACTORS: Dict[str, ExtractorSpec] = {
    "1_count_stopwords": ExtractorSpec(1, "count+stopwords", _v1),
    "2_llm":             ExtractorSpec(2, "LLM",             _v2),
    "3_tfidf_sklearn":   ExtractorSpec(3, "TF-IDF/sklearn",  _v3),
    "4_tfidf_gensim":    ExtractorSpec(4, "TF-IDF/gensim",   _v4),
    "6_yake":            ExtractorSpec(6, "YAKE",            _v6),
    "7_ensemble_136":    ExtractorSpec(7, "ensemble(1+3+6)", _v7),
    "8_keybert":         ExtractorSpec(8, "KeyBERT",         _v8),
}

# ------------------------------------------------------------------ активный алгоритм

# Для смены алгоритма — изменить эту строку.
# ВАЖНО: смена вызовет пересчёт ключевых слов для всех статей (db_id меняется).
ACTIVE_EXTRACTOR_KEY: str = "1_count_stopwords"
ACTIVE_EXTRACTOR: ExtractorSpec = EXTRACTORS[ACTIVE_EXTRACTOR_KEY]


# ------------------------------------------------------------------ публичный API

def extract_keywords(abstract: str) -> Dict[str, int]:
    """Извлечь ключевые слова из абстракта активным алгоритмом."""
    return ACTIVE_EXTRACTOR.fn(abstract)


def extractor_info() -> str:
    """Строка для логов: 'v1 (count+stopwords)'."""
    return f"v{ACTIVE_EXTRACTOR.db_id} ({ACTIVE_EXTRACTOR.label})"
