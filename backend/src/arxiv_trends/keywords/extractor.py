from __future__ import annotations
import re
from collections import Counter
from typing import Dict

from config.constants import TOKEN_PATTERN, STOPWORDS_EN, MIN_TOKEN_LEN

_token_re = re.compile(TOKEN_PATTERN)

TODO поменяь на вызов ЛЛИ

def extract_keywords_from_abstract(abstract: str) -> Dict[str, int]:
    tokens = [t.lower() for t in _token_re.findall(abstract or "")]
    tokens = [t for t in tokens if len(t) >= MIN_TOKEN_LEN and t not in STOPWORDS_EN]
    return dict(Counter(tokens))
