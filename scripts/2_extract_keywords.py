"""Сервис 2: извлечение ключевых слов из articles → weekly_keyword_counts.

Читает только из БД. arXiv API не используется.
Обрабатывает статьи у которых keywords=None или версия экстрактора устарела.

Примеры:
  # Все домены за Q1 2026:
  python scripts/2_extract_keywords.py --from 2026-01-01 --to 2026-03-31

  # Только cs_ro, батч по 50 статей за раз:
  python scripts/2_extract_keywords.py --from 2026-01-01 --to 2026-01-31 --domains cs_ro --batch-size 50
"""
from __future__ import annotations
import argparse
import logging
import os
import sys
from pathlib import Path

_root = Path(__file__).parent.parent
sys.path.insert(0, str(_root / "backend"))
sys.path.insert(0, str(_root))

from dotenv import load_dotenv
load_dotenv(_root / ".env")

from pipeline import extract_keywords_batch
from utils.cli import parse_date, load_domains, validate_date_range
from utils.logging_setup import setup_logging


def main():
    ap = argparse.ArgumentParser(description="Сервис 2: извлечение ключевых слов из БД")
    ap.add_argument("--from", dest="week_from", required=True, metavar="YYYY-MM-DD",
                    type=parse_date, help="Начало диапазона (включительно)")
    ap.add_argument("--to", dest="week_to", required=True, metavar="YYYY-MM-DD",
                    type=parse_date, help="Конец диапазона (включительно)")
    ap.add_argument("--domains", nargs="+", metavar="DOMAIN",
                    help="Список доменов (по умолчанию — все из domains.json)")
    ap.add_argument("--batch-size", type=int, default=100, dest="batch_size",
                    help="Статей за одну итерацию (по умолчанию 100)")
    ap.add_argument("--domains-file", default="config/domains.json")
    ap.add_argument("--log-level", default="INFO",
                    choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    ap.add_argument("--log-format", default="text", choices=["text", "json"])
    args = ap.parse_args()

    setup_logging(
        level=args.log_level,
        log_file=_root / ".outputs" / "logs" / "extract_keywords.log",
        fmt=args.log_format,
    )

    week_from = args.week_from
    week_to = args.week_to
    validate_date_range(week_from, week_to)

    domains = load_domains(args.domains_file, args.domains)

    mongo_uri = os.environ.get("MONGO_URI", "mongodb://127.0.0.1:8627")
    mongo_db = os.environ.get("MONGO_DB", "arxiv_trends")

    logging.info("extract_keywords: %d доменов, %s … %s, batch=%d",
                 len(domains), week_from, week_to, args.batch_size)

    stats = extract_keywords_batch(
        domains=domains,
        week_from=week_from,
        week_to=week_to,
        mongo_uri=mongo_uri,
        mongo_db=mongo_db,
        batch_size=args.batch_size,
    )

    print("\n=== Итог ===")
    for domain, s in stats.items():
        print(f"  {domain:<14}  обработано={s['processed']:>5}  пропущено={s['skipped']:>5}")


if __name__ == "__main__":
    main()
