"""Общие утилиты для argparse: валидация дат и доменов."""
from __future__ import annotations
import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path


def parse_date(value: str) -> dt.date:
    """Тип для argparse: парсит дату YYYY-MM-DD с понятным сообщением об ошибке."""
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Неверный формат даты: '{value}'. Используйте YYYY-MM-DD (например, 2026-01-01)"
        )


def load_domains(domains_file: str, domain_filter: list[str] | None) -> list[dict]:
    """Загрузить домены из JSON и опционально отфильтровать.

    Args:
        domains_file: путь к domains.json
        domain_filter: список slug-имён доменов или None (все домены)

    Returns:
        Список domain-dict. Завершает программу с ошибкой если указаны неизвестные домены.
    """
    all_domains: list[dict] = json.loads(Path(domains_file).read_text(encoding="utf-8"))

    if not domain_filter:
        return all_domains

    known = {d["domain"] for d in all_domains}
    unknown = set(domain_filter) - known
    if unknown:
        logging.error(
            "Неизвестные домены: %s\nДоступные: %s",
            ", ".join(sorted(unknown)),
            ", ".join(sorted(known)),
        )
        sys.exit(1)

    return [d for d in all_domains if d["domain"] in set(domain_filter)]


def validate_date_range(from_date: dt.date, to_date: dt.date) -> None:
    """Проверить что from_date <= to_date. Завершает программу с ошибкой если нет."""
    if from_date > to_date:
        logging.error(
            "--from (%s) должна быть <= --to (%s)", from_date, to_date
        )
        sys.exit(1)
