from __future__ import annotations
import datetime as dt
from typing import List


def utc_today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def week_start(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def iter_week_starts(end_date: dt.date, weeks: int) -> List[dt.date]:
    end_ws = week_start(end_date)
    return [end_ws - dt.timedelta(weeks=i) for i in reversed(range(weeks))]


def to_week_datetime(d: dt.date) -> dt.datetime:
    # Monday 00:00 UTC
    return dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc)


def last_complete_week_start() -> dt.datetime:
    """Понедельник последней полностью завершённой недели (naive UTC).

    Текущая неделя исключается, так как данные по ней неполные.
    Возвращает naive datetime для совместимости с значениями из MongoDB.
    """
    today = dt.datetime.now(dt.timezone.utc).date()
    this_monday = week_start(today)
    last_monday = this_monday - dt.timedelta(weeks=1)
    return dt.datetime(last_monday.year, last_monday.month, last_monday.day)  # naive


def iter_weeks_between(week_from: dt.date, week_to: dt.date) -> List[dt.date]:
    """Список понедельников от week_from до week_to включительно."""
    start = week_start(week_from)
    end = week_start(week_to)
    result = []
    cur = start
    while cur <= end:
        result.append(cur)
        cur += dt.timedelta(weeks=1)
    return result
