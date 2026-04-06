"""Планировщик: запускает один шаг pipeline в бесконечном цикле.

Использование:
    python scripts/run_scheduler.py --step 1 --interval-hours 24
    python scripts/run_scheduler.py --step 2 --interval-hours 1
    python scripts/run_scheduler.py --step 3 --interval-hours 1

Шаги:
    1  — fetch_abstracts: скачивает статьи из arXiv API → articles
    2  — extract_keywords_batch: извлекает ключевые слова → articles + counts
    3  — recompute_aggregates + render_plots: пересчёт агрегатов и графиков

По умолчанию диапазон дат: от 1 года назад до сегодня (пересчитывается каждый прогон).
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import logging
import os
import signal
import time
from pathlib import Path

_root = Path(__file__).parent.parent
import sys
sys.path.insert(0, str(_root / "backend"))
sys.path.insert(0, str(_root))

from dotenv import load_dotenv
load_dotenv(_root / ".env")

from pipeline import fetch_abstracts, extract_keywords_batch, recompute_aggregates, render_plots

logger = logging.getLogger(__name__)

_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    logger.info("Получен сигнал %d, завершаем после текущего прогона...", signum)
    _shutdown = True


def _setup_logging(level: str, step: str) -> None:
    log_dir = _root / ".outputs" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_dir / f"scheduler_step{step}.log", encoding="utf-8"),
        ],
    )


def _date_range(from_date: dt.date | None, to_date: dt.date | None) -> tuple[dt.date, dt.date]:
    today = dt.date.today()
    return (
        from_date if from_date is not None else today - dt.timedelta(days=365),
        to_date  if to_date  is not None else today,
    )


def run_once(
    step: str,
    domains: list[dict],
    mongo_uri: str,
    mongo_db: str,
    api_url: str,
    user_agent: str,
    out_dir: str,
    from_date: dt.date | None,
    to_date: dt.date | None,
) -> None:
    logger.info("=== Начало прогона (шаг %s) ===", step)
    try:
        week_from, week_to = _date_range(from_date, to_date)

        if step == "1":
            fetch_abstracts(
                domains=domains,
                week_from=week_from,
                week_to=week_to,
                mongo_uri=mongo_uri,
                mongo_db=mongo_db,
                api_url=api_url,
                user_agent=user_agent,
            )

        elif step == "2":
            extract_keywords_batch(
                domains=domains,
                week_from=week_from,
                week_to=week_to,
                mongo_uri=mongo_uri,
                mongo_db=mongo_db,
            )

        elif step == "3":
            recompute_aggregates(
                domains=domains,
                mongo_uri=mongo_uri,
                mongo_db=mongo_db,
                date_from=week_from,
            )
            render_plots(
                domains=domains,
                mongo_uri=mongo_uri,
                mongo_db=mongo_db,
                out_dir=out_dir,
                date_from=week_from,
            )

        logger.info("=== Прогон завершён успешно ===")
    except Exception as exc:
        logger.error("=== Прогон завершился с ошибкой: %s ===", exc, exc_info=True)


def main():
    ap = argparse.ArgumentParser(description="Планировщик шага arXiv Trends Pipeline")
    ap.add_argument("--step", required=True, choices=["1", "2", "3"],
                    help="Шаг pipeline: 1=fetch, 2=extract, 3=aggregates+plots")
    ap.add_argument("--interval-hours", type=float, default=1.0,
                    help="Интервал между прогонами в часах (по умолчанию: 1)")
    ap.add_argument("--from", dest="from_date", metavar="YYYY-MM-DD", default=None,
                    help="Начало диапазона дат (по умолчанию: год назад от текущей даты)")
    ap.add_argument("--to", dest="to_date", metavar="YYYY-MM-DD", default=None,
                    help="Конец диапазона дат (по умолчанию: сегодня)")
    ap.add_argument("--domains", default="config/domains.json")
    ap.add_argument("--out", default=".outputs")
    ap.add_argument("--log-level", default="INFO",
                    choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    ap.add_argument("--run-once", action="store_true",
                    help="Запустить один прогон и выйти")
    args = ap.parse_args()

    _setup_logging(args.log_level, args.step)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    domains = json.loads(Path(args.domains).read_text(encoding="utf-8"))
    mongo_uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
    mongo_db = os.environ.get("MONGO_DB", "arxiv_trends")
    api_url = os.environ.get("ARXIV_API_URL", "https://export.arxiv.org/api/query")
    user_agent = os.environ.get("HTTP_USER_AGENT", "arxiv-trends-bot/0.1")
    interval_sec = args.interval_hours * 3600

    from_date = dt.date.fromisoformat(args.from_date) if args.from_date else None
    to_date   = dt.date.fromisoformat(args.to_date)   if args.to_date   else None

    logger.info("Планировщик запущен. Шаг=%s, интервал=%.1f ч.", args.step, args.interval_hours)

    kwargs = dict(
        step=args.step,
        domains=domains,
        mongo_uri=mongo_uri,
        mongo_db=mongo_db,
        api_url=api_url,
        user_agent=user_agent,
        out_dir=args.out,
        from_date=from_date,
        to_date=to_date,
    )

    if args.run_once:
        run_once(**kwargs)
        return

    while not _shutdown:
        run_once(**kwargs)

        if _shutdown:
            break

        logger.info("Следующий прогон через %.1f ч. (Ctrl+C для остановки)", args.interval_hours)
        elapsed = 0.0
        sleep_chunk = 30.0
        while elapsed < interval_sec and not _shutdown:
            time.sleep(min(sleep_chunk, interval_sec - elapsed))
            elapsed += sleep_chunk

    logger.info("Планировщик остановлен.")


if __name__ == "__main__":
    main()
