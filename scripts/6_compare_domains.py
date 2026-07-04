"""Сервис 6: кросс-доменные сравнительные графики.

Строит графики показывающие как конкретный термин менялся по разным доменам.
Например: как рос интерес к 'diffusion model' в cs_cv, cs_lg и stat_ml.

Использование:
    # Сравнить все домены по ключевым словам из топ-популярных:
    python scripts/6_compare_domains.py --auto-keywords

    # Указать конкретные термины:
    python scripts/6_compare_domains.py --keywords "diffusion model" "transformer" "federated learning"

    # Только выбранные домены:
    python scripts/6_compare_domains.py --keywords "attention" --domains cs_lg cs_cv stat_ml

Графики сохраняются в .outputs/plots/_compare/<keyword_slug>.png
"""
from __future__ import annotations
import argparse
import logging
import os
import sys
from pathlib import Path

import pandas as pd
from slugify import slugify

_root = Path(__file__).parent.parent
sys.path.insert(0, str(_root / "backend"))
sys.path.insert(0, str(_root))

from dotenv import load_dotenv
load_dotenv(_root / ".env")

from storage.mongo import MongoStore
from plots.plotter import plot_keyword_across_domains
from utils.cli import load_domains
from utils.logging_setup import setup_logging

logger = logging.getLogger(__name__)


def _get_keyword_series(store: MongoStore, domain: str, keyword: str) -> pd.Series:
    """Вернуть временной ряд (week_start → count) для данного домена и ключевого слова."""
    rows = store.get_keyword_history(domain, keyword)
    if not rows:
        return pd.Series(dtype=float)
    return pd.Series(
        {r["week_start"]: r["count"] for r in rows},
        name=keyword,
    )


def render_compare(
    keywords: list[str],
    domains: list[dict],
    store: MongoStore,
    out_dir: Path,
) -> dict:
    """Построить кросс-доменные графики для каждого ключевого слова."""
    compare_dir = out_dir / "plots" / "_compare"
    compare_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    for keyword in keywords:
        domain_series: dict[str, pd.Series] = {}
        for domain in domains:
            dname = domain["domain"]
            series = _get_keyword_series(store, dname, keyword)
            if not series.empty:
                domain_series[dname] = series

        if not domain_series:
            logger.warning("Ключевое слово '%s': данных нет ни в одном домене", keyword)
            results[keyword] = {"domains": 0, "path": None}
            continue

        out_path = compare_dir / f"{slugify(keyword)}.png"
        plot_keyword_across_domains(
            keyword=keyword,
            domain_series=domain_series,
            title=f"'{keyword}' по доменам",
            out_path=out_path,
        )
        logger.info("'%s': %d доменов → %s", keyword, len(domain_series), out_path)
        results[keyword] = {"domains": len(domain_series), "path": str(out_path)}

    return results


def _auto_keywords(store: MongoStore, domains: list[dict], top_n: int = 10) -> list[str]:
    """Собрать топ-N ключевых слов из агрегатов по всем доменам."""
    agg_col = store.db["aggregates"]
    keyword_set: set[str] = set()
    for domain in domains:
        agg = agg_col.find_one({"domain": domain["domain"]}, {"_id": 0})
        if agg:
            keyword_set.update(agg.get("top_popular", [])[:top_n])
            keyword_set.update(agg.get("top_growing", [])[:top_n])
    return sorted(keyword_set)


def main() -> None:
    ap = argparse.ArgumentParser(description="Сервис 6: кросс-доменные сравнительные графики")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--keywords", nargs="+", metavar="KEYWORD",
                       help="Список ключевых слов для сравнения")
    group.add_argument("--auto-keywords", action="store_true", dest="auto_keywords",
                       help="Взять ключевые слова из топ-популярных/растущих агрегатов")
    ap.add_argument("--domains", nargs="+", metavar="DOMAIN",
                    help="Список доменов (по умолчанию — все из domains.json)")
    ap.add_argument("--domains-file", default="config/domains.json")
    ap.add_argument("--out", default=".outputs",
                    help="Папка вывода (по умолчанию .outputs)")
    ap.add_argument("--log-level", default="INFO",
                    choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    ap.add_argument("--log-format", default="text", choices=["text", "json"])
    args = ap.parse_args()

    setup_logging(
        level=args.log_level,
        log_file=_root / ".outputs" / "logs" / "compare_domains.log",
        fmt=args.log_format,
    )

    domains = load_domains(args.domains_file, args.domains)

    mongo_uri = os.environ.get("MONGO_URI", "mongodb://127.0.0.1:8627")
    mongo_db  = os.environ.get("MONGO_DB",  "arxiv_trends")
    store = MongoStore(mongo_uri, mongo_db)

    if args.auto_keywords:
        keywords = _auto_keywords(store, domains)
        if not keywords:
            logger.error("Нет агрегатов в БД. Сначала запустите скрипт 3.")
            sys.exit(1)
        logger.info("Авто-ключевые слова (%d): %s", len(keywords), keywords)
    else:
        keywords = args.keywords

    results = render_compare(
        keywords=keywords,
        domains=domains,
        store=store,
        out_dir=Path(args.out),
    )

    print("\n=== Итог ===")
    for kw, r in results.items():
        if r["path"]:
            print(f"  '{kw}'  →  {r['domains']} доменов  →  {r['path']}")
        else:
            print(f"  '{kw}'  →  нет данных")


if __name__ == "__main__":
    main()
