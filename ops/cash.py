"""Paper deposits, withdrawals, and the monthly contribution. No bank transfer."""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

from ops.account import PaperAccount, load_account, save_account
from ops.activity import append_activity
from ops.audit import append_event
from ops.ledger import ledger_path
from ops.paths import STATE

LARGE_MOVE = 0.10


def contribution_path(root: Path | None = None) -> Path:
    return (root or STATE) / "contribution.json"


def load_contribution(root: Path | None = None) -> dict:
    path = contribution_path(root)
    if not path.exists():
        return {"enabled": False, "amount": 0.0, "next_date": "", "applied_months": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.setdefault("applied_months", [])
    return payload


def save_contribution(plan: dict, root: Path | None = None) -> Path:
    path = contribution_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return path


def latest_nav(root: Path | None = None) -> float | None:
    path = ledger_path(root)
    if not path.exists():
        return None
    import pandas as pd

    frame = pd.read_csv(path)
    if frame.empty or "nav" not in frame.columns:
        return None
    value = pd.to_numeric(frame.iloc[-1]["nav"], errors="coerce")
    if pd.isna(value):
        return None
    return float(value)


def move_cash(
    account: PaperAccount,
    amount: float,
    side: str,
    *,
    actor: str,
    reason: str,
    root: Path | None = None,
    nav: float | None = None,
    confirm: bool = False,
    persist: bool = True,
) -> dict:
    """Change paper cash. A move larger than 10% of NAV needs confirm=True."""
    if account.halted:
        raise ValueError("halted; clear the halt before cash moves")
    if side not in {"deposit", "withdraw"}:
        raise ValueError("side must be deposit or withdraw")
    dollars = float(amount)
    if not math.isfinite(dollars) or dollars <= 0:
        raise ValueError("amount must be a positive number")
    who = str(actor or "").strip()
    why = str(reason or "").strip()
    if not who or not why:
        raise ValueError("actor and reason are required")
    basis = float(nav) if nav is not None else latest_nav(root)
    if basis is None:
        basis = float(account.cash)
    if basis > 0 and dollars > LARGE_MOVE * basis and not confirm:
        raise ValueError("amount is more than 10% of NAV; pass confirm")
    if side == "withdraw" and dollars > float(account.cash) + 1e-6:
        raise ValueError("insufficient cash")

    before = float(account.cash)
    if side == "deposit":
        account.cash = before + dollars
        signed = dollars
        event = "cash_deposit"
    else:
        account.cash = before - dollars
        signed = -dollars
        event = "cash_withdrawal"
    account.rebalance_reason = "deposit rebalance"
    record = {
        "side": side,
        "amount": dollars,
        "cash_before": before,
        "cash_after": float(account.cash),
    }
    append_event(
        event,
        actor=who,
        root=root,
        reason=why,
        amount=signed,
        cash_before=before,
        cash_after=float(account.cash),
    )
    append_activity(
        {
            "as_of": date.today().isoformat(),
            "type": side,
            "symbol": "",
            "amount": signed,
            "shares": None,
            "price": None,
            "detail": why,
            "actor": who,
            "ref": "",
        },
        root,
    )
    if persist:
        save_account(account, root)
    return record


def set_contribution(
    *,
    enabled: bool,
    amount: float,
    next_date: date | None,
    actor: str,
    root: Path | None = None,
) -> dict:
    who = str(actor or "").strip()
    if not who:
        raise ValueError("actor is required")
    plan = load_contribution(root)
    plan["enabled"] = bool(enabled)
    if enabled:
        dollars = float(amount)
        if not math.isfinite(dollars) or dollars <= 0:
            raise ValueError("amount must be a positive number")
        if next_date is None:
            raise ValueError("next_date is required")
        plan["amount"] = dollars
        plan["next_date"] = next_date.isoformat()
    save_contribution(plan, root)
    append_event(
        "contribution_set",
        actor=who,
        root=root,
        enabled=bool(enabled),
        amount=plan.get("amount"),
        next_date=plan.get("next_date"),
    )
    return plan


def take_due_contribution(
    account: PaperAccount,
    as_of: date,
    root: Path | None = None,
) -> dict | None:
    """Credit one due contribution in memory. The caller saves the account, then the plan."""
    if account.halted:
        return None
    plan = load_contribution(root)
    if not plan.get("enabled"):
        return None
    due = plan.get("next_date")
    if not due or as_of < date.fromisoformat(str(due)[:10]):
        return None
    month_key = as_of.strftime("%Y-%m")
    if month_key in set(account.contribution_months):
        return None
    amount = float(plan["amount"])
    before = float(account.cash)
    account.cash = before + amount
    account.rebalance_reason = "deposit rebalance"
    account.contribution_months.append(month_key)
    applied = [str(item) for item in plan.get("applied_months") or []]
    if month_key not in applied:
        applied.append(month_key)
    plan["applied_months"] = applied
    nxt = _add_month(date.fromisoformat(str(due)[:10]))
    while nxt <= as_of:
        nxt = _add_month(nxt)
    plan["next_date"] = nxt.isoformat()
    return {
        "plan": plan,
        "amount": amount,
        "cash_before": before,
        "cash_after": float(account.cash),
        "as_of": as_of.isoformat(),
    }


def record_contribution(taken: dict, root: Path | None = None, *, actor: str = "scheduler") -> None:
    save_contribution(taken["plan"], root)
    append_event(
        "cash_deposit",
        actor=actor,
        root=root,
        reason="monthly contribution",
        amount=taken["amount"],
        cash_before=taken["cash_before"],
        cash_after=taken["cash_after"],
    )
    append_activity(
        {
            "as_of": taken["as_of"],
            "type": "deposit",
            "symbol": "",
            "amount": taken["amount"],
            "shares": None,
            "price": None,
            "detail": "monthly contribution",
            "actor": actor,
            "ref": "",
        },
        root,
    )


def _add_month(day: date) -> date:
    import calendar

    month = day.month + 1
    year = day.year
    if month == 13:
        month = 1
        year += 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))
