"""Ex-date purification on the paper account. Cash leaves NAV. No charity wire."""

from __future__ import annotations

from datetime import date

import pandas as pd

from ops.account import PaperAccount


def purification_lines(
    account: PaperAccount,
    as_of: date | str,
    dividends: pd.DataFrame | None,
    impure_ratios: dict[str, float] | None,
) -> list[dict]:
    """Impure dividend slices for this ex-date. Does not change the account."""
    if dividends is None or dividends.empty or "symbol" not in dividends.columns:
        return []
    day = pd.Timestamp(as_of).date()
    frame = dividends.copy()
    frame["_day"] = pd.to_datetime(frame["ex_date"]).dt.date
    frame = frame.loc[frame["_day"] == day]
    ratios = impure_ratios or {}
    lines = []
    for _, row in frame.iterrows():
        symbol = str(row["symbol"])
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
        lines.append(
            {
                "key": f"{symbol}|{day.isoformat()}",
                "symbol": symbol,
                "ex_date": day.isoformat(),
                "shares": shares,
                "gross_dividend": dividend,
                "impure_ratio": float(ratio),
                "amount": amount,
            }
        )
    return lines


def accrue_purification(
    account: PaperAccount,
    as_of: date | str,
    dividends: pd.DataFrame | None,
    impure_ratios: dict[str, float] | None,
    entries: list | None = None,
) -> float:
    """Donate impure dividend cash on the ex-date. Returns today's amount."""
    paid = 0.0
    for line in purification_lines(account, as_of, dividends, impure_ratios):
        key = line["key"]
        if key in account.purified_keys:
            continue
        account.cash -= line["amount"]
        account.purification_cumulative += line["amount"]
        account.purified_keys.append(key)
        paid += line["amount"]
        if entries is not None:
            entries.append({**line, "status": "posted", "actor": "session"})
    return paid
