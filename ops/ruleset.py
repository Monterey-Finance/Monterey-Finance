"""A rules change applies only after the audit entry exists.

Proposals edit BookSpec section fields. FrozenRules overlays stay so older
tests and notebooks keep working.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from ops.audit import append_event
from ops.live_rules import BOOK_VERSION, live_rules, live_spec
from ops.paths import STATE

ALLOWED = {
    "name_cap": ("construction", "name_cap"),
    "throttle": ("overlay", "kind"),
    "breach_exit": ("screen", "breach_exit"),
    "breach_monitor": ("screen", "breach_exit"),
    "purify_schedule": ("accounting", "purify"),
    "purify": ("accounting", "purify"),
    "cost_bps": ("accounting", "cost_bps"),
    "rebalance_freq": ("execution", "rebalance"),
    "drift_band": ("execution", "drift_band"),
    "min_trade": ("execution", "min_trade"),
    "confirm_days": ("overlay", "confirm_days"),
    "band": ("overlay", "band"),
    "off_exposure": ("overlay", "off_exposure"),
    "vol_target": ("overlay", "vol_target"),
    "sector_cap": ("construction", "sector_cap"),
    "pit": ("universe", "pit"),
    "sectors": ("screen", "sectors"),
    "dividends": ("accounting", "dividends"),
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
        "prior_hash": live_spec(root).hash(),
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
    old = {key: getattr(current.book, key) for key in merged if hasattr(current.book, key)}
    found["status"] = "confirmed"
    path.write_text(json.dumps({"proposals": rows}, indent=2) + "\n", encoding="utf-8")
    overlay = {
        "id": found["id"],
        "changes": _to_spec_sections(merged),
        "book_version": BOOK_VERSION,
        "spec_hash": live_spec(root).replace(**_to_spec_sections(merged)).hash(),
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
    raw = overlay.get("changes") or {}
    flat = _flatten(raw)
    if not flat:
        return rules, None
    kwargs = {}
    mapping = {
        "name_cap": "name_cap",
        "cost_bps": "cost_bps",
        "throttle": "throttle",
        "breach_exit": "breach_exit",
        "purify": "purify_schedule",
        "purify_schedule": "purify_schedule",
    }
    for key, value in flat.items():
        if key in mapping:
            kwargs[mapping[key]] = value
    if not kwargs:
        return rules, overlay
    return rules.with_book(**kwargs), overlay


def _to_spec_sections(changes: dict) -> dict:
    sections: dict[str, dict] = {}
    for key, value in changes.items():
        if key not in ALLOWED:
            continue
        section, field = ALLOWED[key]
        if key == "throttle" and value in {"spy_sma", "off", "none"}:
            value = "spy_sma" if value == "spy_sma" else "none"
        sections.setdefault(section, {})[field] = value
    return sections


def _flatten(changes: dict) -> dict:
    if not changes:
        return {}
    if any(k in changes for k in ("universe", "screen", "signal", "construction", "overlay", "execution", "accounting")):
        out = {}
        for section, fields in changes.items():
            if isinstance(fields, dict):
                for key, value in fields.items():
                    out[key if key != "purify" else "purify"] = value
            else:
                out[section] = fields
        return out
    return dict(changes)


def _validate(changes: dict) -> dict:
    if not changes:
        raise ValueError("a rules bump needs at least one change")
    flat = _flatten(changes)
    unknown = set(flat) - set(ALLOWED)
    if unknown:
        raise ValueError("cannot change " + ", ".join(sorted(unknown)))
    if "sleeve_weights" in flat:
        raise ValueError("sleeve weights stay on the frozen book")
    for name in FORBIDDEN_SLEEVES:
        if name in flat:
            raise ValueError(f"{name} stays out of the traded book")
    clean = {}
    for key, value in flat.items():
        if key == "name_cap":
            cap = float(value)
            if cap <= 0 or cap > 0.10:
                raise ValueError("name cap stays at or under 10%")
            clean[key] = cap
        elif key in {"cost_bps", "drift_band", "min_trade", "band", "off_exposure", "vol_target", "confirm_days", "sector_cap"}:
            clean[key] = value if value is None else float(value)
        else:
            clean[key] = value
    return clean
