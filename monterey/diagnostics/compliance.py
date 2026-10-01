"""Shariah process checks on a ledger: sector exposure, breach handling, purification."""

from __future__ import annotations

import pandas as pd

from monterey.data.research_data import sector_allowed


def excluded_exposure(positions: pd.DataFrame) -> dict:
    """Sessions and names where the book held a name whose sector is excluded or unknown."""
    held = positions[positions["shares"].astype(float) > 0].copy()
    if held.empty:
        return {"sessions": 0, "names": [], "latest_weight": 0.0}
    held["bad"] = ~held["sector"].map(sector_allowed).astype(bool)
    bad = held[held["bad"]]
    latest = held["date"].max()
    return {
        "sessions": int(bad["date"].nunique()),
        "names": sorted(bad["symbol"].astype(str).unique()),
        "latest_weight": float(bad.loc[bad["date"] == latest, "weight"].astype(float).sum()),
    }


def breach_handling(events: pd.DataFrame, positions: pd.DataFrame, lag: int = 5) -> dict:
    """Breach events, and how many names were still held ``lag`` sessions later."""
    breaches = events[events["type"] == "breach"].copy() if not events.empty else events
    if breaches is None or breaches.empty:
        return {"events": 0, "names": 0, "still_held": 0}
    breaches["date"] = pd.to_datetime(breaches["date"])
    sessions = sorted(pd.to_datetime(positions["date"]).unique())
    held = positions[positions["shares"].astype(float) > 0]
    by_day = {d: set(g["symbol"]) for d, g in held.groupby(pd.to_datetime(held["date"]))}
    index = {d: i for i, d in enumerate(sessions)}
    still = 0
    checked = 0
    for row in breaches.itertuples(index=False):
        i = index.get(pd.Timestamp(row.date))
        if i is None or i + lag >= len(sessions):
            continue
        checked += 1
        if row.symbol in by_day.get(sessions[i + lag], set()):
            still += 1
    return {"events": int(len(breaches)), "names": int(breaches["symbol"].nunique()), "checked": checked, "still_held": still}


def purification(cashflows: pd.DataFrame) -> dict:
    if cashflows.empty:
        return {"dividends": 0.0, "purification": 0.0, "posts": 0}
    div = cashflows[cashflows["type"] == "dividend"]["amount"].astype(float).sum()
    pur = -cashflows[cashflows["type"] == "purification"]["amount"].astype(float).sum()
    return {
        "dividends": float(div),
        "purification": float(pur),
        "posts": int((cashflows["type"] == "purification").sum()),
        "share_of_dividends": float(pur / div) if div else None,
    }


def watch_list(positions: pd.DataFrame, band: float = 0.02, lines: dict[str, float] | None = None) -> list[dict]:
    """Held names on the last session within ``band`` of a ratio line."""
    if positions.empty:
        return []
    lines = lines or {"debt_ratio": 0.30, "cash_ratio": 0.30, "receivables_ratio": 0.70}
    last = positions[pd.to_datetime(positions["date"]) == pd.to_datetime(positions["date"]).max()]
    rows = []
    for row in last.itertuples(index=False):
        if float(row.shares or 0) <= 0:
            continue
        for ratio, line in lines.items():
            value = getattr(row, ratio)
            if value is not None and pd.notna(value) and 0 <= line - float(value) <= band:
                rows.append({"symbol": row.symbol, "ratio": ratio, "value": float(value), "line": line, "gap": line - float(value)})
    return rows
