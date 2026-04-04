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
