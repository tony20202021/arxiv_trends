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
    def __init__(self, db_id: int, label: str, fn: Callable[[str], Dict[str, int]], max_score: int = 1):
        self.db_id = db_id         # число в articles.keyword_extractor_version
        self.label = label         # человекочитаемое имя (для логов и графиков)
        self.fn = fn               # функция (abstract: str) -> Dict[keyword, count]
        self.max_score = max_score # макс. score на статью; для нормировки pct: count/(articles*max_score)*100

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
    """Ленивая инициализация CountVectorizer для биграммного TF."""
    global _sklearn_extractor
    if _sklearn_extractor is None:
        from sklearn.feature_extraction.text import CountVectorizer
        from config.constants import STOPWORDS_EN
        _sklearn_extractor = CountVectorizer(
            stop_words=list(STOPWORDS_EN),
            ngram_range=(1, 2),   # уни- и биграммы (ловит "neural network", "diffusion model")
            min_df=1,
            max_features=500,
            token_pattern=r"[a-zA-Z][a-zA-Z0-9\-]{2,}",
        )
    return _sklearn_extractor


def _v3(abstract: str) -> Dict[str, int]:
    """3_tfidf_sklearn: уни- и биграммы с raw TF (sklearn CountVectorizer).

    Возвращает raw count вхождений каждого термина в абстракте.
    Главное преимущество перед v1 — захватывает биграммы типа
    «neural network», «diffusion model», «attention mechanism».
    """
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
        parts = term.split()
        if any(p in STOPWORDS_EN for p in parts):
            continue
        if len(term) < 3:
            continue
        result[term] = int(count)

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


def _v8(abstract: str) -> Dict[str, int]:
    """8_ensemble_137: ансамбль v1 + v3 + v7 с нормализацией по максимуму.

    Каждый экстрактор нормализуется к [0, 1] по максимальному баллу в своём выводе,
    затем берётся взвешенная сумма (веса равные). Результат масштабируется в 1–100.
    db_id = 8, несовместим с v1/v3/v7 по отдельности.
    """
    # TODO: реализовать
    # weights = {"v1": 1.0, "v3": 1.0, "v7": 1.0}
    # raw = {
    #     "v1": _v1(abstract),
    #     "v3": _v3(abstract),
    #     "v7": _v7(abstract),
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
    raise NotImplementedError("8_ensemble_137: не реализован")


def _v9(abstract: str) -> Dict[str, int]:
    """9_keybert: извлечение через KeyBERT (требует sentence-transformers)."""
    # TODO: инициализировать KeyBERT один раз (глобальный объект),
    #       вернуть слова со скором как целое число (score * 100).
    # Пример:
    #   from keybert import KeyBERT
    #   kw_model = KeyBERT()
    #   keywords = kw_model.extract_keywords(abstract, top_n=20)
    #   return {kw: int(score * 100) for kw, score in keywords}
    raise NotImplementedError("9_keybert: не реализован")


_yake_extractor_v7 = None
_yake_extractor_v11 = None


def _get_yake_extractor_v7():
    """Ленивая инициализация YAKE (v7: n=3, dedupLim=0.7)."""
    global _yake_extractor_v7
    if _yake_extractor_v7 is None:
        import yake
        _yake_extractor_v7 = yake.KeywordExtractor(
            lan="en",
            n=3,
            dedupLim=0.7,
            top=30,
            features=None,
        )
    return _yake_extractor_v7


def _get_yake_extractor_v11():
    """Ленивая инициализация YAKE (v11: n=3, dedupLim=0.5 — агрессивнее дедупликация)."""
    global _yake_extractor_v11
    if _yake_extractor_v11 is None:
        import yake
        _yake_extractor_v11 = yake.KeywordExtractor(
            lan="en",
            n=3,
            dedupLim=0.5,
            top=30,
            features=None,
        )
    return _yake_extractor_v11


def _yake_extract(abstract: str, get_extractor) -> Dict[str, int]:
    """Общая логика YAKE-извлечения: rank-based счётчики, фильтрация стоп-слов."""
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
    """7_yake: YAKE trigrams, dedupLim=0.7."""
    return _yake_extract(abstract, _get_yake_extractor_v7)


def _v11(abstract: str) -> Dict[str, int]:
    """11_yake: YAKE trigrams, dedupLim=0.5 — уменьшает пересечение n-грамм внутри абстракта."""
    return _yake_extract(abstract, _get_yake_extractor_v11)


def _v20(abstract: str) -> Dict[str, int]:
    """20_ensemble: ансамбль v1+v3+v11, веса 0.5:1.0:2.0, нормировка к [0,1] по max.

    Каждый экстрактор нормализуется делением на свой максимум → [0,1].
    Затем взвешенная сумма → масштаб 1–100.
    Выход совместим с YAKE по формату (score за термин).
    """
    weights = {"v1": 0.5, "v3": 1.0, "v11": 2.0}
    raw = {
        "v1":  _v1(abstract),
        "v3":  _v3(abstract),
        "v11": _v11(abstract),
    }
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


# ------------------------------------------------------------------ реестр

EXTRACTORS: Dict[str, ExtractorSpec] = {
    "1_count_stopwords": ExtractorSpec(1,  "count+stopwords",    _v1),
    "2_llm":             ExtractorSpec(2,  "LLM",                _v2),
    "3_tfidf_sklearn":   ExtractorSpec(3,  "bigram-TF/sklearn",  _v3),
    "4_tfidf_gensim":    ExtractorSpec(4,  "TF-IDF/gensim",      _v4),
    "7_yake":            ExtractorSpec(7,  "YAKE+trigrams",      _v7,  max_score=30),
    "8_ensemble_137":    ExtractorSpec(8,  "ensemble(1+3+7)",    _v8),
    "9_keybert":         ExtractorSpec(9,  "KeyBERT",            _v9),
    # Нумерация с 11: шаг 10 (как в BASIC: 10, 20, 30...), предыдущие зарезервированы.
    "11_yake":           ExtractorSpec(11, "YAKE+trigrams,d0.5", _v11, max_score=30),
    "20_ensemble":       ExtractorSpec(20, "ensemble(1+3+11)",   _v20, max_score=100),
    # "30_...":          ExtractorSpec(30, "...",                _v30),
}

# ------------------------------------------------------------------ активный алгоритм

# Для смены алгоритма — изменить эту строку.
# ВАЖНО: смена вызовет пересчёт ключевых слов для всех статей (db_id меняется).
ACTIVE_EXTRACTOR_KEY: str = "20_ensemble"
ACTIVE_EXTRACTOR: ExtractorSpec = EXTRACTORS[ACTIVE_EXTRACTOR_KEY]


# ------------------------------------------------------------------ публичный API

def extract_keywords(abstract: str) -> Dict[str, int]:
    """Извлечь ключевые слова из абстракта активным алгоритмом."""
    return ACTIVE_EXTRACTOR.fn(abstract)


def extractor_info() -> str:
    """Строка для логов: 'v1 (count+stopwords)'."""
    return f"v{ACTIVE_EXTRACTOR.db_id} ({ACTIVE_EXTRACTOR.label})"
