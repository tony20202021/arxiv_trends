from __future__ import annotations
import datetime as dt

import pytest

from utils import week_start, iter_week_starts, to_week_datetime, utc_today, iter_weeks_between


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


class TestIterWeeksBetween:
    def test_single_week(self):
        d = dt.date(2024, 1, 1)  # понедельник
        result = iter_weeks_between(d, d)
        assert result == [d]

    def test_two_weeks(self):
        start = dt.date(2024, 1, 1)
        end = dt.date(2024, 1, 8)
        result = iter_weeks_between(start, end)
        assert len(result) == 2
        assert result[0] == dt.date(2024, 1, 1)
        assert result[1] == dt.date(2024, 1, 8)

    def test_all_results_are_mondays(self):
        start = dt.date(2024, 1, 1)
        end = dt.date(2024, 3, 31)
        result = iter_weeks_between(start, end)
        for d in result:
            assert d.weekday() == 0, f"{d} не понедельник"

    def test_midweek_start_snapped_to_monday(self):
        wednesday = dt.date(2024, 1, 3)  # среда → понедельник Jan 1
        end = dt.date(2024, 1, 15)
        result = iter_weeks_between(wednesday, end)
        assert result[0] == dt.date(2024, 1, 1)

    def test_includes_both_endpoints(self):
        start = dt.date(2024, 1, 1)
        end = dt.date(2024, 1, 15)
        result = iter_weeks_between(start, end)
        assert dt.date(2024, 1, 1) in result
        assert dt.date(2024, 1, 15) in result

    def test_sorted_ascending(self):
        start = dt.date(2024, 1, 1)
        end = dt.date(2024, 3, 1)
        result = iter_weeks_between(start, end)
        assert result == sorted(result)
