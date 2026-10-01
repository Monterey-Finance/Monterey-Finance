"""Price helpers: panels, 12–1 momentum, rolling beta, SMA regime."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd


def to_price_panel(prices: pd.DataFrame) -> pd.DataFrame:
    if prices is None or prices.empty:
        return pd.DataFrame()
    value_col = "adj_close" if "adj_close" in prices.columns else "close"
    panel = (
        prices.pivot(index="date", columns="symbol", values=value_col)
        .sort_index()
        .ffill()
    )
    panel.index = pd.to_datetime(panel.index)
    return panel


def series_as_of(panel: pd.DataFrame, symbol: str, as_of) -> pd.Series:
    if panel.empty or symbol not in panel.columns:
        return pd.Series(dtype=float)
    s = panel[symbol].dropna()
    return s.loc[: pd.Timestamp(as_of)]


def trailing_return(
    price_panel: pd.DataFrame,
    symbol: str,
    as_of,
    lookback: int,
    skip: int,
) -> float:
    s = series_as_of(price_panel, symbol, as_of)
    if len(s) < lookback + skip + 1:
        return np.nan
    end_px = float(s.iloc[-1 - skip])
    start_px = float(s.iloc[-1 - skip - lookback])
    if start_px <= 0:
        return np.nan
    return end_px / start_px - 1.0


def spy_sma_risk_on(spy_series: pd.Series, as_of, sma_window: int = 200) -> bool:
    """True when SPY's last close is above its trailing SMA (paper 04 / 09 throttle)."""
    s = spy_series.dropna().loc[: pd.Timestamp(as_of)]
    if len(s) < sma_window:
        return False
    px = float(s.iloc[-1])
    sma = float(s.iloc[-sma_window:].mean())
    return px > sma


def rolling_beta(
    price_panel: pd.DataFrame,
    symbol: str,
    market: str,
    as_of,
    window: int = 252,
) -> float:
    stock = series_as_of(price_panel, symbol, as_of)
    mkt = series_as_of(price_panel, market, as_of)
    joined = pd.concat([stock, mkt], axis=1, keys=["y", "x"]).dropna()
    if len(joined) < max(60, window // 4):
        return np.nan
    joined = joined.iloc[-window:]
    y = joined["y"].pct_change().dropna()
    x = joined["x"].pct_change().reindex(y.index)
    aligned = pd.concat([y, x], axis=1).dropna()
    if len(aligned) < 40:
        return np.nan
    yy, xx = aligned.iloc[:, 0], aligned.iloc[:, 1]
    var_x = float(xx.var())
    if var_x <= 0:
        return np.nan
    beta = float(yy.cov(xx) / var_x)
    return beta if np.isfinite(beta) else np.nan


def trailing_volatility(price_panel: pd.DataFrame, as_of, lookback: int = 252) -> pd.Series:
    as_of_ts = pd.Timestamp(as_of)
    window = price_panel.loc[:as_of_ts].iloc[-lookback:]
    rets = window.pct_change()
    return rets.std() * np.sqrt(252)


def trading_days_between(price_index: pd.DatetimeIndex, start, end) -> int:
    lo = pd.Timestamp(start)
    hi = pd.Timestamp(end)
    if hi <= lo:
        return 0
    window = price_index[(price_index > lo) & (price_index <= hi)]
    return int(len(window))


def daily_returns(price_panel: pd.DataFrame) -> pd.DataFrame:
    return price_panel.pct_change(fill_method=None)
