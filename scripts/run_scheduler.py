"""Планировщик: запускает pipeline по таймауту в бесконечном цикле.

Использование:
    python backend/scripts/run_scheduler.py --interval-hours 6

Запускает один прогон сразу при старте, затем засыпает на interval-hours часов.
"""
from __future__ import annotations
import argparse
import json
import logging
import os
import signal
import time
from pathlib import Path

from dotenv import load_dotenv

from pipeline import run_all

logger = logging.getLogger(__name__)

_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    logger.info("Получен сигнал %d, завершаем после текущего прогона...", signum)
    _shutdown = True


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def run_once(domains: list[dict], mongo_uri: str, mongo_db: str,
             api_url: str, user_agent: str, out_dir: str) -> None:
    logger.info("=== Начало прогона pipeline ===")
    try:
        run_all(domains, mongo_uri, mongo_db, api_url, user_agent, out_dir)
        logger.info("=== Прогон завершён успешно ===")
    except Exception as exc:
        logger.error("=== Прогон завершился с ошибкой: %s ===", exc, exc_info=True)


def main():
    load_dotenv()

    ap = argparse.ArgumentParser(description="Планировщик arXiv Trends Pipeline")
    ap.add_argument("--interval-hours", type=float, default=6.0,
                    help="Интервал между прогонами в часах (по умолчанию: 6)")
    ap.add_argument("--domains", default="config/domains.json")
    ap.add_argument("--out", default=".outputs")
    ap.add_argument("--log-level", default="INFO",
                    choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    ap.add_argument("--run-once", action="store_true",
                    help="Запустить один прогон и выйти")
    args = ap.parse_args()

    _setup_logging(args.log_level)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    domains = json.loads(Path(args.domains).read_text(encoding="utf-8"))
    mongo_uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
    mongo_db = os.environ.get("MONGO_DB", "arxiv_trends")
    api_url = os.environ.get("ARXIV_API_URL", "https://export.arxiv.org/api/query")
    user_agent = os.environ.get("HTTP_USER_AGENT", "arxiv-trends-bot/0.1")
    interval_sec = args.interval_hours * 3600

    logger.info("Планировщик запущен. Интервал: %.1f ч.", args.interval_hours)

    if args.run_once:
        run_once(domains, mongo_uri, mongo_db, api_url, user_agent, args.out)
        return

    while not _shutdown:
        run_once(domains, mongo_uri, mongo_db, api_url, user_agent, args.out)

        if _shutdown:
            break

        logger.info("Следующий прогон через %.1f ч. (Ctrl+C для остановки)", args.interval_hours)
        # Спим маленькими интервалами чтобы реагировать на сигналы
        elapsed = 0.0
        sleep_chunk = 30.0
        while elapsed < interval_sec and not _shutdown:
            time.sleep(min(sleep_chunk, interval_sec - elapsed))
            elapsed += sleep_chunk

    logger.info("Планировщик остановлен.")


if __name__ == "__main__":
    import sys
    _root = Path(__file__).parent.parent
    sys.path.insert(0, str(_root / "backend"))
    sys.path.insert(0, str(_root))
    main()
