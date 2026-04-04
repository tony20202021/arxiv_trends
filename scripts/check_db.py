"""Проверка покрытия БД: домены, диапазон недель, суммарные данные.

Использование:
    python scripts/check_db.py
    python scripts/check_db.py --uri mongodb://127.0.0.1:27027 --db arxiv_trends
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

from utils.diagnostics import print_coverage


def main() -> None:
    ap = argparse.ArgumentParser(description="Покрытие БД по доменам")
    ap.add_argument("--uri", default=os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017"))
    ap.add_argument("--db",  default=os.environ.get("MONGO_DB",  "arxiv_trends"))
    args = ap.parse_args()

    print(f"MongoDB: {args.uri}  /  {args.db}\n")
    print_coverage(args.uri, args.db)


if __name__ == "__main__":
    main()
