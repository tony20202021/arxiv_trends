"""Corpus TF-IDF через gensim (v4).

Модель обучается offline: scripts/train_gensim_model.py
Сохраняется в .outputs/models/gensim/ (dictionary, tfidf, meta.json).
"""
from __future__ import annotations
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from config.constants import MIN_TOKEN_LEN, STOPWORDS_EN, TOKEN_PATTERN

logger = logging.getLogger(__name__)

_token_re = re.compile(TOKEN_PATTERN)
_latex_re = re.compile(r"\\[a-zA-Z]+")

_dictionary = None
_tfidf = None
_model_dir: Optional[Path] = None
_loaded_version: Optional[int] = None

META_FILENAME = "meta.json"


def default_model_dir() -> Path:
    return Path(__file__).resolve().parents[2] / ".outputs" / "models" / "gensim"


def _meta_path(model_dir: Optional[Path] = None) -> Path:
    return (model_dir or default_model_dir()) / META_FILENAME


def read_gensim_meta(model_dir: Optional[Path] = None) -> Optional[dict]:
    path = _meta_path(model_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Cannot read gensim meta %s: %s", path, exc)
        return None


def get_gensim_model_version(model_dir: Optional[Path] = None) -> int:
    """Версия обученной gensim-модели. 0 — модели нет."""
    model_dir = model_dir or default_model_dir()
    meta = read_gensim_meta(model_dir)
    if meta and "version" in meta:
        return int(meta["version"])
    if (model_dir / "dictionary.gensim").exists() and (model_dir / "tfidf.gensim").exists():
        return 1  # legacy: модель без meta.json
    return 0


def write_gensim_meta(
    version: int,
    *,
    model_dir: Optional[Path] = None,
    document_count: int = 0,
    limit: int = 0,
) -> dict:
    """Записать meta.json после обучения."""
    model_dir = model_dir or default_model_dir()
    model_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "version": version,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "document_count": document_count,
        "limit": limit,
    }
    _meta_path(model_dir).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def next_gensim_model_version(model_dir: Optional[Path] = None) -> int:
    """Следующая версия для train_gensim_model.py."""
    return get_gensim_model_version(model_dir) + 1


def invalidate_gensim_cache() -> None:
    global _dictionary, _tfidf, _model_dir, _loaded_version
    _dictionary = None
    _tfidf = None
    _model_dir = None
    _loaded_version = None


def tokenize_for_gensim(text: str) -> List[str]:
    """Токенизация абстракта (как v1, без лемм — словарь gensim строится на raw tokens)."""
    text = _latex_re.sub(" ", text or "")
    tokens = [t.lower() for t in _token_re.findall(text)]
    return [
        t for t in tokens
        if len(t) >= MIN_TOKEN_LEN and t not in STOPWORDS_EN
    ]


def _load_models(model_dir: Optional[Path] = None) -> bool:
    global _dictionary, _tfidf, _model_dir, _loaded_version
    model_dir = model_dir or default_model_dir()
    current_version = get_gensim_model_version(model_dir)

    if (
        _dictionary is not None
        and _tfidf is not None
        and _model_dir == model_dir
        and _loaded_version == current_version
    ):
        return True

    dict_path = model_dir / "dictionary.gensim"
    tfidf_path = model_dir / "tfidf.gensim"
    if not dict_path.exists() or not tfidf_path.exists():
        _dictionary = None
        _tfidf = None
        _loaded_version = None
        return False

    try:
        from gensim.corpora import Dictionary
        from gensim.models import TfidfModel

        _dictionary = Dictionary.load(str(dict_path))
        _tfidf = TfidfModel.load(str(tfidf_path))
        _model_dir = model_dir
        _loaded_version = current_version
        logger.debug("Gensim TF-IDF v%d loaded from %s", current_version, model_dir)
        return True
    except Exception as exc:
        logger.warning("Gensim model load failed: %s", exc)
        _dictionary = None
        _tfidf = None
        _loaded_version = None
        return False


def extract_keywords_gensim(abstract: str, top_n: int = 25) -> Dict[str, int]:
    """TF-IDF scores для терминов абстракта относительно обученного корпуса."""
    if not _load_models():
        return {}

    tokens = tokenize_for_gensim(abstract)
    if not tokens:
        return {}

    bow = _dictionary.doc2bow(tokens)
    if not bow:
        return {}

    scored = sorted(_tfidf[bow], key=lambda x: x[1], reverse=True)[:top_n]
    if not scored:
        return {}

    max_score = scored[0][1] or 1.0
    result: Dict[str, int] = {}
    for term_id, score in scored:
        term = _dictionary[term_id]
        if any(p in STOPWORDS_EN for p in term.split()):
            continue
        if len(term) < MIN_TOKEN_LEN:
            continue
        result[term] = max(1, int(score / max_score * 100))
    return result
