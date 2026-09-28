"""Decide whether today's session should run. The caller supplies the job."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Callable

from ops.audit import append_event
from ops.calendar import is_market_session, is_weekend
from ops.data import resolve_as_of
from ops.ledger import already_marked


def session_status(as_of: date, root: Path | None = None) -> tuple[bool, str]:
    if is_weekend(as_of):
        return False, "weekend"
    if not is_market_session(as_of):
        return False, "market holiday"
    if already_marked(as_of, root):
        return False, "already marked"
    return True, "due"


def run_schedule(
    as_of: date | str | None = "today",
    *,
    root: Path | None = None,
    dry_run: bool = False,
    actor: str = "scheduler",
    runner: Callable | None = None,
) -> dict:
    day = resolve_as_of(as_of)
    due, reason = session_status(day, root)
    if not due:
        if not dry_run:
            append_event("run_skipped", actor=actor, root=root, as_of=day.isoformat(), reason=reason)
        return {"status": "skipped", "as_of": day.isoformat(), "reason": reason}
    if dry_run:
        return {"status": "dry_run", "as_of": day.isoformat(), "reason": "due"}
    if runner is None:
        raise ValueError("schedule needs a session runner")
    result = runner(day)
    return {"status": "ran", "as_of": day.isoformat(), "result": result}
