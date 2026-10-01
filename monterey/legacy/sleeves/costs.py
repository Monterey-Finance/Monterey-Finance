"""Turnover, trading costs, and ADV capacity (paper 12).

One-way turnover is half the L1 weight change. Cost is paid on the
full L1 (buys plus sells). Cash days are an empty weight vector, so a
regime switch to cash trades 100% of NAV.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .triggers import last_rebalance_on_or_before


def _as_date(value) -> date:
    return pd.Timestamp(value).date()


def _risk_on(throttle_on: pd.Series | None, as_of) -> bool:
    if throttle_on is None or throttle_on.empty:
        return True
    s = throttle_on.copy()
    s.index = pd.to_datetime(s.index)
    ts = pd.Timestamp(as_of)
    if ts in s.index:
        return bool(s.loc[ts])
    prior = s.loc[:ts]
    if prior.empty:
        return False
    return bool(prior.iloc[-1])


def active_weights(
    weights_by_date: dict[date, pd.Series],
    as_of,
    throttle_on: pd.Series | None = None,
) -> pd.Series:
    if not _risk_on(throttle_on, as_of):
        return pd.Series(dtype=float)
    keys = sorted(weights_by_date)
    key = last_rebalance_on_or_before(keys, as_of)
    if key is None:
        return pd.Series(dtype=float)
    w = weights_by_date.get(key, pd.Series(dtype=float))
    if w is None or w.empty:
        return pd.Series(dtype=float)
    w = w.astype(float)
    w = w[w > 0]
    return w


def l1_trade(prev: pd.Series, curr: pd.Series) -> float:
    """Buys plus sells as a fraction of NAV (cash omitted from both series)."""
    a = prev.astype(float) if prev is not None and not prev.empty else pd.Series(dtype=float)
    b = curr.astype(float) if curr is not None and not curr.empty else pd.Series(dtype=float)
    a = a[a > 0]
    b = b[b > 0]
    a2, b2 = a.align(b, fill_value=0.0)
    return float((a2 - b2).abs().sum())


def one_way(prev: pd.Series, curr: pd.Series) -> float:
    return 0.5 * l1_trade(prev, curr)


def trade_calendar(
    weights_by_date: dict[date, pd.Series],
    price_index: pd.DatetimeIndex,
    throttle_on: pd.Series | None = None,
    start: str | None = None,
) -> pd.DataFrame:
    """One row per day the holdings change. ``traded_nav`` is buys+sells."""
    idx = pd.to_datetime(price_index).sort_values()
    if start is not None:
        idx = idx[idx >= pd.Timestamp(start)]
    rows = []
    prev = pd.Series(dtype=float)
    live = False
    for dt in idx:
        curr = active_weights(weights_by_date, dt.date(), throttle_on)
        if curr is not None and not curr.empty:
            live = True
        if not live:
            prev = curr
            continue
        traded = l1_trade(prev, curr)
        if traded > 1e-12:
            rows.append(
                {
                    "date": dt.date(),
                    "traded_nav": traded,
                    "one_way": 0.5 * traded,
                    "n_names": int(len(curr)),
                    "to_cash": bool(curr.empty and len(prev) > 0),
                    "from_cash": bool(len(curr) > 0 and prev.empty),
                }
            )
        prev = curr
    if not rows:
        return pd.DataFrame(
            columns=["date", "traded_nav", "one_way", "n_names", "to_cash", "from_cash"]
        )
    return pd.DataFrame(rows)


def annualized_one_way(trades: pd.DataFrame, start, end) -> float:
    if trades is None or trades.empty:
        return np.nan
    days = (pd.Timestamp(end) - pd.Timestamp(start)).days
    years = max(days / 365.25, 1e-9)
    return float(trades["one_way"].sum() / years)


def apply_flat_costs(
    daily_returns: pd.Series,
    trades: pd.DataFrame,
    cost_bps: float,
) -> pd.Series:
    """Subtract ``traded_nav * bps / 1e4`` on each trade date."""
    r = daily_returns.dropna().astype(float).sort_index()
    r.index = pd.to_datetime(r.index)
    if trades is None or trades.empty or cost_bps <= 0:
        return r
    drag = (float(cost_bps) / 1e4) * trades.set_index(pd.to_datetime(trades["date"]))["traded_nav"]
    drag = drag.groupby(level=0).sum()
    out = r.copy()
    aligned = drag.reindex(out.index).fillna(0.0)
    out = out - aligned
    return out


def dollar_volume_panel(prices: pd.DataFrame) -> pd.DataFrame:
    """Daily dollar volume = shares × close (not adjusted close)."""
    if prices is None or prices.empty:
        return pd.DataFrame()
    work = prices.copy()
    work["date"] = pd.to_datetime(work["date"])
    px = pd.to_numeric(work.get("close", work.get("adj_close")), errors="coerce")
    vol = pd.to_numeric(work.get("volume"), errors="coerce")
    work["dollar_volume"] = px * vol
    return (
        work.pivot(index="date", columns="symbol", values="dollar_volume")
        .sort_index()
    )


def trailing_adv(
    dollar_volume: pd.DataFrame,
    as_of,
    window: int = 20,
) -> pd.Series:
    """Median dollar volume over the last ``window`` sessions (inclusive)."""
    if dollar_volume is None or dollar_volume.empty:
        return pd.Series(dtype=float)
    hist = dollar_volume.loc[: pd.Timestamp(as_of)]
    if hist.empty:
        return pd.Series(dtype=float)
    windowed = hist.iloc[-window:]
    med = windowed.median(numeric_only=True)
    return med.dropna()


def name_trades(
    weights_by_date: dict[date, pd.Series],
    price_index: pd.DatetimeIndex,
    throttle_on: pd.Series | None = None,
    start: str | None = None,
) -> pd.DataFrame:
    """Per-name weight changes on trade dates (for ADV participation)."""
    idx = pd.to_datetime(price_index).sort_values()
    if start is not None:
        idx = idx[idx >= pd.Timestamp(start)]
    rows = []
    prev = pd.Series(dtype=float)
    live = False
    for dt in idx:
        curr = active_weights(weights_by_date, dt.date(), throttle_on)
        if curr is not None and not curr.empty:
            live = True
        if not live:
            prev = curr
            continue
        a, b = prev.align(curr, fill_value=0.0)
        delta = b.astype(float) - a.astype(float)
        delta = delta[delta.abs() > 1e-12]
        for symbol, dw in delta.items():
            rows.append({"date": dt.date(), "symbol": symbol, "delta_w": float(dw)})
        prev = curr
    if not rows:
        return pd.DataFrame(columns=["date", "symbol", "delta_w"])
    return pd.DataFrame(rows)


def attach_adv(
    trades: pd.DataFrame,
    dollar_volume: pd.DataFrame,
    window: int = 20,
) -> pd.DataFrame:
    if trades is None or trades.empty:
        return trades
    out = trades.copy()
    advs = []
    cache: dict[date, pd.Series] = {}
    for as_of in out["date"].unique():
        cache[as_of] = trailing_adv(dollar_volume, as_of, window=window)
    for _, row in out.iterrows():
        adv = cache[row["date"]]
        val = np.nan
        if adv is not None and not adv.empty and row["symbol"] in adv.index:
            val = float(adv[row["symbol"]])
        advs.append(val)
    out["adv"] = advs
    return out


def participation(delta_w: float, aum: float, adv: float) -> float:
    if not np.isfinite(adv) or adv <= 0 or not np.isfinite(delta_w):
        return np.nan
    return abs(float(delta_w)) * float(aum) / float(adv)


def capacity_table(
    name_df: pd.DataFrame,
    aum_list: list[float],
    max_participation: float = 0.10,
) -> pd.DataFrame:
    """At each AUM: max ADV share, count of breaches, implied book capacity."""
    work = name_df.dropna(subset=["adv"]).copy()
    work = work[work["adv"] > 0]
    rows = []
    # Binding name-days: AUM * |dw| / adv <= cap → AUM <= cap * adv / |dw|
    bind = work[work["delta_w"].abs() > 1e-12].copy()
    bind["aum_cap"] = max_participation * bind["adv"] / bind["delta_w"].abs()
    book_cap = float(bind["aum_cap"].min()) if not bind.empty else np.nan
    for aum in aum_list:
        part = work["delta_w"].abs() * aum / work["adv"]
        rows.append(
            {
                "aum": aum,
                "max_participation": float(part.max()) if len(part) else np.nan,
                "median_participation": float(part.median()) if len(part) else np.nan,
                "n_over_10pct_adv": int((part > max_participation).sum()),
                "frac_over_10pct_adv": float((part > max_participation).mean()) if len(part) else np.nan,
                "book_capacity": book_cap,
                "ok": bool(len(part) == 0 or part.max() <= max_participation),
            }
        )
    return pd.DataFrame(rows)


def sqrt_impact_bps(participation_rate: float, k: float = 25.0) -> float:
    """Simple square-root impact in basis points. ``k=25`` is conservative large-cap."""
    if not np.isfinite(participation_rate) or participation_rate <= 0:
        return 0.0
    return float(k) * float(np.sqrt(participation_rate))


def apply_impact_costs(
    daily_returns: pd.Series,
    name_df: pd.DataFrame,
    aum: float,
    base_bps: float = 5.0,
    k: float = 25.0,
) -> pd.Series:
    """NAV-weighted impact: each name pays (base + k√part) × |Δw|."""
    r = daily_returns.dropna().astype(float).sort_index()
    r.index = pd.to_datetime(r.index)
    if name_df is None or name_df.empty:
        return r
    work = attach_needed_part(name_df, aum)
    day_drag = work.groupby("date")["nav_cost"].sum()
    day_drag.index = pd.to_datetime(day_drag.index)
    aligned = day_drag.reindex(r.index).fillna(0.0)
    return r - aligned


def attach_needed_part(name_df: pd.DataFrame, aum: float, base_bps: float = 5.0, k: float = 25.0) -> pd.DataFrame:
    work = name_df.copy()
    work["part"] = [
        participation(dw, aum, adv) for dw, adv in zip(work["delta_w"], work.get("adv", pd.Series(np.nan, index=work.index)))
    ]
    work["cost_bps"] = base_bps + work["part"].map(lambda p: sqrt_impact_bps(p, k=k) if pd.notna(p) else np.nan)
    work["nav_cost"] = work["delta_w"].abs() * work["cost_bps"] / 1e4
    work.loc[work["nav_cost"].isna(), "nav_cost"] = work["delta_w"].abs() * base_bps / 1e4
    return work
