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

from pipeline import render_plots


def _setup_logging(level: str) -> None:
    log_dir = _root / ".outputs" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_dir / "render_plots.log", encoding="utf-8"),
        ],
    )


def main():
    ap = argparse.ArgumentParser(description="Сервис 4: построение графиков из данных БД")
    ap.add_argument("--domains", nargs="+", metavar="DOMAIN",
                    help="Список доменов (по умолчанию — все из domains.json)")
    ap.add_argument("--domains-file", default="config/domains.json")
    ap.add_argument("--out", default=".outputs",
                    help="Папка для графиков (по умолчанию .outputs)")
    ap.add_argument("--log-level", default="INFO",
                    choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = ap.parse_args()

    _setup_logging(args.log_level)

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
