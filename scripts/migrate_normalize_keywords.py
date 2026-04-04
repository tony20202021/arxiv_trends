"""Миграция: нормализует (лемматизирует) keyword-поле во всех документах БД.

Алгоритм:
  1. Загружает все уникальные ключевые слова, батч-лемматизирует через spaCy.
  2. Читает все 215K документов в память.
  3. Пересчитывает счётчики: группирует по (domain, week_start, lemma).
  4. Bulk-upsert новых нормализованных счётчиков.
  5. Удаляет все старые ненормализованные документы.
  6. Фильтрует стоп-слова и слова короче 3 символов.

Запуск:
  python scripts/migrate_normalize_keywords.py [--dry-run]
"""
from __future__ import annotations
import argparse
import logging
import sys
from collections import defaultdict
from pathlib import Path

_root = Path(__file__).parent.parent
sys.path.insert(0, str(_root / "backend"))
sys.path.insert(0, str(_root))

from dotenv import load_dotenv
import os

load_dotenv(_root / ".env")

from pymongo import UpdateOne
from storage.mongo import MongoStore
from keywords.normalizer import lemmatize_batch
from config.constants import STOPWORDS_EN

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("migrate")


def run(mongo_uri: str, mongo_db: str, dry_run: bool = False) -> None:
    store = MongoStore(mongo_uri, mongo_db)
    col = store.col

    # 1. Лемматизация уникальных слов
    logger.info("Загрузка уникальных ключевых слов...")
    unique_words: list[str] = col.distinct("keyword")
    logger.info("Уникальных слов: %d", len(unique_words))

    logger.info("Батч-лемматизация...")
    lemmas = lemmatize_batch(unique_words)

    word_to_lemma: dict[str, str | None] = {}
    for word, lemma in zip(unique_words, lemmas):
        if lemma in STOPWORDS_EN or len(lemma) < 3:
            word_to_lemma[word] = None  # удалить
        else:
            word_to_lemma[word] = lemma

    changed = sum(1 for w, l in word_to_lemma.items() if l is not None and l != w)
    deleted = sum(1 for l in word_to_lemma.values() if l is None)
    unchanged = sum(1 for w, l in word_to_lemma.items() if l == w)
    logger.info("Слов без изменений: %d, к нормализации: %d, к удалению (стоп-слова): %d",
                unchanged, changed, deleted)

    if dry_run:
        logger.info("--- DRY RUN --- изменения не записываются")
        sample = [(w, l) for w, l in word_to_lemma.items() if l is not None and l != w][:30]
        for w, l in sample:
            logger.info("  %s → %s", w, l)
        return

    # 2. Читаем все документы в память
    logger.info("Чтение всех документов из БД...")
    all_docs = list(col.find({}, {"_id": 0, "domain": 1, "week_start": 1, "keyword": 1, "count": 1}))
    logger.info("Загружено документов: %d", len(all_docs))

    # 3. Пересчёт: (domain, week_start, lemma) → count
    new_counts: dict[tuple, int] = defaultdict(int)
    for doc in all_docs:
        lemma = word_to_lemma.get(doc["keyword"], doc["keyword"])
        if lemma is None:
            continue  # стоп-слово — пропускаем
        key = (doc["domain"], doc["week_start"], lemma)
        new_counts[key] += doc["count"]

    logger.info("Уникальных (domain, week, lemma) после нормализации: %d", len(new_counts))

    # 4. Удаляем всё старое
    logger.info("Удаление старых документов...")
    col.delete_many({})

    # 5. Bulk-insert нормализованных данных
    logger.info("Запись нормализованных данных...")
    BATCH = 5000
    items = list(new_counts.items())
    ops = [
        UpdateOne(
            {"domain": domain, "week_start": week_start, "keyword": lemma},
            {"$inc": {"count": count}},
            upsert=True,
        )
        for (domain, week_start, lemma), count in items
    ]
    for i in range(0, len(ops), BATCH):
        col.bulk_write(ops[i:i + BATCH], ordered=False)
        logger.info("  записано %d / %d", min(i + BATCH, len(ops)), len(ops))

    logger.info("Миграция завершена. Документов в БД: %d", col.count_documents({}))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="Показать что изменится, без записи")
    ap.add_argument("--uri", default=os.getenv("MONGO_URI", "mongodb://127.0.0.1:27027"))
    ap.add_argument("--db", default=os.getenv("MONGO_DB", "arxiv_trends"))
    args = ap.parse_args()
    run(args.uri, args.db, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
