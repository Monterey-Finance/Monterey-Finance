"""Fill paper orders at a known open or close. No live broker."""

from __future__ import annotations

from datetime import date

from ops.account import PaperAccount


def fill_orders(
    account: PaperAccount,
    orders: list[dict],
    quotes: dict[str, float],
    *,
    as_of: date,
    price_field: str,
) -> list[dict]:
    """Sells first, then buys. A buy stops at the cash on hand."""
    day = as_of.isoformat() if isinstance(as_of, date) else str(as_of)[:10]
    sells = [o for o in orders if o.get("side") == "sell" and o.get("status") != "rejected"]
    buys = [o for o in orders if o.get("side") == "buy" and o.get("status") != "rejected"]
    rejected = [dict(o) for o in orders if o.get("status") == "rejected"]
    fills: list[dict] = []
    for order in sells + buys:
        fills.append(_fill_one(account, order, quotes, day, price_field))
    fills.extend(rejected)
    account.fills.extend(fills)
    return fills


def _fill_one(
    account: PaperAccount,
    order: dict,
    quotes: dict[str, float],
    day: str,
    price_field: str,
) -> dict:
    symbol = str(order["symbol"])
    price = quotes.get(symbol)
    base = {
        "symbol": symbol,
        "side": order.get("side"),
        "as_of": day,
        "price_field": price_field,
        "target_weight": order.get("target_weight"),
        "reason": order.get("reason"),
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
        account.cash += shares * price
        return {**base, "shares": shares, "price": price, "status": "filled", "detail": "sell"}
    affordable = int(account.cash // price)
    shares = min(requested, affordable)
    if shares <= 0:
        return {**base, "shares": 0, "price": price, "status": "rejected", "detail": "no cash"}
    account.cash -= shares * price
    account.positions[symbol] = float(account.positions.get(symbol, 0)) + shares
    detail = "buy" if shares == requested else "partial buy"
    status = "filled" if shares == requested else "partial"
    return {**base, "shares": shares, "price": price, "status": status, "detail": detail}
