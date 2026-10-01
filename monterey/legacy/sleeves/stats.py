"""Headline performance stats used in every white paper."""

from __future__ import annotations

import numpy as np
import pandas as pd


def calc_performance_stats(
    daily_returns: pd.Series,
    label: str,
    rf: float = 0.02,
) -> dict:
    r = daily_returns.dropna()
    empty = {
        "Strategy": label,
        "CAGR": np.nan,
        "Volatility": np.nan,
        "Sharpe": np.nan,
        "Sortino": np.nan,
        "Max Drawdown": np.nan,
        "Calmar": np.nan,
    }
    if r.empty:
        return empty

    equity = (1 + r).cumprod()
    years = len(r) / 252
    cagr = equity.iloc[-1] ** (1 / years) - 1 if years > 0 else np.nan
    vol = r.std() * np.sqrt(252)
    excess = r - rf / 252
    sharpe = excess.mean() / excess.std() * np.sqrt(252) if excess.std() > 0 else np.nan
    downside = r[r < 0]
    sortino = (
        (r.mean() - rf / 252) / downside.std() * np.sqrt(252) if len(downside) else np.nan
    )
    dd = equity / equity.cummax() - 1
    max_dd = dd.min()
    calmar = cagr / abs(max_dd) if max_dd < 0 else np.nan
    return {
        "Strategy": label,
        "CAGR": cagr,
        "Volatility": vol,
        "Sharpe": sharpe,
        "Sortino": sortino,
        "Max Drawdown": max_dd,
        "Calmar": calmar,
    }


def stats_table(series_map: dict[str, pd.Series], rf: float = 0.02) -> pd.DataFrame:
    rows = [calc_performance_stats(s, name, rf=rf) for name, s in series_map.items()]
    return pd.DataFrame(rows)
