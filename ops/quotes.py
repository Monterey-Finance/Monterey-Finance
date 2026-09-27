"""Close and open quotes from a long price frame."""

from __future__ import annotations

from datetime import date

import pandas as pd


def session_quotes(
    prices: pd.DataFrame,
    as_of: date | str,
    field: str = "close",
    lookback_days: int = 10,
) -> dict[str, float]:
    """Last positive price on or before as_of, within lookback_days.

    A blank close on the session date (a Yahoo timeout that still wrote a row)
    falls back to the previous real print. It does not invent a price beyond
    that window.
    """
    if prices is None or prices.empty or "symbol" not in prices.columns:
        return {}
    day = pd.Timestamp(as_of).normalize()
    start = day - pd.Timedelta(days=int(lookback_days))
    frame = prices.copy()
    frame["_day"] = pd.to_datetime(frame["date"])
    frame = frame.loc[(frame["_day"] >= start) & (frame["_day"] <= day)]
    if frame.empty:
        return {}
    col = field if field in frame.columns else "close"
    if col not in frame.columns:
        return {}
    frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.loc[frame[col] > 0]
    if frame.empty:
        return {}
    latest = frame.sort_values("_day").groupby("symbol", as_index=False).tail(1)
    return {str(row["symbol"]): float(row[col]) for _, row in latest.iterrows()}


def prices_on(prices: pd.DataFrame, as_of: date | str, field: str = "close") -> dict[str, float]:
    """One price per symbol on as_of. Missing field falls back to close."""
    if prices is None or prices.empty or "symbol" not in prices.columns:
        return {}
    day = pd.Timestamp(as_of).date()
    frame = prices.copy()
    frame["_day"] = pd.to_datetime(frame["date"]).dt.date
    frame = frame.loc[frame["_day"] == day]
    if frame.empty:
        return {}
    col = field if field in frame.columns else "close"
    if col not in frame.columns:
        return {}
    out: dict[str, float] = {}
    for _, row in frame.iterrows():
        value = pd.to_numeric(row.get(col), errors="coerce")
        if pd.isna(value) or float(value) <= 0:
            continue
        out[str(row["symbol"])] = float(value)
    return out
