"""Turn today's target book into paper fills and a NAV row."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from ops.account import PaperAccount
from ops.batches import new_batch, transition
from ops.broker import fill_orders
from ops.oms import build_orders, default_order_reason, rejected_halt, target_map
from ops.quotes import session_quotes
from ops.reconcile import reconcile
from ops.targets import IntendedBook


@dataclass
class TradeResult:
    fills: list[dict] = field(default_factory=list)
    orders: list[dict] = field(default_factory=list)
    purification_today: float = 0.0
    purification_entries: list = field(default_factory=list)
    fill_basis: str = "none"
    max_gap: float | None = None
    reconcile_reason: str = ""
    batch: dict | None = None
    closed_batch_id: str = ""


def run_paper_day(
    book: IntendedBook,
    account: PaperAccount,
    prices: pd.DataFrame,
    *,
    min_notional: float = 100.0,
    dividends: pd.DataFrame | None = None,
    impure_ratios: dict[str, float] | None = None,
    commit: bool = True,
    fail_symbols: set[str] | None = None,
    purify_schedule: str = "ex_date",
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
        settle_purification(book, account, dividends, impure_ratios, result, purify_schedule)
        return result

    as_of = book.as_of if isinstance(book.as_of, date) else pd.Timestamp(book.as_of).date()
    opens = session_quotes(prices, as_of, "open")
    closes = session_quotes(prices, as_of, "close")
    # A blank open still trades at the last real close.
    for symbol, price in closes.items():
        opens.setdefault(symbol, price)
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
        result.closed_batch_id = account.open_batch_id
        account.open_batch_id = ""
        if check.halt:
            account.halted = True
            account.halt_reason = check.reason
            settle_purification(book, account, dividends, impure_ratios, result, purify_schedule)
            return result

    orders = build_orders(
        book,
        account,
        closes,
        min_notional=min_notional,
        default_reason=default_order_reason(book, account),
        exit_reasons={symbol: "filing breach" for symbol in (fail_symbols or set())},
    )
    account.rebalance_reason = ""
    result.orders = orders
    halt = rejected_halt(orders)
    if halt:
        account.halted = True
        account.halt_reason = halt
        result.reconcile_reason = halt
        result.fill_basis = result.fill_basis or "rejected"
        settle_purification(book, account, dividends, impure_ratios, result, purify_schedule)
        return result
    skipped = sorted({str(order["symbol"]) for order in orders if order.get("status") == "rejected"})
    if skipped and not result.reconcile_reason:
        result.reconcile_reason = "skipped no price for " + ", ".join(skipped)

    actionable = [order for order in orders if order.get("status") != "rejected"]
    if actionable:
        result.batch = _commit_orders(
            book,
            account,
            actionable,
            closes,
            as_of=as_of,
            commit=commit,
            never_traded=never_traded,
            result=result,
        )
    elif result.fill_basis == "none":
        result.fill_basis = "no_orders"
        check = reconcile(account, closes, target_map(book))
        result.max_gap = check.max_gap
        result.reconcile_reason = check.reason
        if check.halt:
            account.halted = True
            account.halt_reason = check.reason

    settle_purification(book, account, dividends, impure_ratios, result, purify_schedule)
    return result


def settle_purification(book, account, dividends, impure_ratios, result: TradeResult, schedule: str = "ex_date") -> None:
    from ops.purify_ledger import apply_purification

    paid, entries = apply_purification(
        account,
        book.as_of,
        dividends,
        impure_ratios,
        schedule=schedule,
    )
    result.purification_today = paid
    result.purification_entries = entries


def _commit_orders(book, account, actionable, closes, *, as_of, commit, never_traded, result: TradeResult):
    batch = new_batch(as_of, actionable, target_map(book))
    if not commit:
        for order in actionable:
            order["status"] = "draft"
        result.fill_basis = "draft" if result.fill_basis == "none" else result.fill_basis
        return batch
    if not account.venue:
        account.venue = "local"
    batch = transition(batch, "approved", actor="session")
    batch = transition(batch, "executing", actor="session")
    if never_traded:
        filled = fill_orders(account, actionable, closes, as_of=as_of, price_field="close")
        result.fills.extend(filled)
        result.fill_basis = "close_bootstrap"
        check = reconcile(account, closes, target_map(book))
        result.max_gap = check.max_gap
        result.reconcile_reason = check.reason
        if check.halt:
            account.halted = True
            account.halt_reason = check.reason
            return transition(batch, "halted", actor="session")
        return transition(batch, "completed", actor="session")
    account.pending = actionable
    account.pending_targets = target_map(book)
    account.open_batch_id = batch["id"]
    if result.fill_basis == "none":
        result.fill_basis = "queued_next_open"
    return batch
