TODO сделать разные скрипты для запуска 
БД
фронтенд
бэкенд (в нем возможно разные сервисы для скачивания с архива и для выбора ключевых слов через ЛЛМ)


from __future__ import annotations
import argparse
import json
import os

from dotenv import load_dotenv

from src.arxiv_trends.pipeline import run_all


def main():
    load_dotenv()

    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["full"], default="full")
    ap.add_argument("--domains", default="config/domains.json")
    args = ap.parse_args()

    domains = json.loads(Path(args.domains).read_text(encoding="utf-8"))

    mongo_uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
    mongo_db = os.environ.get("MONGO_DB", "arxiv_trends")
    api_url = os.environ.get("ARXIV_API_URL", "https://export.arxiv.org/api/query")
    user_agent = os.environ.get("HTTP_USER_AGENT", "arxiv-trends-bot/0.1")

    run_all(domains, mongo_uri, mongo_db, api_url, user_agent, args.out)


if __name__ == "__main__":
    from pathlib import Path
    main()
