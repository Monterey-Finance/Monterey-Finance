"""Return, risk, and benchmark-relative figures from a NAV path."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

RF_ANNUAL = 0.02
TRADING_DAYS = 252


def nav_of(source) -> pd.Series:
    """A ledger, a NAV frame, or a series → NAV series indexed by date."""
    if isinstance(source, pd.Series):
        out = source.dropna().astype(float)
        out.index = pd.to_datetime(out.index)
        return out
    if hasattr(source, "nav_series"):
        return source.nav_series()
    frame = source
    return pd.Series(frame["nav"].astype(float).values, index=pd.to_datetime(frame["date"]))


def max_drawdown(values: pd.Series) -> tuple[float, pd.Timestamp | None, pd.Timestamp | None]:
    if values.empty:
        return 0.0, None, None
    dd = values / values.cummax() - 1.0
    trough = dd.idxmin()
    peak = values.loc[:trough].idxmax()
    return float(dd.min()), peak, trough


def stats(values: pd.Series) -> dict:
    values = values.dropna()
    if len(values) < 2:
        return {}
    r = values.pct_change().dropna()
    years = max((values.index[-1] - values.index[0]).days / 365.25, 1e-9)
    total = float(values.iloc[-1] / values.iloc[0] - 1.0)
    cagr = float((values.iloc[-1] / values.iloc[0]) ** (1 / years) - 1.0)
    dd, peak, trough = max_drawdown(values)
    excess = r - RF_ANNUAL / TRADING_DAYS
    vol = float(r.std(ddof=1) * math.sqrt(TRADING_DAYS))
    downside = excess[excess < 0].std(ddof=1)
    cutoff = float(r.quantile(0.05))
    return {
        "start": values.index[0].date().isoformat(),
        "end": values.index[-1].date().isoformat(),
        "sessions": int(len(values)),
        "total_return": total,
        "cagr": cagr,
        "volatility": vol,
        "max_drawdown": dd,
        "drawdown_peak": None if peak is None else peak.date().isoformat(),
        "drawdown_trough": None if trough is None else trough.date().isoformat(),
        "calmar": cagr / abs(dd) if dd < 0 else None,
        "sharpe": float(excess.mean() / excess.std(ddof=1) * math.sqrt(TRADING_DAYS)) if excess.std(ddof=1) > 0 else None,
        "sortino": float(excess.mean() / downside * math.sqrt(TRADING_DAYS)) if downside and downside > 0 else None,
        "var_95": -cutoff,
        "cvar_95": float(-r[r <= cutoff].mean()),
    }


def yearly(values: pd.Series) -> pd.DataFrame:
    """Calendar-year return, intra-year drawdown, and year-end NAV."""
    values = values.dropna()
    rows = []
    previous = float(values.iloc[0])
    for year, chunk in values.groupby(values.index.year):
        end = float(chunk.iloc[-1])
        dd = float((chunk / chunk.cummax() - 1.0).min())
        rows.append({"year": int(year), "return": end / previous - 1.0, "intra_year_drawdown": dd, "year_end": end})
        previous = end
    return pd.DataFrame(rows).set_index("year")


def relative(fund: pd.Series, bench: pd.Series) -> dict:
    """Beta, tracking error, alpha, correlation, and capture versus one benchmark."""
    joined = pd.concat([fund.pct_change(), bench.reindex(fund.index).ffill().pct_change()], axis=1, keys=["f", "b"]).dropna()
    if len(joined) < 20:
        return {}
    f, b = joined["f"], joined["b"]
    var = float(b.var(ddof=1))
    beta = float(f.cov(b) / var) if var > 0 else None
    rf = RF_ANNUAL / TRADING_DAYS
    alpha = None if beta is None else float(((f.mean() - rf) - beta * (b.mean() - rf)) * TRADING_DAYS)
    up = b > 0
    return {
        "beta": beta,
        "tracking_error": float((f - b).std(ddof=1) * math.sqrt(TRADING_DAYS)),
        "alpha": alpha,
        "correlation": float(f.corr(b)),
        "up_capture": float(f[up].mean() / b[up].mean()) if up.any() else None,
        "down_capture": float(f[~up].mean() / b[~up].mean()) if (~up).any() else None,
    }


def scorecard(source, label: str | None = None) -> dict:
    """One comparable row for a ledger (or a plain NAV series)."""
    values = nav_of(source)
    row = {"book": label or getattr(getattr(source, "spec", None), "id", None) or getattr(source, "name", None) or "series"}
    row.update({k: v for k, v in stats(values).items() if k in {"total_return", "cagr", "volatility", "max_drawdown", "calmar", "sharpe", "sortino"}})
    nav = getattr(source, "nav", None)
    if isinstance(nav, pd.DataFrame) and not nav.empty:
        years = max((values.index[-1] - values.index[0]).days / 365.25, 1e-9)
        avg = float(nav["nav"].astype(float).mean())
        row["turnover"] = float(nav["traded_notional"].astype(float).sum()) / 2 / avg / years
        row["costs_pct"] = float(nav["costs"].astype(float).sum()) / avg
        row["dividends_pct"] = float(nav["dividends"].astype(float).sum()) / avg
        row["avg_exposure"] = float(nav["exposure"].astype(float).mean())
        row["switches"] = int((nav["exposure"].astype(float).diff().fillna(0) != 0).sum())
        row["hash"] = source.spec.hash()
    return row


def _float(value) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out) else None
