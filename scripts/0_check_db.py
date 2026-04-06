"""Диагностика БД: покрытие по доменам и топ ключевых слов.

Использование:
    python scripts/0_check_db.py coverage
    python scripts/0_check_db.py top [--top-n 20]
    python scripts/0_check_db.py latest
    python scripts/0_check_db.py search --keyword "neural network" [--limit 10]
    python scripts/0_check_db.py --uri mongodb://host:port --db db_name coverage
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

from utils.diagnostics import print_coverage, print_top_keywords, print_latest, print_search


def main() -> None:
    ap = argparse.ArgumentParser(description="Диагностика БД")
    ap.add_argument("--uri",   default=os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017"))
    ap.add_argument("--db",    default=os.environ.get("MONGO_DB",  "arxiv_trends"))
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("coverage", help="Покрытие БД по доменам (недели, упоминания)")

    top_p = sub.add_parser("top", help="Топ ключевых слов")
    top_p.add_argument("--top-n", type=int, default=10, dest="top_n")

    sub.add_parser("latest", help="Последняя запись в каждой коллекции")

    search_p = sub.add_parser("search", help="Поиск статей по ключевому слову")
    search_p.add_argument("--keyword", required=True, help="Ключевое слово для поиска")
    search_p.add_argument("--limit", type=int, default=10, help="Максимальное число результатов")

    args = ap.parse_args()

    if not args.cmd:
        ap.print_help()
        sys.exit(0)

    print(f"MongoDB: {args.uri}  /  {args.db}\n")

    if args.cmd == "top":
        print_top_keywords(args.uri, args.db, args.top_n)
    elif args.cmd == "coverage":
        print_coverage(args.uri, args.db)
    elif args.cmd == "latest":
        print_latest(args.uri, args.db)
    elif args.cmd == "search":
        print_search(args.uri, args.db, args.keyword, args.limit)


if __name__ == "__main__":
    main()
