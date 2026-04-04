"""Пересчёт агрегатов и графиков на основе данных уже имеющихся в БД.

Статьи не скачиваются и не обрабатываются.

Примеры:
  # Все домены:
  python scripts/recompute_plots.py

  # Только выбранные:
  python scripts/recompute_plots.py --domains cs_cv cs_ro
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

from pipeline import recompute_plots


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main():
    ap = argparse.ArgumentParser(description="Пересчёт графиков из данных БД")
    ap.add_argument("--domains", nargs="+", metavar="DOMAIN",
                    help="Список доменов (по умолчанию — все из domains.json)")
    ap.add_argument("--domains-file", default="config/domains.json")
    ap.add_argument("--out", default=".outputs")
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

    logging.info("Пересчёт графиков: %d доменов", len(domains))

    results = recompute_plots(
        domains=domains,
        mongo_uri=mongo_uri,
        mongo_db=mongo_db,
        out_dir=args.out,
    )

    print("\n=== Итог ===")
    for domain, r in results.items():
        if r["weeks"] == 0:
            print(f"  {domain:<14}  нет данных")
        else:
            print(f"  {domain:<14}  недель={r['weeks']:>3}  "
                  f"популярные={r['popular'][:3]}  растущие={r['growing'][:3]}")


if __name__ == "__main__":
    main()
