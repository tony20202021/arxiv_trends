"""Запуск пайплайна за произвольный диапазон недель.

Примеры:
  # Собрать данные за Q1 2026 для всех доменов (пропускать уже обработанные):
  python scripts/run_pipeline.py --from 2026-01-01 --to 2026-03-31

  # Только cs_ro и cs_ai за февраль 2026:
  python scripts/run_pipeline.py --from 2026-02-01 --to 2026-02-28 --domains cs_ro cs_ai

  # Перезаписать данные за конкретную неделю:
  python scripts/run_pipeline.py --from 2026-03-10 --to 2026-03-10 --overwrite
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import logging
import os
import sys
from pathlib import Path

_root = Path(__file__).parent.parent
sys.path.insert(0, str(_root / "backend"))
sys.path.insert(0, str(_root))

from dotenv import load_dotenv
load_dotenv(_root / ".env")

from pipeline import run_pipeline


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main():
    ap = argparse.ArgumentParser(description="Запуск пайплайна за диапазон недель")
    ap.add_argument("--from", dest="week_from", required=True, metavar="YYYY-MM-DD",
                    help="Начало диапазона (включительно)")
    ap.add_argument("--to", dest="week_to", required=True, metavar="YYYY-MM-DD",
                    help="Конец диапазона (включительно)")
    ap.add_argument("--domains", nargs="+", metavar="DOMAIN",
                    help="Список доменов (по умолчанию — все из domains.json)")
    ap.add_argument("--overwrite", action="store_true",
                    help="Удалить старые данные за указанные недели и домены и обработать заново")
    ap.add_argument("--recompute-aggregates", action="store_true", dest="recompute_aggregates",
                    help="Пересчитать агрегаты (топ-популярные/растущие) после обработки")
    ap.add_argument("--max-articles", type=int, default=-1, dest="max_articles",
                    help="Максимум статей на домен (-1 = без ограничений)")
    ap.add_argument("--domains-file", default="config/domains.json")
    ap.add_argument("--log-level", default="INFO",
                    choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = ap.parse_args()

    _setup_logging(args.log_level)

    week_from = dt.date.fromisoformat(args.week_from)
    week_to = dt.date.fromisoformat(args.week_to)

    all_domains: list[dict] = json.loads(
        (Path(args.domains_file)).read_text(encoding="utf-8")
    )
    if args.domains:
        domain_set = set(args.domains)
        domains = [d for d in all_domains if d["domain"] in domain_set]
        unknown = domain_set - {d["domain"] for d in domains}
        if unknown:
            logging.error("Неизвестные домены: %s", unknown)
            sys.exit(1)
    else:
        domains = all_domains

    mongo_uri = os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017")
    mongo_db = os.environ.get("MONGO_DB", "arxiv_trends")
    api_url = os.environ.get("ARXIV_API_URL", "https://export.arxiv.org/api/query")
    user_agent = os.environ.get("HTTP_USER_AGENT", "arxiv-trends-bot/0.1")

    logging.info(
        "Запуск: %d доменов, %s … %s, overwrite=%s",
        len(domains), week_from, week_to, args.overwrite,
    )

    stats = run_pipeline(
        domains=domains,
        week_from=week_from,
        week_to=week_to,
        mongo_uri=mongo_uri,
        mongo_db=mongo_db,
        api_url=api_url,
        user_agent=user_agent,
        overwrite=args.overwrite,
        max_articles=args.max_articles,
        recompute_aggregates=args.recompute_aggregates,
    )

    print("\n=== Итог ===")
    for domain, s in stats.items():
        print(f"  {domain:<14}  получено={s['total_fetched']:>5}  "
              f"обработано={s['processed_now']:>5}  "
              f"пропущено={s['skipped_already_done']:>5}  "
              f"ошибок={s['skipped_error']:>4}")


if __name__ == "__main__":
    main()
