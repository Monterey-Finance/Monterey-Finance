"""Append-only operator log. Entries are recorded, not a legal sign-off."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ops.paths import STATE

EVENT_TYPES = (
    "run_completed",
    "run_skipped",
    "run_halted",
    "order_batch_approved",
    "order_batch_cancelled",
    "purification_posted",
    "rules_version_bumped",
    "override",
    "halt_cleared",
    "cash_deposit",
    "cash_withdrawal",
    "contribution_set",
)


def audit_path(root: Path | None = None) -> Path:
    return (root or STATE) / "audit.jsonl"


def append_event(
    event_type: str,
    *,
    actor: str,
    root: Path | None = None,
    **fields: Any,
) -> dict:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown audit event {event_type}")
    who = str(actor or "").strip()
    if not who:
        raise ValueError("actor is required")
    row = {
        "id": uuid.uuid4().hex,
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "actor": who,
        "recorded_not_legal_signoff": True,
    }
    row.update(fields)
    path = audit_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, default=str) + "\n")
    return row


def read_events(
    root: Path | None = None,
    *,
    event_type: str | None = None,
    since: str | None = None,
) -> list[dict]:
    path = audit_path(root)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if event_type and row.get("type") != event_type:
            continue
        if since and str(row.get("ts", "")) < since:
            continue
        rows.append(row)
    return rows
