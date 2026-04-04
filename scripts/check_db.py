"""Диагностика БД: покрытие по доменам и топ ключевых слов.

Использование:
    python scripts/check_db.py
    python scripts/check_db.py --top
    python scripts/check_db.py --top --top-n 20
    python scripts/check_db.py --uri mongodb://host:port --db db_name
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

from utils.diagnostics import print_coverage, print_top_keywords


def main() -> None:
    ap = argparse.ArgumentParser(description="Диагностика БД")
    ap.add_argument("--uri",   default=os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017"))
    ap.add_argument("--db",    default=os.environ.get("MONGO_DB",  "arxiv_trends"))
    ap.add_argument("--top",   action="store_true", help="Показать топ ключевых слов")
    ap.add_argument("--top-n", type=int, default=10, dest="top_n")
    args = ap.parse_args()

    print(f"MongoDB: {args.uri}  /  {args.db}\n")

    if args.top:
        print_top_keywords(args.uri, args.db, args.top_n)
    else:
        print_coverage(args.uri, args.db)


if __name__ == "__main__":
    main()
