"""Turn today's target book into paper fills and a NAV row."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from ops.account import PaperAccount
from ops.broker import fill_orders
from ops.oms import build_orders, target_map
from ops.purify_ops import accrue_purification
from ops.quotes import prices_on
from ops.reconcile import reconcile
from ops.targets import IntendedBook


@dataclass
class TradeResult:
    fills: list[dict] = field(default_factory=list)
    orders: list[dict] = field(default_factory=list)
    purification_today: float = 0.0
    fill_basis: str = "none"
    max_gap: float | None = None
    reconcile_reason: str = ""


def run_paper_day(
    book: IntendedBook,
    account: PaperAccount,
    prices: pd.DataFrame,
    *,
    min_notional: float = 100.0,
    dividends: pd.DataFrame | None = None,
    impure_ratios: dict[str, float] | None = None,
) -> TradeResult:
    """
    Fill orders that were waiting for this session's open.
    On the first ever session, fill the new book at the close so NAV exists today.
    Later sessions leave new orders pending for the next open.
    """
    result = TradeResult()
    if account.halted:
        result.fill_basis = "halted"
        result.reconcile_reason = account.halt_reason or "halted"
        _purify(book, account, dividends, impure_ratios, result)
        return result

    as_of = book.as_of if isinstance(book.as_of, date) else pd.Timestamp(book.as_of).date()
    opens = prices_on(prices, as_of, "open")
    closes = prices_on(prices, as_of, "close")
    never_traded = not account.fills and not account.positions and not account.pending

    if account.pending:
        prior = dict(account.pending_targets)
        opened = fill_orders(account, account.pending, opens, as_of=as_of, price_field="open")
        result.fills.extend(opened)
        account.pending = []
        account.pending_targets = {}
        result.fill_basis = "next_open"
        check = reconcile(account, closes, prior)
        result.max_gap = check.max_gap
        result.reconcile_reason = check.reason
        if check.halt:
            account.halted = True
            account.halt_reason = check.reason
            _purify(book, account, dividends, impure_ratios, result)
            return result

    orders = build_orders(book, account, closes, min_notional=min_notional)
    result.orders = orders
    actionable = [o for o in orders if o.get("status") != "rejected"]
    rejected = [o for o in orders if o.get("status") == "rejected"]
    if rejected:
        account.halted = True
        account.halt_reason = "missing price for " + ", ".join(sorted({o["symbol"] for o in rejected}))
        result.reconcile_reason = account.halt_reason
        result.fill_basis = result.fill_basis or "rejected"
        _purify(book, account, dividends, impure_ratios, result)
        return result

    if never_traded and actionable:
        filled = fill_orders(account, actionable, closes, as_of=as_of, price_field="close")
        result.fills.extend(filled)
        result.fill_basis = "close_bootstrap"
        check = reconcile(account, closes, target_map(book))
        result.max_gap = check.max_gap
        result.reconcile_reason = check.reason
        if check.halt:
            account.halted = True
            account.halt_reason = check.reason
    elif actionable:
        account.pending = actionable
        account.pending_targets = target_map(book)
        if result.fill_basis == "none":
            result.fill_basis = "queued_next_open"
    elif result.fill_basis == "none":
        result.fill_basis = "no_orders"
        check = reconcile(account, closes, target_map(book))
        result.max_gap = check.max_gap
        result.reconcile_reason = check.reason
        if check.halt:
            account.halted = True
            account.halt_reason = check.reason

    _purify(book, account, dividends, impure_ratios, result)
    return result


def _purify(book, account, dividends, impure_ratios, result: TradeResult) -> None:
    result.purification_today = accrue_purification(
        account,
        book.as_of,
        dividends,
        impure_ratios,
    )
