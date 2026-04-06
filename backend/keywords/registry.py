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


def _v3(abstract: str) -> Dict[str, int]:
    """3_tfidf_sklearn: TF-IDF через scikit-learn (требует fit на корпусе)."""
    # TODO: обучить TfidfVectorizer на всём корпусе articles из БД,
    #       затем трансформировать каждый абстракт и вернуть топ-N слов с весами.
    # Пример:
    #   from sklearn.feature_extraction.text import TfidfVectorizer
    #   vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
    #   tfidf = vec.fit_transform([abstract])
    #   ...
    raise NotImplementedError("3_tfidf_sklearn: не реализован")


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


def _v5(abstract: str) -> Dict[str, int]:
    """5_keybert: извлечение через KeyBERT (требует sentence-transformers)."""
    # TODO: инициализировать KeyBERT один раз (глобальный объект),
    #       вернуть слова со скором как целое число (score * 100).
    # Пример:
    #   from keybert import KeyBERT
    #   kw_model = KeyBERT()
    #   keywords = kw_model.extract_keywords(abstract, top_n=20)
    #   return {kw: int(score * 100) for kw, score in keywords}
    raise NotImplementedError("5_keybert: не реализован")


def _v6(abstract: str) -> Dict[str, int]:
    """6_yake: статистическое извлечение через YAKE (без обучения)."""
    # TODO: инициализировать yake.KeywordExtractor один раз,
    #       YAKE возвращает (keyword, score) где меньше = важнее,
    #       инвертировать: count = int(1 / score) или rank-based.
    # Пример:
    #   import yake
    #   kw_extractor = yake.KeywordExtractor(lan="en", n=2, top=20)
    #   keywords = kw_extractor.extract_keywords(abstract)
    #   return {kw: int(1000 / (score + 1e-9)) for kw, score in keywords}
    raise NotImplementedError("6_yake: не реализован")


# ------------------------------------------------------------------ реестр

EXTRACTORS: Dict[str, ExtractorSpec] = {
    "1_count_stopwords": ExtractorSpec(1, "count+stopwords", _v1),
    "2_llm":             ExtractorSpec(2, "LLM",             _v2),
    "3_tfidf_sklearn":   ExtractorSpec(3, "TF-IDF/sklearn",  _v3),
    "4_tfidf_gensim":    ExtractorSpec(4, "TF-IDF/gensim",   _v4),
    "5_keybert":         ExtractorSpec(5, "KeyBERT",         _v5),
    "6_yake":            ExtractorSpec(6, "YAKE",            _v6),
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
