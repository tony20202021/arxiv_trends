"""Централизованная настройка логирования.

Поддерживает два формата:
  text  — стандартный человекочитаемый (%(asctime)s ...)
  json  — структурированный JSON (одна строка на событие)

Пример использования:
    from utils.logging_setup import setup_logging
    setup_logging(level="INFO", log_file=Path(".outputs/logs/fetch.log"), fmt="json")
"""
from __future__ import annotations
import json
import logging
import sys
import traceback
from pathlib import Path


class _JsonFormatter(logging.Formatter):
    """Форматтер: одна JSON-строка на лог-запись."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        obj: dict = {
            "ts":      self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level":   record.levelname,
            "logger":  record.name,
            "msg":     record.getMessage(),
        }
        if record.exc_info:
            obj["exc"] = traceback.format_exception(*record.exc_info)
        return json.dumps(obj, ensure_ascii=False)


def setup_logging(
    level: str = "INFO",
    log_file: Path | None = None,
    fmt: str = "text",
) -> None:
    """Настроить корневой логгер.

    Args:
        level:    уровень логирования (DEBUG, INFO, WARNING, ERROR)
        log_file: путь к файлу (None — только stdout)
        fmt:      "text" или "json"
    """
    if fmt == "json":
        formatter: logging.Formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    for h in handlers:
        h.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    # Очищаем старые обработчики чтобы не дублировать при повторном вызове
    root.handlers.clear()
    for h in handlers:
        root.addHandler(h)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
