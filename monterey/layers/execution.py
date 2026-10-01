"""Execution layer: target weights − holdings → whole-share orders, and how they fill.

Works on any account with ``cash`` (float) and ``positions`` (symbol → shares),
so the simulator and the ops paper account share one implementation.
"""

from __future__ import annotations

from typing import Iterable, Protocol

from monterey.spec import BookSpec


class Account(Protocol):
    cash: float
    positions: dict


def equity(account: Account, closes: dict[str, float]) -> float:
    invested = 0.0
    for symbol, shares in account.positions.items():
        price = closes.get(symbol)
        if price is None or price <= 0:
            continue
        invested += float(shares) * float(price)
    return float(account.cash) + invested


def plan_orders(
    account: Account,
    targets: dict[str, float],
    closes: dict[str, float],
    spec: BookSpec,
    *,
    as_of: str,
    reasons: dict[str, str] | None = None,
    default_reason: str = "rebalance",
    exits_only: bool = False,
    cost_bps: float | None = None,
) -> list[dict]:
    """
    Orders that move holdings to ``targets`` at ``closes``. A name that leaves
    the book is always sold. ``exits_only`` keeps everything else as it is.
    """
    e = spec.execution
    min_trade = float(e["min_trade"])
    band = float(e.get("drift_band") or 0.0)
    bps = float(spec.accounting["cost_bps"] if cost_bps is None else cost_bps)
    reasons = reasons or {}
    nav = equity(account, closes)
    orders: list[dict] = []
    for symbol in sorted(set(targets) | set(account.positions)):
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
        exiting = weight <= 0 and held > 0
        if exits_only and not exiting:
            continue
        target_shares = (weight * nav) / price if weight > 0 else 0.0
        delta = int(round(target_shares - held))
        if delta == 0:
            continue
        notional = abs(delta) * price
        current_weight = (held * price) / nav if nav > 0 else 0.0
        if not exiting:
            if notional < min_trade:
                continue
            if band > 0 and held > 0 and abs(weight - current_weight) < band:
                continue
        reason = reasons.get(symbol) or ("exit" if exiting and default_reason == "rebalance" else default_reason)
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
                "est_cost": notional * bps / 10_000.0,
                "created_as_of": as_of,
                "status": "pending",
                "reason": reason,
            }
        )
    return orders


def fill_orders(
    account: Account,
    orders: Iterable[dict],
    quotes: dict[str, float],
    *,
    day: str,
    price_field: str,
    cost_bps: float = 0.0,
) -> list[dict]:
    """
    Sells first, then buys. A buy stops at the cash on hand (cost included).
    Each fill is charged ``cost_bps`` of its notional; the cost leaves cash.
    """
    orders = list(orders)
    sells = [o for o in orders if o.get("side") == "sell" and o.get("status") != "rejected"]
    buys = [o for o in orders if o.get("side") == "buy" and o.get("status") != "rejected"]
    rejected = [dict(o) for o in orders if o.get("status") == "rejected"]
    rate = float(cost_bps) / 10_000.0
    fills: list[dict] = []
    for order in sells + buys:
        fills.append(_fill_one(account, order, quotes, day, price_field, rate))
    fills.extend(rejected)
    return fills


def _fill_one(account: Account, order: dict, quotes: dict, day: str, price_field: str, rate: float) -> dict:
    symbol = str(order["symbol"])
    price = quotes.get(symbol)
    base = {
        "symbol": symbol,
        "side": order.get("side"),
        "as_of": day,
        "price_field": price_field,
        "target_weight": order.get("target_weight"),
        "reason": order.get("reason"),
        "cost": 0.0,
    }
    if price is None or price <= 0:
        return {**base, "shares": 0, "price": None, "status": "rejected", "detail": "no price"}
    requested = int(order.get("shares") or 0)
    if requested <= 0:
        return {**base, "shares": 0, "price": price, "status": "rejected", "detail": "zero shares"}
    if order.get("side") == "sell":
        held = int(account.positions.get(symbol, 0))
        shares = min(requested, held)
        if shares <= 0:
            return {**base, "shares": 0, "price": price, "status": "rejected", "detail": "no shares"}
        left = held - shares
        if left <= 0:
            account.positions.pop(symbol, None)
        else:
            account.positions[symbol] = left
        notional = shares * price
        cost = notional * rate
        account.cash += notional - cost
        return {**base, "shares": shares, "price": price, "cost": cost, "status": "filled", "detail": "sell"}
    affordable = int(account.cash // (price * (1.0 + rate)))
    shares = min(requested, affordable)
    if shares <= 0:
        return {**base, "shares": 0, "price": price, "status": "rejected", "detail": "no cash"}
    notional = shares * price
    cost = notional * rate
    account.cash -= notional + cost
    account.positions[symbol] = float(account.positions.get(symbol, 0)) + shares
    status = "filled" if shares == requested else "partial"
    return {**base, "shares": shares, "price": price, "cost": cost, "status": status, "detail": "buy" if status == "filled" else "partial buy"}
