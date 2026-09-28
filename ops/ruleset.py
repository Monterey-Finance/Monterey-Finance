"""A rules change applies only after the audit entry exists."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from ops.audit import append_event
from ops.live_rules import BOOK_VERSION, live_rules
from ops.paths import STATE

ALLOWED = {
    "name_cap",
    "throttle",
    "breach_exit",
    "breach_monitor",
    "purify_schedule",
    "cost_bps",
    "rebalance_freq",
}
FORBIDDEN_SLEEVES = ("roic", "sue", "dual_momentum", "high_beta")


def proposals_path(root: Path | None = None) -> Path:
    return (root or STATE) / "rules_proposals.json"


def overlay_path(root: Path | None = None) -> Path:
    return (root or STATE) / "rules_overlay.json"


def propose(
    changes: dict,
    *,
    actor: str,
    reason: str,
    root: Path | None = None,
) -> dict:
    why = str(reason or "").strip()
    who = str(actor or "").strip()
    if not why or not who:
        raise ValueError("actor and reason are required")
    clean = _validate(changes)
    proposal = {
        "id": uuid.uuid4().hex,
        "status": "proposed",
        "actor": who,
        "reason": why,
        "changes": clean,
        "prior_version": BOOK_VERSION,
    }
    path = proposals_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    if path.exists():
        rows = list(json.loads(path.read_text(encoding="utf-8")).get("proposals") or [])
    rows.append(proposal)
    path.write_text(json.dumps({"proposals": rows}, indent=2) + "\n", encoding="utf-8")
    return proposal


def confirm(proposal_id: str, *, actor: str, root: Path | None = None) -> dict:
    who = str(actor or "").strip()
    if not who:
        raise ValueError("actor is required")
    path = proposals_path(root)
    if not path.exists():
        raise ValueError("no rules proposal")
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = list(payload.get("proposals") or [])
    found = None
    for row in rows:
        if row.get("id") == proposal_id:
            found = row
            break
    if found is None:
        raise ValueError("unknown rules proposal")
    if found.get("status") == "confirmed":
        raise ValueError("rules proposal is already confirmed")
    changes = _validate(found.get("changes") or {})
    current, existing = rules_for_run(root)
    merged = dict((existing or {}).get("changes") or {})
    merged.update(changes)
    merged = _validate(merged)
    old = {key: getattr(current.book, key) for key in merged}
    found["status"] = "confirmed"
    path.write_text(json.dumps({"proposals": rows}, indent=2) + "\n", encoding="utf-8")
    overlay = {
        "id": found["id"],
        "changes": merged,
        "book_version": BOOK_VERSION,
    }
    overlay_path(root).write_text(json.dumps(overlay, indent=2) + "\n", encoding="utf-8")
    append_event(
        "rules_version_bumped",
        actor=who,
        root=root,
        proposal_id=found["id"],
        reason=found.get("reason"),
        old=old,
        new=merged,
    )
    return overlay


def rules_for_run(root: Path | None = None):
    """Code defaults, then an overlay that has an audit entry."""
    rules = live_rules()
    path = overlay_path(root)
    if not path.exists():
        return rules, None
    overlay = json.loads(path.read_text(encoding="utf-8"))
    changes = _validate(overlay.get("changes") or {})
    if not changes:
        return rules, None
    return rules.with_book(**changes), overlay


def _validate(changes: dict) -> dict:
    if not changes:
        raise ValueError("a rules bump needs at least one change")
    unknown = set(changes) - ALLOWED
    if unknown:
        raise ValueError("cannot change " + ", ".join(sorted(unknown)))
    if "sleeve_weights" in changes:
        raise ValueError("sleeve weights stay on the frozen book")
    for name in FORBIDDEN_SLEEVES:
        if name in changes:
            raise ValueError(f"{name} stays out of the traded book")
    clean = {}
    for key, value in changes.items():
        if key == "name_cap":
            cap = float(value)
            if cap <= 0 or cap > 0.10:
                raise ValueError("name cap stays at or under 10%")
            clean[key] = cap
        elif key == "cost_bps":
            clean[key] = float(value)
        else:
            clean[key] = value
    return clean
