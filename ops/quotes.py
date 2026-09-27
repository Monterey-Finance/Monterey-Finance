"""Close and open quotes from a long price frame."""

from __future__ import annotations

from datetime import date

import pandas as pd


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
