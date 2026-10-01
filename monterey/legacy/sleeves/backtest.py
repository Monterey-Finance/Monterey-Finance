"""Walk daily P&L from a weight schedule (month-end or event-time)."""

from __future__ import annotations

import warnings
from datetime import date

import pandas as pd

from .prices import daily_returns, to_price_panel
from .triggers import last_rebalance_on_or_before, rebalance_dates


def holdings_to_weights(holdings: pd.DataFrame) -> pd.Series:
    if holdings is None or holdings.empty:
        return pd.Series(dtype=float)
    return holdings.set_index("symbol")["weight"].astype(float)


def run_weight_schedule(
    prices: pd.DataFrame,
    weights_by_date: dict[date, pd.Series],
    start: str | None = None,
    throttle_on: pd.Series | None = None,
    off_weights_by_date: dict[date, pd.Series] | None = None,
) -> pd.DataFrame:
    """Apply the latest weights as of each day. Missing return before first live day.

    ``throttle_on`` is an optional daily boolean series (True = stay invested).
    When False the book earns 0 (cash), unless ``off_weights_by_date`` is set
    (defensive sleeve while the regime is off).

    Deprecated: this engine applies the close-t signal to day-t returns.
    New work should use ``monterey.sim.simulate``.
    """
    warnings.warn(
        "run_weight_schedule is deprecated. Use monterey.sim.simulate so a signal never earns the day that made it.",
        DeprecationWarning,
        stacklevel=2,
    )
    panel = to_price_panel(prices)
    rets = daily_returns(panel)
    dates = sorted(weights_by_date)
    if start is not None:
        rets = rets.loc[rets.index >= pd.Timestamp(start)]

    rows: list[dict] = []
    active = pd.Series(dtype=float)
    last_key: date | None = None
    live = False

    throttle_map = None
    if throttle_on is not None and not throttle_on.empty:
        throttle_map = throttle_on.copy()
        throttle_map.index = pd.to_datetime(throttle_map.index)

    for dt in rets.index:
        key = last_rebalance_on_or_before(dates, dt.date())
        if key is not None and key != last_key:
            active = weights_by_date.get(key, pd.Series(dtype=float))
            last_key = key
            if active is not None and not active.empty:
                live = True

        if throttle_map is not None:
            if dt in throttle_map.index:
                risk_on = bool(throttle_map.loc[dt])
            else:
                prior = throttle_map.loc[:dt]
                risk_on = bool(prior.iloc[-1]) if not prior.empty else False
            if not risk_on:
                if off_weights_by_date:
                    off_key = last_rebalance_on_or_before(sorted(off_weights_by_date), dt.date())
                    off_w = off_weights_by_date.get(off_key, pd.Series(dtype=float)) if off_key is not None else pd.Series(dtype=float)
                    held = [s for s in off_w.index if s in rets.columns]
                    w = off_w.reindex(held).astype(float)
                    w = w[w > 0]
                    if w.empty:
                        rows.append({"date": dt.date(), "return": 0.0 if live else float("nan"), "n_holdings": 0})
                    else:
                        live = True
                        w = w / w.sum()
                        day_ret = (rets.loc[dt, w.index] * w).sum(skipna=True)
                        rows.append(
                            {
                                "date": dt.date(),
                                "return": 0.0 if pd.isna(day_ret) else float(day_ret),
                                "n_holdings": int(len(w)),
                            }
                        )
                    continue
                if not live:
                    rows.append({"date": dt.date(), "return": float("nan"), "n_holdings": 0})
                else:
                    rows.append({"date": dt.date(), "return": 0.0, "n_holdings": 0})
                continue

        if not live:
            rows.append({"date": dt.date(), "return": float("nan"), "n_holdings": 0})
            continue

        held = [s for s in active.index if s in rets.columns]
        w = active.reindex(held).astype(float)
        w = w[w > 0]
        if w.empty:
            rows.append({"date": dt.date(), "return": 0.0, "n_holdings": 0})
            continue
        w = w / w.sum()
        day_ret = (rets.loc[dt, w.index] * w).sum(skipna=True)
        rows.append(
            {
                "date": dt.date(),
                "return": 0.0 if pd.isna(day_ret) else float(day_ret),
                "n_holdings": int(len(w)),
            }
        )

    out = pd.DataFrame(rows)
    out["date"] = pd.to_datetime(out["date"])
    return out


def monthly_dates_from_panel(panel: pd.DataFrame) -> list[date]:
    return rebalance_dates(panel)
