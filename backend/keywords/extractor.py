from __future__ import annotations
import logging
import re
from collections import Counter
from typing import Dict

from config.constants import TOKEN_PATTERN, STOPWORDS_EN, MIN_TOKEN_LEN
from keywords.normalizer import lemmatize

logger = logging.getLogger(__name__)

_token_re = re.compile(TOKEN_PATTERN)
_latex_re = re.compile(r"\\[a-zA-Z]+")  # \texttt, \mathbf, \emph, ...


def _regex_extract(abstract: str) -> Dict[str, int]:
    text = _latex_re.sub(" ", abstract or "")
    tokens = [t.lower() for t in _token_re.findall(text)]
    tokens = [t for t in tokens if len(t) >= MIN_TOKEN_LEN and t not in STOPWORDS_EN]
    normalized: Counter = Counter()
    for t in tokens:
        lemma = lemmatize(t)
        if lemma not in STOPWORDS_EN and len(lemma) >= MIN_TOKEN_LEN:
            normalized[lemma] += 1
    return dict(normalized)


def extract_keywords_from_abstract(abstract: str) -> Dict[str, int]:
    """Извлечь ключевые слова из абстракта.

    Если установлена переменная USE_LLM_EXTRACTOR=1 и LLM доступен — использует LLM.
    Иначе использует regex-токенизацию.
    """
    from keywords.llm_extractor import extract_keywords_llm

    result = extract_keywords_llm(abstract)
    if result is not None:
        return result

    return _regex_extract(abstract)
