"""Сервис 3: пересчёт агрегатов (топ-популярные / топ-растущие) из данных БД.

Читает только из БД. arXiv API не используется. Графики не строятся.
Использует все недели которые есть в weekly_keyword_counts для каждого домена.

Выполнять после 2_extract_keywords.py.
Для построения графиков запустить 4_render_plots.py.

Примеры:
  # Все домены:
  python scripts/3_recompute_aggregates.py

  # Только выбранные:
  python scripts/3_recompute_aggregates.py --domains cs_ro cs_cv

  # Пересчитать принудительно, даже если агрегаты уже актуальны:
  python scripts/3_recompute_aggregates.py --force
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

from pipeline import recompute_aggregates


def _setup_logging(level: str) -> None:
    log_dir = _root / ".outputs" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_dir / "recompute_aggregates.log", encoding="utf-8"),
        ],
    )


def main():
    ap = argparse.ArgumentParser(description="Сервис 3: пересчёт агрегатов из данных БД")
    ap.add_argument("--domains", nargs="+", metavar="DOMAIN",
                    help="Список доменов (по умолчанию — все из domains.json)")
    ap.add_argument("--domains-file", default="config/domains.json")
    ap.add_argument("--force", action="store_true",
                    help="Пересчитать даже если агрегаты уже актуальны")
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

    logging.info("recompute_aggregates: %d доменов", len(domains))

    results = recompute_aggregates(
        domains=domains,
        mongo_uri=mongo_uri,
        mongo_db=mongo_db,
        force=args.force,
    )

    print("\n=== Итог ===")
    for domain, r in results.items():
        if r.get("skipped"):
            print(f"  {domain:<14}  актуально, пропущено")
        elif r["weeks"] == 0:
            print(f"  {domain:<14}  нет данных в БД")
        else:
            print(f"  {domain:<14}  недель={r['weeks']:>3}  "
                  f"популярные={r['popular']}  растущие={r['growing']}")


if __name__ == "__main__":
    main()
