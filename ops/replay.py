"""Walk many sessions in one process. The market history is loaded once."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

from ops.calendar import is_market_session
from ops.data import load_lab, resolve_as_of
from ops.ledger import already_marked
from ops.session import run_session


@dataclass
class ReplayResult:
    start: date
    end: date
    reached: date | None
    sessions: int
    complete: bool

    def as_dict(self) -> dict:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "reached": None if self.reached is None else self.reached.isoformat(),
            "sessions": self.sessions,
            "complete": self.complete,
        }


def replay_range(
    start: date | str,
    end: date | str,
    *,
    budget_s: float | None = None,
    lookback_days: int = 550,
    save_every: int = 21,
    on_checkpoint: Callable[[date], None] | None = None,
    breaches: bool = True,
) -> ReplayResult:
    """Run each market session from ``start`` through ``end``.

    Weekends, holidays, and days already on the NAV ledger are skipped.
    The stock list is built once per monthly snapshot and reused until the
    next one. The SPY cash switch still updates every session.
    """
    first = resolve_as_of(start)
    last = resolve_as_of(end)
    if last < first:
        raise ValueError("replay end is before start")

    pending = _pending_sessions(first, last)
    if not pending:
        return ReplayResult(first, last, _last_marked(first, last), 0, True)

    span = (last - pending[0]).days + int(lookback_days)
    lab = load_lab(last, lookback_days=span)
    selection_cache: dict = {}
    deadline = None if budget_s is None else time.monotonic() + float(budget_s)
    reached: date | None = None
    done = 0
    since_save = 0
    for day in pending:
        if deadline is not None and done > 0 and time.monotonic() >= deadline:
            break
        run_session(
            day,
            lab=lab,
            refresh=False,
            breaches=breaches,
            selection_cache=selection_cache,
            cache_dividends=True,
        )
        reached = day
        done += 1
        since_save += 1
        if on_checkpoint is not None and save_every > 0 and since_save >= save_every:
            on_checkpoint(day)
            since_save = 0

    complete = reached is not None and reached >= pending[-1]
    return ReplayResult(first, last, reached, done, complete)


def _pending_sessions(start: date, end: date) -> list[date]:
    days: list[date] = []
    cursor = start
    while cursor <= end:
        if is_market_session(cursor) and not already_marked(cursor):
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _last_marked(start: date, end: date) -> date | None:
    cursor = end
    while cursor >= start:
        if is_market_session(cursor) and already_marked(cursor):
            return cursor
        cursor -= timedelta(days=1)
    return None
