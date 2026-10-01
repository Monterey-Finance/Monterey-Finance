"""Concentration, sector mix, turnover, and trading churn from ledger tables."""

from __future__ import annotations

import pandas as pd


def concentration(positions: pd.DataFrame, name_cap: float | None) -> pd.DataFrame:
    """Yearly mean of top-5 / top-10 invested weight, capped names, and effective names (1/HHI)."""
    frame = positions[positions["invested_weight"].astype(float) > 0].copy()
    if frame.empty:
        return pd.DataFrame(columns=["names", "top5", "top10", "capped", "effective_names"])
    frame["date"] = pd.to_datetime(frame["date"])
    rows = []
    for day, chunk in frame.groupby("date"):
        w = chunk["invested_weight"].astype(float).sort_values(ascending=False)
        w = w / w.sum()
        rows.append(
            {
                "date": day,
                "names": int(len(w)),
                "top5": float(w.head(5).sum()),
                "top10": float(w.head(10).sum()),
                "capped": int((w >= (name_cap or 1.0) - 1e-4).sum()) if name_cap else 0,
                "effective_names": float(1.0 / (w**2).sum()),
            }
        )
    daily = pd.DataFrame(rows).set_index("date")
    return daily.groupby(daily.index.year).mean()


def sector_mix(positions: pd.DataFrame, day=None) -> pd.Series:
    frame = positions.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    if day is None:
        live = frame[frame["invested_weight"].astype(float) > 0]
        if live.empty:
            return pd.Series(dtype=float)
        day = live["date"].max()
    chunk = frame[(frame["date"] == pd.Timestamp(day)) & (frame["invested_weight"].astype(float) > 0)]
    w = chunk.set_index("symbol")["invested_weight"].astype(float)
    if w.empty:
        return pd.Series(dtype=float)
    return (w / w.sum()).groupby(chunk.set_index("symbol")["sector"].fillna("unknown")).sum().sort_values(ascending=False)


def trading(nav: pd.DataFrame, fills: pd.DataFrame) -> dict:
    """Turnover per year, share of notional on switch days, and how small the fills are."""
    frame = nav.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    years = max((frame["date"].iloc[-1] - frame["date"].iloc[0]).days / 365.25, 1e-9)
    avg = float(frame["nav"].astype(float).mean())
    notional = float(frame["traded_notional"].astype(float).sum())
    exposure = frame.set_index("date")["exposure"].astype(float)
    changed = exposure.diff().fillna(0) != 0
    switch_days = set(exposure.index[changed.shift(1, fill_value=False)])
    good = fills[fills["status"].isin(["filled", "partial"])].copy() if not fills.empty else fills
    out = {
        "annual_turnover": notional / 2 / avg / years if avg else None,
        "traded_notional": notional,
        "costs": float(frame["costs"].astype(float).sum()),
        "by_year_notional": {int(y): float(v) for y, v in frame.groupby(frame["date"].dt.year)["traded_notional"].sum().items()},
        "switch_share": None,
        "fills": int(len(good)),
        "median_fills_per_day": None,
        "small_fill_share": None,
    }
    if not good.empty:
        good["date"] = pd.to_datetime(good["date"])
        good["notional"] = good["notional"].astype(float)
        out["switch_share"] = float(good[good["date"].isin(switch_days)]["notional"].sum() / good["notional"].sum())
        out["median_fills_per_day"] = float(good.groupby("date").size().median())
        out["small_fill_share"] = float((good["notional"] < 2000).mean())
    return out
