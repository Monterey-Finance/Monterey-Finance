"""Orders are the gap between target weights and paper shares."""

from __future__ import annotations

from datetime import date

from ops.account import PaperAccount
from ops.calendar import is_month_end_session
from ops.targets import IntendedBook

COST_BPS = 10.0

MIN_NOTIONAL = 100.0


def target_map(book: IntendedBook) -> dict[str, float]:
    if book.holdings is None or book.holdings.empty or not book.sma_on:
        return {}
    out: dict[str, float] = {}
    for _, row in book.holdings.iterrows():
        weight = float(row["target_weight"])
        if weight > 0:
            out[str(row["symbol"])] = weight
    return out


def equity(account: PaperAccount, closes: dict[str, float]) -> float:
    invested = 0.0
    for symbol, shares in account.positions.items():
        price = closes.get(symbol)
        if price is None or price <= 0:
            continue
        invested += float(shares) * float(price)
    return float(account.cash) + invested


def default_order_reason(book: IntendedBook, account: PaperAccount) -> str:
    if account.rebalance_reason:
        return account.rebalance_reason
    if not book.sma_on:
        return "SMA cash"
    if isinstance(book.as_of, date) and is_month_end_session(book.as_of):
        return "monthly rebuild"
    return "rebalance"


def rejected_halt(orders: list[dict], band: float = 0.03) -> str | None:
    rejected = [order for order in orders if order.get("status") == "rejected"]
    if not rejected:
        return None
    skipped_weight = sum(float(order.get("target_weight") or 0.0) for order in rejected)
    if skipped_weight <= band:
        return None
    skipped = sorted({str(order["symbol"]) for order in rejected})
    return "no price for " + ", ".join(skipped)


def build_orders(
    book: IntendedBook,
    account: PaperAccount,
    closes: dict[str, float],
    *,
    min_notional: float = MIN_NOTIONAL,
    default_reason: str = "rebalance",
    exit_reasons: dict[str, str] | None = None,
    cost_bps: float = COST_BPS,
) -> list[dict]:
    """Whole-share buys and sells. A name that leaves the book is always sold."""
    nav = equity(account, closes)
    targets = target_map(book)
    symbols = set(targets) | set(account.positions)
    orders: list[dict] = []
    as_of = book.as_of.isoformat() if isinstance(book.as_of, date) else str(book.as_of)
    for symbol in sorted(symbols):
        price = closes.get(symbol)
        held = float(account.positions.get(symbol, 0.0))
        weight = float(targets.get(symbol, 0.0))
        if price is None or price <= 0:
            if weight > 0 or held > 0:
                orders.append(
                    {
                        "symbol": symbol,
                        "side": "buy" if weight > 0 and held <= 0 else "sell",
                        "shares": 0,
                        "target_weight": weight,
                        "price_ref": None,
                        "notional": None,
                        "created_as_of": as_of,
                        "status": "rejected",
                        "reason": "no close",
                    }
                )
            continue
        target_shares = (weight * nav) / price if weight > 0 else 0.0
        delta = int(round(target_shares - held))
        if delta == 0:
            continue
        notional = abs(delta) * price
        exiting = weight <= 0 and held > 0
        if not exiting and notional < min_notional:
            continue
        if exiting and exit_reasons and symbol in exit_reasons:
            reason = exit_reasons[symbol]
        elif exiting and default_reason == "SMA cash":
            reason = "SMA cash"
        elif exiting:
            reason = "exit"
        else:
            reason = default_reason or "rebalance"
        current_weight = (held * price) / nav if nav > 0 else 0.0
        orders.append(
            {
                "symbol": symbol,
                "side": "buy" if delta > 0 else "sell",
                "shares": abs(delta),
                "target_weight": weight,
                "current_weight": current_weight,
                "drift": weight - current_weight,
                "price_ref": price,
                "notional": notional,
                "est_cost": notional * float(cost_bps) / 10_000.0,
                "created_as_of": as_of,
                "status": "pending",
                "reason": reason,
            }
        )
    return orders
