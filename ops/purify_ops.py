"""Ex-date purification on the paper account. Cash leaves NAV. No charity wire."""

from __future__ import annotations

from datetime import date

import pandas as pd

from ops.account import PaperAccount


def accrue_purification(
    account: PaperAccount,
    as_of: date | str,
    dividends: pd.DataFrame | None,
    impure_ratios: dict[str, float] | None,
) -> float:
    """Donate impure dividend cash on the ex-date. Returns today's amount."""
    if dividends is None or dividends.empty or "symbol" not in dividends.columns:
        return 0.0
    day = pd.Timestamp(as_of).date()
    frame = dividends.copy()
    frame["_day"] = pd.to_datetime(frame["ex_date"]).dt.date
    frame = frame.loc[frame["_day"] == day]
    ratios = impure_ratios or {}
    paid = 0.0
    for _, row in frame.iterrows():
        symbol = str(row["symbol"])
        key = f"{symbol}|{day.isoformat()}"
        if key in account.purified_keys:
            continue
        shares = float(account.positions.get(symbol, 0.0))
        if shares <= 0:
            continue
        ratio = ratios.get(symbol)
        if ratio is None or pd.isna(ratio):
            continue
        dividend = float(pd.to_numeric(row.get("dividend"), errors="coerce") or 0.0)
        amount = shares * dividend * float(ratio)
        if amount <= 0:
            continue
        account.cash -= amount
        account.purification_cumulative += amount
        account.purified_keys.append(key)
        paid += amount
    return paid
