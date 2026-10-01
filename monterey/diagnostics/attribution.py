"""Where the return went: selection, switch timing, costs, dividends, purification."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _compound(returns: pd.Series) -> float:
    returns = returns.dropna()
    return float(np.prod(1.0 + returns.values) - 1.0) if len(returns) else 0.0


def components(nav: pd.DataFrame) -> dict:
    """
    Split each day's return (as a share of the prior NAV) into dividends,
    purification, costs, and the price move, then compound each part.
    """
    frame = nav.copy()
    prior = frame["nav"].astype(float).shift()
    div = frame["dividends"].astype(float) / prior
    purify = frame["purification"].astype(float) / prior
    cost = frame["costs"].astype(float) / prior
    total = frame["nav"].astype(float).pct_change()
    price = total - div + purify + cost
    return {
        "total": _compound(total),
        "price": _compound(price),
        "dividends": _compound(div),
        "purification": -_compound(purify),
        "costs": -_compound(cost),
    }


def switch_cost(nav: pd.DataFrame, bench: pd.Series) -> dict:
    """
    What the regime switch cost under next-open execution.

    ``off_day_loss``: the book's return on the closes that turned the switch
    off (it is still invested that day). ``on_day_missed``: the benchmark's
    return on the closes that turned it back on (the book is still in cash).
    ``out_of_market``: the benchmark's return over every day the book was
    not fully invested.
    """
    frame = nav.copy()
    dates = pd.DatetimeIndex(pd.to_datetime(frame["date"]))
    exposure = pd.Series(frame["exposure"].astype(float).values, index=dates)
    returns = pd.Series(frame["nav"].astype(float).pct_change().values, index=dates)
    b = bench.reindex(dates).ffill().pct_change()
    previous = exposure.shift().fillna(exposure.iloc[0])
    cut = exposure < previous
    raised = exposure > previous
    held_prior = exposure.shift(1).fillna(0) >= 1.0
    invested_full = (exposure >= 1.0) & held_prior
    years = []
    for year in sorted(set(dates.year)):
        mask = dates.year == year
        years.append(
            {
                "year": int(year),
                "cuts": int(cut[mask].sum()),
                "off_day_loss": _compound(returns[cut & mask]),
                "on_day_missed": _compound(b[raised & mask]),
                "days_not_invested": int((~invested_full & mask).sum()),
            }
        )
    return {
        "cuts": int(cut.sum()),
        "raises": int(raised.sum()),
        "off_day_loss": _compound(returns[cut]),
        "on_day_missed": _compound(b[raised]),
        "out_of_market": _compound(b[~invested_full]),
        "days_not_invested": int((~invested_full).sum()),
        "by_year": years,
    }


def selection_vs_bench(nav: pd.DataFrame, bench_price: pd.Series) -> dict:
    """Book versus a benchmark's price return on days the book was fully invested all day."""
    frame = nav.copy()
    dates = pd.DatetimeIndex(pd.to_datetime(frame["date"]))
    exposure = pd.Series(frame["exposure"].astype(float).values, index=dates)
    prior = frame["nav"].astype(float).shift().values
    price_only = (frame["nav"].astype(float).values - prior - frame["dividends"].astype(float).values) / prior
    r = pd.Series(price_only, index=dates)
    b = bench_price.reindex(dates).ffill().pct_change()
    mask = (exposure >= 1.0) & (exposure.shift(1).fillna(0) >= 1.0) & b.notna()
    years = []
    for year in sorted(set(dates.year)):
        m = mask & (dates.year == year)
        years.append({"year": int(year), "book": _compound(r[m]), "bench": _compound(b[m])})
    return {"days": int(mask.sum()), "book": _compound(r[mask]), "bench": _compound(b[mask]), "by_year": years}


def always_invested(nav: pd.DataFrame, bench_price: pd.Series) -> dict:
    """Rough counterfactual: the book on invested days, the benchmark's price return on the others."""
    frame = nav.copy()
    dates = pd.DatetimeIndex(pd.to_datetime(frame["date"]))
    exposure = pd.Series(frame["exposure"].astype(float).values, index=dates)
    r = pd.Series(frame["nav"].astype(float).pct_change().fillna(0).values, index=dates)
    b = bench_price.reindex(dates).ffill().pct_change().fillna(0)
    invested = (exposure >= 1.0) & (exposure.shift(1).fillna(0) >= 1.0)
    path = (1.0 + r.where(invested, b)).cumprod()
    years = max((dates[-1] - dates[0]).days / 365.25, 1e-9)
    dd = float((path / path.cummax() - 1.0).min())
    cagr = float(path.iloc[-1] ** (1 / years) - 1)
    return {"total_return": float(path.iloc[-1] - 1), "cagr": cagr, "max_drawdown": dd, "calmar": cagr / abs(dd) if dd < 0 else None}
