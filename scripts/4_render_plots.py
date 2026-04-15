"""Сервис 4: построение графиков из агрегатов и данных БД.

Читает aggregates и weekly_keyword_counts / articles из БД.
Агрегаты не пересчитываются — запустите сначала 3_recompute_aggregates.py.

Строит 3 графика на домен:
  - top_popular.png       — топ-N популярных ключевых слов за последнюю неделю
  - top_growing.png       — топ-N растущих ключевых слов
  - articles_per_week.png — количество статей по неделям

Примеры:
  # Все домены:
  python scripts/4_render_plots.py

  # Только выбранные:
  python scripts/4_render_plots.py --domains cs_ro cs_cv

  # Указать папку вывода:
  python scripts/4_render_plots.py --out .outputs
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

from pipeline import render_plots
from utils.cli import load_domains
from utils.logging_setup import setup_logging


def main():
    ap = argparse.ArgumentParser(description="Сервис 4: построение графиков из данных БД")
    ap.add_argument("--domains", nargs="+", metavar="DOMAIN",
                    help="Список доменов (по умолчанию — все из domains.json)")
    ap.add_argument("--domains-file", default="config/domains.json")
    ap.add_argument("--out", default=".outputs",
                    help="Папка для графиков (по умолчанию .outputs)")
    ap.add_argument("--log-level", default="INFO",
                    choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    ap.add_argument("--log-format", default="text", choices=["text", "json"])
    args = ap.parse_args()

    setup_logging(
        level=args.log_level,
        log_file=_root / ".outputs" / "logs" / "render_plots.log",
        fmt=args.log_format,
    )

    domains = load_domains(args.domains_file, args.domains)

    mongo_uri = os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017")
    mongo_db = os.environ.get("MONGO_DB", "arxiv_trends")

    logging.info("render_plots: %d доменов → %s", len(domains), args.out)

    results = render_plots(
        domains=domains,
        mongo_uri=mongo_uri,
        mongo_db=mongo_db,
        out_dir=args.out,
    )

    print("\n=== Итог ===")
    for domain, r in results.items():
        if r.get("skipped"):
            print(f"  {domain:<14}  пропущено (нет агрегатов)")
        else:
            print(f"  {domain:<14}  графиков={r['plots']}")


if __name__ == "__main__":
    main()
