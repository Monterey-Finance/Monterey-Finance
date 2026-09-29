"""Weekday sessions and the month-end cheque date. NYSE holidays for 2020–2028."""

from __future__ import annotations

from datetime import date, timedelta

# Full closures. Early closes still count as a session.
NYSE_HOLIDAYS = {
    date(2020, 1, 1),
    date(2020, 1, 20),
    date(2020, 2, 17),
    date(2020, 4, 10),
    date(2020, 5, 25),
    date(2020, 7, 3),
    date(2020, 9, 7),
    date(2020, 11, 26),
    date(2020, 12, 25),
    date(2021, 1, 1),
    date(2021, 1, 18),
    date(2021, 2, 15),
    date(2021, 4, 2),
    date(2021, 5, 31),
    date(2021, 7, 5),
    date(2021, 9, 6),
    date(2021, 11, 25),
    date(2021, 12, 24),
    date(2022, 1, 17),
    date(2022, 2, 21),
    date(2022, 4, 15),
    date(2022, 5, 30),
    date(2022, 6, 20),
    date(2022, 7, 4),
    date(2022, 9, 5),
    date(2022, 11, 24),
    date(2022, 12, 26),
    date(2023, 1, 2),
    date(2023, 1, 16),
    date(2023, 2, 20),
    date(2023, 4, 7),
    date(2023, 5, 29),
    date(2023, 6, 19),
    date(2023, 7, 4),
    date(2023, 9, 4),
    date(2023, 11, 23),
    date(2023, 12, 25),
    date(2024, 1, 1),
    date(2024, 1, 15),
    date(2024, 2, 19),
    date(2024, 3, 29),
    date(2024, 5, 27),
    date(2024, 6, 19),
    date(2024, 7, 4),
    date(2024, 9, 2),
    date(2024, 11, 28),
    date(2024, 12, 25),
    date(2025, 1, 1),
    date(2025, 1, 9),
    date(2025, 1, 20),
    date(2025, 2, 17),
    date(2025, 4, 18),
    date(2025, 5, 26),
    date(2025, 6, 19),
    date(2025, 7, 4),
    date(2025, 9, 1),
    date(2025, 11, 27),
    date(2025, 12, 25),
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
