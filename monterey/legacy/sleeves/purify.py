"""Dividend purification as a cash policy (paper 11).

Gross backtests keep the full dividend because they use adjusted prices.
AAOIFI still asks the fund to donate the impure slice (interest income /
revenue × dividend). This module:

1. Attaches each dividend to the weight we actually held on the ex-date.
2. Turns that into a dollar liability on a $1 NAV.
3. Pays the liability on a chosen calendar (ex-date, quarter-end, year-end).
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .triggers import last_rebalance_on_or_before
from .backtest import holdings_to_weights

SCHEDULES = ("off", "ex_date", "quarter_end", "year_end")


def weights_from_log(log: pd.DataFrame) -> dict[date, pd.Series]:
    """Monthly (or event) weight snapshot from a book log."""
    if log is None or log.empty:
        return {}
    work = log.dropna(subset=["symbol"]).copy()
    work["as_of"] = pd.to_datetime(work["as_of"]).dt.date
    out: dict[date, pd.Series] = {}
    for as_of, g in work.groupby("as_of"):
        out[as_of] = holdings_to_weights(g)
    return out


def _as_date(value) -> date:
    return pd.Timestamp(value).date()


def _num(value) -> float:
    v = pd.to_numeric(value, errors="coerce")
    if v is None or pd.isna(v) or not np.isfinite(float(v)):
        return np.nan
    return float(v)


def session_on_or_after(price_index: pd.DatetimeIndex, as_of) -> date | None:
    if price_index is None or len(price_index) == 0:
        return None
    idx = pd.to_datetime(price_index).sort_values()
    hit = idx[idx >= pd.Timestamp(as_of)]
    if hit.empty:
        return None
    return hit[0].date()


def pay_date_for(event: date, schedule: str, price_index: pd.DatetimeIndex) -> date | None:
    """When the cheque leaves the fund."""
    schedule = (schedule or "ex_date").lower()
    if schedule in {"off", "none", ""}:
        return None
    session = session_on_or_after(price_index, event)
    if session is None:
        return None
    if schedule == "ex_date":
        return session
    ts = pd.Timestamp(session)
    if schedule == "quarter_end":
        target = ts.to_period("Q").end_time.normalize()
    elif schedule == "year_end":
        target = ts.to_period("Y").end_time.normalize()
    else:
        raise ValueError(f"Unknown purify schedule {schedule!r}. Choose from {SCHEDULES}.")
    return session_on_or_after(price_index, target)


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


def weight_on(
    weights_by_date: dict[date, pd.Series],
    symbol: str,
    as_of,
    throttle_on: pd.Series | None = None,
) -> float:
    if not _risk_on(throttle_on, as_of):
        return 0.0
    keys = sorted(weights_by_date)
    key = last_rebalance_on_or_before(keys, as_of)
    if key is None:
        return 0.0
    w = weights_by_date.get(key, pd.Series(dtype=float))
    if w is None or w.empty or symbol not in w.index:
        return 0.0
    val = _num(w.loc[symbol])
    return 0.0 if not np.isfinite(val) else max(float(val), 0.0)


def fill_impure_ratio(
    purified: pd.DataFrame,
    metrics: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Use the latest known filing ratio when the dividend row is missing one."""
    out = purified.copy()
    if out.empty:
        return out
    out["ex_date"] = pd.to_datetime(out["ex_date"])
    out["impure_ratio"] = pd.to_numeric(out.get("impure_ratio"), errors="coerce")
    if metrics is None or metrics.empty or "impure_ratio" not in metrics.columns:
        return out
    hist = metrics[["symbol", "as_of", "impure_ratio"]].copy()
    hist["as_of"] = pd.to_datetime(hist["as_of"])
    hist["impure_ratio"] = pd.to_numeric(hist["impure_ratio"], errors="coerce")
    hist = hist.dropna(subset=["symbol", "as_of"]).sort_values(["symbol", "as_of"])
    filled = []
    for _, row in out.iterrows():
        ratio = row["impure_ratio"]
        if pd.notna(ratio) and np.isfinite(ratio):
            filled.append(ratio)
            continue
        prior = hist[
            (hist["symbol"] == row["symbol"]) & (hist["as_of"] <= row["ex_date"])
        ]
        if prior.empty or prior["impure_ratio"].dropna().empty:
            filled.append(np.nan)
        else:
            filled.append(float(prior["impure_ratio"].dropna().iloc[-1]))
    out["impure_ratio"] = filled
    div = pd.to_numeric(out.get("dividend"), errors="coerce")
    out["purification_amount"] = div * out["impure_ratio"]
    return out


def held_dividends(
    purified: pd.DataFrame,
    weights_by_date: dict[date, pd.Series],
    price_panel: pd.DataFrame,
    throttle_on: pd.Series | None = None,
    metrics: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Dividends paid while the book owned the name, with NAV fraction to donate."""
    cols = [
        "symbol",
        "ex_date",
        "weight",
        "price",
        "dividend",
        "impure_ratio",
        "purification_amount",
        "nav_frac",
        "covered",
    ]
    if purified is None or purified.empty:
        return pd.DataFrame(columns=cols)
    work = fill_impure_ratio(purified, metrics)
    rows = []
    for _, div in work.iterrows():
        symbol = str(div["symbol"])
        ex = _as_date(div["ex_date"])
        w = weight_on(weights_by_date, symbol, ex, throttle_on=throttle_on)
        if w <= 0:
            continue
        px = np.nan
        if price_panel is not None and not price_panel.empty and symbol in price_panel.columns:
            s = price_panel[symbol].dropna().loc[: pd.Timestamp(ex)]
            if not s.empty:
                px = float(s.iloc[-1])
        amount = _num(div.get("purification_amount"))
        ratio = _num(div.get("impure_ratio"))
        dividend = _num(div.get("dividend"))
        if (not np.isfinite(amount)) and np.isfinite(ratio) and np.isfinite(dividend):
            amount = ratio * dividend
        covered = bool(np.isfinite(amount) and np.isfinite(px) and px > 0)
        nav_frac = (w * amount / px) if covered else np.nan
        rows.append(
            {
                "symbol": symbol,
                "ex_date": ex,
                "weight": w,
                "price": px,
                "dividend": dividend,
                "impure_ratio": ratio,
                "purification_amount": amount,
                "nav_frac": nav_frac,
                "covered": covered,
            }
        )
    if not rows:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(rows).sort_values(["ex_date", "symbol"]).reset_index(drop=True)


def schedule_outflows(
    events: pd.DataFrame,
    schedule: str,
    price_index: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Map each held dividend onto a pay date. Uncovered rows stay in the table with nav_frac NaN."""
    if events is None or events.empty:
        return pd.DataFrame(columns=list(events.columns) + ["pay_date"] if events is not None else [])
    out = events.copy()
    out["pay_date"] = [
        pay_date_for(ex, schedule, price_index) for ex in pd.to_datetime(out["ex_date"]).dt.date
    ]
    if price_index is not None and len(price_index):
        last = pd.to_datetime(price_index).max().date()
        out["pay_date"] = out["pay_date"].apply(lambda d: last if d is None else d)
    return out


def apply_purification(
    daily_returns: pd.Series,
    events: pd.DataFrame,
    schedule: str = "ex_date",
    price_index: pd.DatetimeIndex | None = None,
) -> pd.Series:
    """Walk a $1 NAV. Subtract the impure *dollar* on the pay date.

    Delayed schedules let the impure cash ride the book until the cheque date.
    Accrue-and-segregate (pay on ex-date) is the Sharia-default investor path.
    """
    r = daily_returns.dropna().astype(float).sort_index()
    r.index = pd.to_datetime(r.index)
    if schedule in {"off", "none", ""} or events is None or events.empty:
        return r
    idx = price_index if price_index is not None else r.index
    planned = schedule_outflows(events, schedule, idx)
    planned = planned[planned["covered"].fillna(False) & planned["nav_frac"].notna()].copy()
    if planned.empty:
        return r

    pay_map: dict[date, float] = {}
    nav = 1.0
    live = False
    out_rets = []
    out_idx = []
    events_by_ex = {
        _as_date(ex): g for ex, g in planned.groupby(pd.to_datetime(planned["ex_date"]).dt.date)
    }
    for dt, ret in r.items():
        day = pd.Timestamp(dt).date()
        if pd.notna(ret):
            live = True
            nav = nav * (1.0 + float(ret))
        day_events = events_by_ex.get(day)
        if day_events is not None:
            for _, ev in day_events.iterrows():
                dollars = float(nav * float(ev["nav_frac"]))
                pay = ev["pay_date"]
                if pay is None or (isinstance(pay, float) and pd.isna(pay)):
                    continue
                pay_d = pay if isinstance(pay, date) else pd.Timestamp(pay).date()
                pay_map[pay_d] = pay_map.get(pay_d, 0.0) + dollars
        due = pay_map.pop(day, 0.0)
        if due and live:
            nav = nav - due
            if nav <= 0:
                nav = 1e-12
        if live:
            out_idx.append(pd.Timestamp(dt))
            out_rets.append(nav)
    leftover = sum(pay_map.values())
    if leftover and out_rets:
        out_rets[-1] = max(out_rets[-1] - leftover, 1e-12)
    if not out_rets:
        return r
    wealth = pd.Series(out_rets, index=pd.DatetimeIndex(out_idx))
    net = wealth.pct_change()
    net.iloc[0] = wealth.iloc[0] / 1.0 - 1.0
    return net


def coverage_stats(events: pd.DataFrame) -> dict:
    if events is None or events.empty:
        return {
            "events": 0,
            "covered": 0,
            "coverage": np.nan,
            "mean_impure_ratio": np.nan,
            "sum_nav_frac": np.nan,
        }
    covered = events["covered"].fillna(False)
    return {
        "events": int(len(events)),
        "covered": int(covered.sum()),
        "coverage": float(covered.mean()),
        "mean_impure_ratio": float(pd.to_numeric(events.loc[covered, "impure_ratio"], errors="coerce").mean()),
        "sum_nav_frac": float(pd.to_numeric(events.loc[covered, "nav_frac"], errors="coerce").sum()),
    }
