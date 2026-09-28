"""Order batch: draft, approved, executing, completed. Cancel only from draft."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ops.paths import STATE

ALLOWED = {
    "draft": {"approved", "cancelled", "halted"},
    "approved": {"executing", "halted"},
    "executing": {"completed", "halted"},
    "completed": set(),
    "halted": set(),
    "cancelled": set(),
}


def batches_path(root: Path | None = None) -> Path:
    return (root or STATE) / "batches.json"


def load_batches(root: Path | None = None) -> list[dict]:
    path = batches_path(root)
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload.get("batches") or [])


def save_batch(batch: dict, root: Path | None = None) -> dict:
    batches = load_batches(root)
    replaced = False
    for index, row in enumerate(batches):
        if row.get("id") == batch.get("id"):
            batches[index] = batch
            replaced = True
            break
    if not replaced:
        batches.append(batch)
    path = batches_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"batches": batches}, indent=2, default=str) + "\n", encoding="utf-8")
    return batch


def new_batch(
    as_of,
    orders: list[dict],
    targets: dict[str, float],
    *,
    actor: str = "session",
) -> dict:
    day = as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of)[:10]
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": f"{day}-{uuid.uuid4().hex[:8]}",
        "as_of": day,
        "status": "draft",
        "orders": orders,
        "targets": targets,
        "actor": actor,
        "history": [{"status": "draft", "at": now, "actor": actor}],
    }


def transition(batch: dict, status: str, *, actor: str) -> dict:
    current = batch.get("status")
    if status not in ALLOWED.get(current, set()):
        raise ValueError(f"cannot move a batch from {current} to {status}")
    now = datetime.now(timezone.utc).isoformat()
    batch["status"] = status
    batch["history"] = list(batch.get("history") or [])
    batch["history"].append({"status": status, "at": now, "actor": actor})
    return batch


def latest_with_status(root: Path | None, as_of, status: str) -> dict | None:
    day = as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of)[:10]
    matches = [
        row
        for row in load_batches(root)
        if str(row.get("as_of"))[:10] == day and row.get("status") == status
    ]
    if not matches:
        return None
    return matches[-1]


def batch_by_id(root: Path | None, batch_id: str) -> dict | None:
    for row in load_batches(root):
        if row.get("id") == batch_id:
            return row
    return None


def public_batch(batch: dict | None) -> dict[str, Any]:
    if not batch:
        return {}
    return {"batch_id": batch.get("id"), "batch_status": batch.get("status")}
