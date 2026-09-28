"""Purification ledger. Ex-date posts cash immediately. A cheque date posts accruals once."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ops.account import PaperAccount
from ops.audit import append_event
from ops.calendar import cheque_due
from ops.paths import STATE
from ops.purify_ops import accrue_purification, purification_lines

COLUMNS = (
    "key",
    "symbol",
    "ex_date",
    "shares",
    "gross_dividend",
    "impure_ratio",
    "amount",
    "status",
    "actor",
    "posted_at",
)
DISCLAIMER = "paper ledger amounts, not a charity wire"


def ledger_file(root: Path | None = None) -> Path:
    return (root or STATE) / "purification.csv"


def read_ledger(root: Path | None = None) -> pd.DataFrame:
    path = ledger_file(root)
    if not path.exists():
        return pd.DataFrame(columns=list(COLUMNS))
    return pd.read_csv(path)


def upsert_entries(entries: list[dict], root: Path | None = None) -> pd.DataFrame:
    if not entries:
        return read_ledger(root)
    frame = read_ledger(root)
    incoming = pd.DataFrame(entries)
    for column in COLUMNS:
        if column not in incoming.columns:
            incoming[column] = None
    incoming = incoming[list(COLUMNS)]
    if frame.empty:
        frame = incoming
    else:
        frame = frame.loc[~frame["key"].astype(str).isin(set(incoming["key"].astype(str)))]
        frame = pd.concat([frame, incoming], ignore_index=True)
    path = ledger_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return frame


def apply_purification(
    account: PaperAccount,
    as_of,
    dividends: pd.DataFrame | None,
    impure_ratios: dict[str, float] | None,
    *,
    schedule: str = "ex_date",
) -> tuple[float, list[dict]]:
    """Return cash that left NAV today, and the ledger rows to store."""
    if schedule in {"", "off"}:
        return 0.0, []
    if schedule == "ex_date":
        entries: list[dict] = []
        paid = accrue_purification(account, as_of, dividends, impure_ratios, entries)
        return paid, entries
    entries = []
    for line in purification_lines(account, as_of, dividends, impure_ratios):
        key = line["key"]
        if key in account.purified_keys or key in account.staged_purify_keys:
            continue
        account.purification_payable += line["amount"]
        account.staged_purify_keys.append(key)
        entries.append({**line, "status": "accrued", "actor": ""})
    paid = 0.0
    day = pd.Timestamp(as_of).date()
    if cheque_due(day, schedule) and not account.halted:
        paid = post_entries(account, entries, actor="session", reject_duplicates=False)
    return paid, entries


def post_entries(
    account: PaperAccount,
    entries: list[dict],
    *,
    actor: str,
    reject_duplicates: bool = False,
) -> float:
    """Post accrued rows once. A second post of the same key is rejected when asked."""
    who = str(actor or "").strip()
    if not who:
        raise ValueError("actor is required")
    if account.halted:
        raise ValueError("halted; purification posts wait until the halt is cleared")
    if reject_duplicates:
        for entry in entries:
            key = str(entry.get("key"))
            if entry.get("status") == "posted" or key in account.purified_keys:
                raise ValueError(f"already posted {key}")
    paid = 0.0
    now = datetime.now(timezone.utc).isoformat()
    for entry in entries:
        key = str(entry.get("key"))
        status = entry.get("status")
        if status == "posted" or key in account.purified_keys:
            continue
        if status not in {None, "accrued"}:
            continue
        amount = float(entry.get("amount") or 0.0)
        if amount <= 0:
            continue
        account.cash -= amount
        account.purification_cumulative += amount
        account.purification_payable = max(0.0, float(account.purification_payable) - amount)
        if key in account.staged_purify_keys:
            account.staged_purify_keys = [item for item in account.staged_purify_keys if item != key]
        account.purified_keys.append(key)
        entry["status"] = "posted"
        entry["actor"] = who
        entry["posted_at"] = now
        paid += amount
    return paid


def post_ledger(
    account: PaperAccount,
    *,
    actor: str,
    root: Path | None = None,
    keys: list[str] | None = None,
    reject_duplicates: bool = True,
) -> float:
    frame = read_ledger(root)
    if frame.empty:
        if keys and reject_duplicates:
            raise ValueError("already posted " + ", ".join(keys))
        return 0.0
    wanted = set(keys or [])
    selected = []
    for row in frame.to_dict("records"):
        key = str(row.get("key"))
        if wanted and key not in wanted:
            continue
        if wanted and str(row.get("status")) == "posted":
            if reject_duplicates:
                raise ValueError(f"already posted {key}")
            continue
        if str(row.get("status")) != "accrued":
            continue
        selected.append(row)
    if wanted and not selected and reject_duplicates:
        posted = set(frame.loc[frame["status"].astype(str) == "posted", "key"].astype(str))
        overlap = wanted & posted
        if overlap:
            raise ValueError("already posted " + ", ".join(sorted(overlap)))
    paid = post_entries(account, selected, actor=actor, reject_duplicates=reject_duplicates)
    if selected:
        upsert_entries(selected, root)
    if paid > 0:
        append_event("purification_posted", actor=actor, root=root, amount=paid)
    return paid


def export_purification(root: Path | None = None, dest: Path | None = None) -> Path:
    frame = read_ledger(root)
    target = dest or ((root or STATE) / "purification_export.csv")
    target.parent.mkdir(parents=True, exist_ok=True)
    body = frame.to_csv(index=False)
    target.write_text(f"# {DISCLAIMER}\n{body}", encoding="utf-8")
    return target


def totals(root: Path | None = None) -> dict:
    frame = read_ledger(root)
    if frame.empty:
        return {"life": 0.0, "accrued": 0.0, "posted": 0.0}
    amounts = pd.to_numeric(frame["amount"], errors="coerce").fillna(0.0)
    posted = frame["status"].astype(str) == "posted"
    accrued = frame["status"].astype(str) == "accrued"
    return {
        "life": float(amounts.sum()),
        "posted": float(amounts.loc[posted].sum()),
        "accrued": float(amounts.loc[accrued].sum()),
    }
