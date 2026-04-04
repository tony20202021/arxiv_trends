from __future__ import annotations
import datetime as dt

import pytest

from utils import week_start, iter_week_starts, to_week_datetime, utc_today


class TestWeekStart:
    def test_monday_unchanged(self):
        monday = dt.date(2024, 1, 1)  # понедельник
        assert week_start(monday) == monday

    def test_wednesday_returns_monday(self):
        wednesday = dt.date(2024, 1, 3)
        assert week_start(wednesday) == dt.date(2024, 1, 1)

    def test_sunday_returns_monday(self):
        sunday = dt.date(2024, 1, 7)
        assert week_start(sunday) == dt.date(2024, 1, 1)


class TestIterWeekStarts:
    def test_returns_correct_count(self):
        today = dt.date(2024, 1, 15)
        result = iter_week_starts(today, 4)
        assert len(result) == 4

    def test_sorted_ascending(self):
        today = dt.date(2024, 1, 15)
        result = iter_week_starts(today, 4)
        assert result == sorted(result)

    def test_all_are_mondays(self):
        today = dt.date(2024, 6, 10)
        result = iter_week_starts(today, 8)
        for d in result:
            assert d.weekday() == 0, f"{d} is not a Monday"

    def test_last_week_is_current_week(self):
        today = dt.date(2024, 1, 17)  # среда
        result = iter_week_starts(today, 3)
        assert result[-1] == week_start(today)


class TestToWeekDatetime:
    def test_has_utc_timezone(self):
        d = dt.date(2024, 3, 4)
        dt_result = to_week_datetime(d)
        assert dt_result.tzinfo == dt.timezone.utc

    def test_midnight(self):
        d = dt.date(2024, 3, 4)
        dt_result = to_week_datetime(d)
        assert dt_result.hour == 0
        assert dt_result.minute == 0
        assert dt_result.second == 0


class TestUtcToday:
    def test_returns_date(self):
        result = utc_today()
        assert isinstance(result, dt.date)
