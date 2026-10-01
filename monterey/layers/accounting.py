"""Accounting layer: dividend credits and purification on the ex-date.

Holders at the prior close receive the dividend on the ex-date. The impure
slice (impure ratio × gross) is donated from that credited cash.
"""

from __future__ import annotations

from typing import Iterable

from monterey.layers.execution import Account
from monterey.spec import BookSpec


def settle_dividends(
    account: Account,
    holders: dict[str, float],
    dividends: Iterable[tuple[str, float]],
    impure: dict[str, float],
    spec: BookSpec,
    *,
    day: str,
) -> list[dict]:
    """
    Credit dividends on ``holders`` (shares at the prior close) and take
    purification. Returns cashflow rows (``dividend`` positive, ``purification`` negative).
    """
    a = spec.accounting
    credit = bool(a["dividends"])
    purify = str(a.get("purify") or "off") == "ex_date"
    purify_uncredited = bool(a.get("purify_uncredited"))
    rows: list[dict] = []
    for symbol, per_share in dividends:
        shares = float(holders.get(symbol, 0.0))
        if shares <= 0 or per_share <= 0:
            continue
        gross = shares * float(per_share)
        if credit:
            account.cash += gross
            rows.append({"date": day, "type": "dividend", "symbol": symbol, "amount": gross, "shares": shares, "per_share": float(per_share), "ratio": None})
        ratio = impure.get(symbol)
        if purify and ratio is not None and ratio > 0 and (credit or purify_uncredited):
            amount = gross * float(ratio)
            account.cash -= amount
            rows.append({"date": day, "type": "purification", "symbol": symbol, "amount": -amount, "shares": shares, "per_share": float(per_share), "ratio": float(ratio)})
    return rows
