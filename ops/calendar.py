"""Weekday sessions and the month-end cheque date. NYSE holidays for 2026–2028."""

from __future__ import annotations

from datetime import date, timedelta

# Full closures. Early closes still count as a session.
NYSE_HOLIDAYS = {
    date(2026, 1, 1),
    date(2026, 1, 19),
    date(2026, 2, 16),
    date(2026, 4, 3),
    date(2026, 5, 25),
    date(2026, 6, 19),
    date(2026, 7, 3),
    date(2026, 9, 7),
    date(2026, 11, 26),
    date(2026, 12, 25),
    date(2027, 1, 1),
    date(2027, 1, 18),
    date(2027, 2, 15),
    date(2027, 3, 26),
    date(2027, 5, 31),
    date(2027, 6, 18),
    date(2027, 7, 5),
    date(2027, 9, 6),
    date(2027, 11, 25),
    date(2027, 12, 24),
    date(2027, 12, 31),
    date(2028, 1, 17),
    date(2028, 2, 21),
    date(2028, 4, 14),
    date(2028, 5, 29),
    date(2028, 6, 19),
    date(2028, 7, 4),
    date(2028, 9, 4),
    date(2028, 11, 23),
    date(2028, 12, 25),
}


def is_weekend(day: date) -> bool:
    return day.weekday() >= 5


def is_market_session(day: date) -> bool:
    return not is_weekend(day) and day not in NYSE_HOLIDAYS


def is_month_end_session(day: date) -> bool:
    """True when no later weekday session remains in this month."""
    cursor = day
    while True:
        cursor += timedelta(days=1)
        if cursor.month != day.month:
            return True
        if is_market_session(cursor):
            return False


def is_quarter_end_session(day: date) -> bool:
    return day.month in {3, 6, 9, 12} and is_month_end_session(day)


def is_year_end_session(day: date) -> bool:
    return day.month == 12 and is_month_end_session(day)


def cheque_due(day: date, schedule: str) -> bool:
    if schedule == "quarter_end":
        return is_quarter_end_session(day)
    if schedule == "year_end":
        return is_year_end_session(day)
    return False
