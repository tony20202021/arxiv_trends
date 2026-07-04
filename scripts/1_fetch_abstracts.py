"""Сервис 1: загрузка абстрактов из arXiv → коллекция articles.

Только эта команда обращается к arXiv API.
Уже сохранённые статьи пропускаются автоматически.

Примеры:
  # Все домены за Q1 2026:
  python scripts/1_fetch_abstracts.py --from 2026-01-01 --to 2026-03-31

  # Только cs_ro за январь, не более 200 статей на домен:
  python scripts/1_fetch_abstracts.py --from 2026-01-01 --to 2026-01-31 --domains cs_ro --max-articles 200
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

from pipeline import fetch_abstracts
from utils.cli import parse_date, load_domains, validate_date_range
from utils.logging_setup import setup_logging


def main():
    ap = argparse.ArgumentParser(description="Сервис 1: загрузка абстрактов из arXiv")
    ap.add_argument("--from", dest="week_from", required=True, metavar="YYYY-MM-DD",
                    type=parse_date, help="Начало диапазона (включительно)")
    ap.add_argument("--to", dest="week_to", required=True, metavar="YYYY-MM-DD",
                    type=parse_date, help="Конец диапазона (включительно)")
    ap.add_argument("--domains", nargs="+", metavar="DOMAIN",
                    help="Список доменов (по умолчанию — все из domains.json)")
    ap.add_argument("--max-articles", type=int, default=-1, dest="max_articles",
                    help="Максимум статей на домен (-1 = без ограничений)")
    ap.add_argument("--domains-file", default="config/domains.json")
    ap.add_argument("--log-level", default="INFO",
                    choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    ap.add_argument("--log-format", default="text", choices=["text", "json"],
                    help="Формат логов: text (по умолчанию) или json")
    args = ap.parse_args()

    setup_logging(
        level=args.log_level,
        log_file=_root / ".outputs" / "logs" / "fetch_abstracts.log",
        fmt=args.log_format,
    )

    week_from = args.week_from
    week_to = args.week_to
    validate_date_range(week_from, week_to)

    domains = load_domains(args.domains_file, args.domains)

    mongo_uri = os.environ.get("MONGO_URI", "mongodb://127.0.0.1:8627")
    mongo_db = os.environ.get("MONGO_DB", "arxiv_trends")
    api_url = os.environ.get("ARXIV_API_URL", "https://export.arxiv.org/api/query")
    user_agent = os.environ.get("HTTP_USER_AGENT", "arxiv-trends-bot/0.1")

    logging.info("fetch_abstracts: %d доменов, %s … %s, max=%s",
                 len(domains), week_from, week_to,
                 args.max_articles if args.max_articles != -1 else "∞")

    stats = fetch_abstracts(
        domains=domains,
        week_from=week_from,
        week_to=week_to,
        mongo_uri=mongo_uri,
        mongo_db=mongo_db,
        api_url=api_url,
        user_agent=user_agent,
        max_articles=args.max_articles,
    )

    print("\n=== Итог ===")
    for domain, s in stats.items():
        truncated = " [прервано API]" if s.get("truncated") else ""
        print(f"  {domain:<14}  из arXiv={s['fetched']:>5}  "
              f"новых={s['new']:>5}  пропущено={s['skipped']:>5}{truncated}")


if __name__ == "__main__":
    main()
