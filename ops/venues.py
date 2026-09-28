"""Alpaca paper venue. Local fills stay in ops.broker."""

from __future__ import annotations

from datetime import date

import pandas as pd

from ops.account import PaperAccount
from ops.alpaca import AlpacaClient, snapshot, submit_orders
from ops.batches import new_batch, transition
from ops.oms import build_orders, default_order_reason, rejected_halt, target_map
from ops.pipeline import TradeResult, settle_purification
from ops.quotes import session_quotes
from ops.reconcile import reconcile
from ops.targets import IntendedBook


def bound_venue(account: PaperAccount) -> str:
    if account.venue:
        return account.venue
    if account.positions or account.fills:
        return "local"
    return ""


def run_alpaca_day(
    book: IntendedBook,
    account: PaperAccount,
    prices: pd.DataFrame,
    client: AlpacaClient,
    *,
    commit: bool = True,
    min_notional: float = 100.0,
    dividends: pd.DataFrame | None = None,
    impure_ratios: dict[str, float] | None = None,
    fail_symbols: set[str] | None = None,
    purify_schedule: str = "ex_date",
) -> TradeResult:
    """Sync the paper broker, then submit next-open orders or leave a draft."""
    result = TradeResult()
    if bound_venue(account) == "local":
        raise ValueError("this paper account is bound to the local venue")
    account.venue = "alpaca"
    if account.halted:
        result.fill_basis = "halted"
        result.reconcile_reason = account.halt_reason or "halted"
        settle_purification(book, account, dividends, impure_ratios, result, purify_schedule)
        return result

    as_of = book.as_of if isinstance(book.as_of, date) else pd.Timestamp(book.as_of).date()
    closes = session_quotes(prices, as_of, "close")
    prior_targets = dict(account.pending_targets)
    open_orders = [
        row
        for row in client.list_open_orders()
        if str(row.get("client_order_id") or "").startswith("mf-")
    ]
    cash, positions = snapshot(client)
    result.fills.extend(_apply_snapshot(account, cash, positions, closes, as_of))

    if open_orders:
        account.pending = [_pending_from_open(row) for row in open_orders]
        result.fill_basis = "submitted_opg"
        result.reconcile_reason = "orders already open at the paper broker"
        result.orders = list(account.pending)
        settle_purification(book, account, dividends, impure_ratios, result, purify_schedule)
        return result

    if prior_targets:
        check = reconcile(account, closes, prior_targets)
        result.max_gap = check.max_gap
        result.reconcile_reason = check.reason
        result.closed_batch_id = account.open_batch_id
        account.open_batch_id = ""
        account.pending = []
        account.pending_targets = {}
        if check.halt:
            account.halted = True
            account.halt_reason = check.reason
            result.fill_basis = "halted"
            settle_purification(book, account, dividends, impure_ratios, result, purify_schedule)
            return result
        result.fill_basis = "broker_sync"

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

    actionable = [order for order in orders if order.get("status") != "rejected"]
    if not actionable:
        if result.fill_basis == "none":
            result.fill_basis = "no_orders"
        settle_purification(book, account, dividends, impure_ratios, result, purify_schedule)
        return result

    batch = new_batch(as_of, actionable, target_map(book))
    if not commit:
        for order in actionable:
            order["status"] = "draft"
        result.batch = batch
        result.fill_basis = "draft"
        settle_purification(book, account, dividends, impure_ratios, result, purify_schedule)
        return result

    batch = transition(batch, "approved", actor="session")
    batch = transition(batch, "executing", actor="session")
    submit_orders(client, actionable, as_of=as_of, time_in_force="opg")
    account.pending = actionable
    account.pending_targets = target_map(book)
    account.open_batch_id = batch["id"]
    result.batch = batch
    if result.fill_basis == "none":
        result.fill_basis = "submitted_opg"
    settle_purification(book, account, dividends, impure_ratios, result, purify_schedule)
    return result


def _apply_snapshot(
    account: PaperAccount,
    cash: float,
    positions: dict[str, float],
    closes: dict[str, float],
    as_of: date,
) -> list[dict]:
    old = {symbol: float(shares) for symbol, shares in account.positions.items()}
    fills = []
    symbols = set(old) | set(positions)
    for symbol in sorted(symbols):
        delta = float(positions.get(symbol, 0.0)) - float(old.get(symbol, 0.0))
        if abs(delta) < 1e-9:
            continue
        price = closes.get(symbol)
        fills.append(
            {
                "symbol": symbol,
                "side": "buy" if delta > 0 else "sell",
                "shares": abs(delta),
                "price": price,
                "as_of": as_of.isoformat(),
                "price_field": "broker",
                "status": "filled",
                "detail": "broker sync",
            }
        )
    account.cash = float(cash)
    account.positions = {symbol: float(shares) for symbol, shares in positions.items() if shares > 0}
    account.fills.extend(fills)
    return fills


def _pending_from_open(row: dict) -> dict:
    return {
        "symbol": row.get("symbol"),
        "side": row.get("side"),
        "shares": int(float(row.get("qty") or 0)),
        "status": "pending",
        "reason": "rebalance",
        "client_order_id": row.get("client_order_id"),
    }
