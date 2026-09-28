"""Approve or cancel a draft order batch. Cancelling a draft does not trade."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from ops.account import load_account, save_account
from ops.alpaca import submit_orders
from ops.audit import append_event
from ops.batches import latest_with_status, save_batch, transition
from ops.data import resolve_as_of


def approve_draft(
    as_of: date | str,
    *,
    actor: str,
    root: Path | None = None,
    client=None,
) -> dict:
    who = str(actor or "").strip()
    if not who:
        raise ValueError("actor is required")
    day = resolve_as_of(as_of)
    account = load_account(root)
    if account.halted:
        raise ValueError("halted; orders wait until the halt is cleared")
    batch = latest_with_status(root, day, "draft")
    if batch is None:
        raise ValueError("no draft batch for this session")
    orders = []
    for order in batch.get("orders") or []:
        if order.get("status") == "rejected":
            continue
        row = dict(order)
        row["status"] = "pending"
        orders.append(row)
    batch = transition(batch, "approved", actor=who)
    append_event(
        "order_batch_approved",
        actor=who,
        root=root,
        as_of=day.isoformat(),
        batch_id=batch["id"],
        n_orders=len(orders),
    )
    venue = account.venue or "local"
    if venue == "alpaca":
        if client is None:
            from ops.alpaca import from_env

            client = from_env()
        submit_orders(client, orders, as_of=day, time_in_force="opg")
    account.pending = orders
    account.pending_targets = {str(k): float(v) for k, v in (batch.get("targets") or {}).items()}
    account.open_batch_id = batch["id"]
    if not account.venue:
        account.venue = "local"
    batch = transition(batch, "executing", actor=who)
    save_batch(batch, root)
    save_account(account, root)
    return batch


def cancel_draft(
    as_of: date | str,
    *,
    actor: str,
    root: Path | None = None,
) -> dict:
    who = str(actor or "").strip()
    if not who:
        raise ValueError("actor is required")
    day = resolve_as_of(as_of)
    batch = latest_with_status(root, day, "draft")
    if batch is None:
        raise ValueError("no draft batch for this session")
    batch = transition(batch, "cancelled", actor=who)
    append_event(
        "order_batch_cancelled",
        actor=who,
        root=root,
        as_of=day.isoformat(),
        batch_id=batch["id"],
    )
    save_batch(batch, root)
    return batch
