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

Circuit breaker:
    После ALERT_FAIL_THRESHOLD последовательных ошибок отправляет Telegram-алерт
    (если заданы TELEGRAM_BOT_TOKEN и ALERT_TELEGRAM_CHAT_ID в .env).
    Сервис НЕ останавливается — продолжает пытаться при следующем интервале.
"""
from __future__ import annotations
import argparse
import ctypes
import datetime as dt
import gc
import json
import logging
import os
import signal
import time
import urllib.request
import urllib.parse
from pathlib import Path

_root = Path(__file__).parent.parent
import sys
sys.path.insert(0, str(_root / "backend"))
sys.path.insert(0, str(_root))

from dotenv import load_dotenv
load_dotenv(_root / ".env")

from pipeline import fetch_abstracts, extract_keywords_batch, recompute_aggregates, render_plots
from utils.cli import parse_date
from utils.logging_setup import setup_logging

logger = logging.getLogger(__name__)

_shutdown = False

# Число последовательных ошибок до отправки Telegram-алерта
ALERT_FAIL_THRESHOLD = 3


def _handle_signal(signum, frame):
    global _shutdown
    logger.info("Получен сигнал %d, завершаем после текущего прогона...", signum)
    _shutdown = True


def _send_telegram_alert(token: str, chat_id: str, text: str) -> None:
    """Отправить сообщение через Telegram Bot API (без внешних зависимостей)."""
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10):
            pass
        logger.info("Telegram-алерт отправлен в chat_id=%s", chat_id)
    except Exception as exc:
        logger.warning("Не удалось отправить Telegram-алерт: %s", exc)




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
) -> bool:
    """Запустить один прогон. Возвращает True при успехе, False при ошибке."""
    _STEP_NAMES = {"1": "fetch abstracts", "2": "extract keywords", "3": "aggregates + plots"}
    logger.info("=== Начало прогона: %s ===", _STEP_NAMES.get(step, step))
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
        return True
    except Exception as exc:
        logger.error("=== Прогон завершился с ошибкой (%s): %s ===",
                     _STEP_NAMES.get(step, step), exc, exc_info=True)
        return False


def main():
    ap = argparse.ArgumentParser(description="Планировщик шага arXiv Trends Pipeline")
    ap.add_argument("--step", required=True, choices=["1", "2", "3"],
                    help="Шаг pipeline: 1=fetch, 2=extract, 3=aggregates+plots")
    ap.add_argument("--interval-hours", type=float, default=1.0,
                    help="Интервал между прогонами в часах (по умолчанию: 1)")
    ap.add_argument("--from", dest="from_date", metavar="YYYY-MM-DD", default=None,
                    type=parse_date,
                    help="Начало диапазона дат (по умолчанию: год назад от текущей даты)")
    ap.add_argument("--to", dest="to_date", metavar="YYYY-MM-DD", default=None,
                    type=parse_date,
                    help="Конец диапазона дат (по умолчанию: сегодня)")
    ap.add_argument("--domains", default="config/domains.json")
    ap.add_argument("--out", default=".outputs")
    ap.add_argument("--log-level", default="INFO",
                    choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    ap.add_argument("--log-format", default="text", choices=["text", "json"])
    ap.add_argument("--run-once", action="store_true",
                    help="Запустить один прогон и выйти")
    args = ap.parse_args()

    setup_logging(
        level=args.log_level,
        log_file=_root / ".outputs" / "logs" / f"scheduler_step{args.step}.log",
        fmt=args.log_format,
    )

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    domains = json.loads(Path(args.domains).read_text(encoding="utf-8"))
    mongo_uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
    mongo_db = os.environ.get("MONGO_DB", "arxiv_trends")
    api_url = os.environ.get("ARXIV_API_URL", "https://export.arxiv.org/api/query")
    user_agent = os.environ.get("HTTP_USER_AGENT", "arxiv-trends-bot/0.1")
    interval_sec = args.interval_hours * 3600

    from_date = args.from_date  # уже dt.date благодаря type=parse_date
    to_date   = args.to_date

    tg_token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    tg_chat_id = os.environ.get("ALERT_TELEGRAM_CHAT_ID", "")

    _STEP_NAMES = {"1": "fetch abstracts", "2": "extract keywords", "3": "aggregates + plots"}
    logger.info("Планировщик запущен. Шаг %s (%s), интервал=%.1f ч.",
                args.step, _STEP_NAMES.get(args.step, "?"), args.interval_hours)
    if tg_token and tg_chat_id:
        logger.info("Telegram-алерты включены (chat_id=%s, порог=%d ошибок)", tg_chat_id, ALERT_FAIL_THRESHOLD)
    else:
        logger.info("Telegram-алерты отключены (TELEGRAM_BOT_TOKEN / ALERT_TELEGRAM_CHAT_ID не заданы)")

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

    consecutive_failures = 0

    while not _shutdown:
        success = run_once(**kwargs)
        gc.collect()
        try:
            ctypes.cdll.LoadLibrary("libc.so.6").malloc_trim(0)
        except Exception:
            pass

        if success:
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            logger.warning(
                "Последовательных ошибок: %d / %d",
                consecutive_failures, ALERT_FAIL_THRESHOLD,
            )
            if consecutive_failures >= ALERT_FAIL_THRESHOLD and tg_token and tg_chat_id:
                hostname = os.uname().nodename if hasattr(os, "uname") else "unknown"
                msg = (
                    f"⚠️ arXiv Trends — шаг {args.step} ({_STEP_NAMES.get(args.step, '?')}) упал {consecutive_failures} раз подряд\n"
                    f"Хост: {hostname}\n"
                    f"Время: {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                    f"Интервал: {args.interval_hours} ч."
                )
                _send_telegram_alert(tg_token, tg_chat_id, msg)
                consecutive_failures = 0  # сброс счётчика после алерта

        if _shutdown:
            break

        next_run = dt.datetime.now(dt.timezone.utc).astimezone() + dt.timedelta(seconds=interval_sec)
        logger.info(
            "Следующий прогон через %.1f ч. (~%s). Ctrl+C для остановки.",
            args.interval_hours,
            next_run.strftime("%H:%M %Z"),
        )
        elapsed = 0.0
        sleep_chunk = 30.0
        while elapsed < interval_sec and not _shutdown:
            time.sleep(min(sleep_chunk, interval_sec - elapsed))
            elapsed += sleep_chunk

    logger.info("Планировщик остановлен.")


if __name__ == "__main__":
    main()
