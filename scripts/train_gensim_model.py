#!/usr/bin/env python3
"""Обучение gensim Dictionary + TfidfModel на абстрактах из MongoDB.

При каждом успешном обучении увеличивает gensim_model_version в meta.json.
Backend-2 (extract) пересчитает keywords у статей с устаревшей gensim_model_version.

Использование:
    python scripts/train_gensim_model.py
    python scripts/train_gensim_model.py --limit 80000 --out .outputs/models/gensim
"""
from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path

_root = Path(__file__).parent.parent
sys.path.insert(0, str(_root / "backend"))
sys.path.insert(0, str(_root))

from dotenv import load_dotenv
load_dotenv(_root / ".env")

from keywords.gensim_extractor import (
    tokenize_for_gensim,
    default_model_dir,
    next_gensim_model_version,
    write_gensim_meta,
    invalidate_gensim_cache,
)


def main() -> None:
    ap = argparse.ArgumentParser(description="Train gensim TF-IDF model on arXiv abstracts")
    ap.add_argument("--limit", type=int, default=80000, help="Max abstracts to use")
    ap.add_argument("--out", default=str(default_model_dir()), help="Output directory")
    ap.add_argument("--min-df", type=int, default=5, help="Min document frequency for dictionary")
    ap.add_argument("--max-df", type=float, default=0.45, help="Max document frequency ratio")
    args = ap.parse_args()

    from pymongo import MongoClient

    out_dir = Path(args.out)
    new_version = next_gensim_model_version(out_dir)

    mongo_uri = os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27027")
    mongo_db = os.environ.get("MONGO_DB", "arxiv_trends")
    client = MongoClient(mongo_uri)
    db = client[mongo_db]

    print(f"Loading up to {args.limit} abstracts from {mongo_db}...")
    cursor = db.articles.find(
        {"abstract": {"$exists": True, "$ne": ""}},
        {"abstract": 1, "_id": 0},
    ).limit(args.limit)

    corpus_tokens = []
    for doc in cursor:
        tokens = tokenize_for_gensim(doc.get("abstract", ""))
        if tokens:
            corpus_tokens.append(tokens)

    if len(corpus_tokens) < 100:
        print(f"ERROR: only {len(corpus_tokens)} documents — need at least 100")
        sys.exit(1)

    print(f"Tokenized {len(corpus_tokens)} documents, building dictionary...")

    from gensim.corpora import Dictionary
    from gensim.models import TfidfModel

    dictionary = Dictionary(corpus_tokens)
    dictionary.filter_extremes(no_below=args.min_df, no_above=args.max_df)
    bow_corpus = [dictionary.doc2bow(doc) for doc in corpus_tokens]
    tfidf = TfidfModel(bow_corpus)

    out_dir.mkdir(parents=True, exist_ok=True)
    dictionary.save(str(out_dir / "dictionary.gensim"))
    tfidf.save(str(out_dir / "tfidf.gensim"))

    meta = write_gensim_meta(
        new_version,
        model_dir=out_dir,
        document_count=len(corpus_tokens),
        limit=args.limit,
    )
    invalidate_gensim_cache()

    print(f"Saved: {out_dir}/dictionary.gensim ({len(dictionary)} terms)")
    print(f"Saved: {out_dir}/tfidf.gensim")
    print(f"Saved: {out_dir}/meta.json → gensim_model_version={new_version}")
    print(
        "Backend-2 пересчитает keywords у статей с gensim_model_version "
        f"≠ {new_version} (при следующих прогонах extract)."
    )


if __name__ == "__main__":
    main()
