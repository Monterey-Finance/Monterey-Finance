"""Risk figures from the paper NAV ledger. A short series stays blank."""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from ops.ledger import ledger_path

MIN_SESSIONS = 20
RF_ANNUAL = 0.02


def health_report(
    nav: pd.DataFrame | None = None,
    *,
    root: Path | None = None,
    benchmark: pd.DataFrame | None = None,
) -> dict:
    try:
        from ops.fund import load_live_ledger

        ledger = load_live_ledger()
        if ledger is not None and not ledger.nav.empty and nav is None:
            from monterey.diagnostics.performance import relative, stats

            values = ledger.nav_series()
            report = {
                "window": f"{values.index[0].date()} to {values.index[-1].date()}",
                "n_sessions": int(len(values)),
                "sessions_required": MIN_SESSIONS,
                **{k: stats(values).get(k) for k in ("max_drawdown", "sharpe", "sortino", "var_95", "cvar_95")},
                "beta_spus": None,
                "beta_spy": None,
                "tracking_error_spus": None,
                "alpha_spus": None,
                "confidence": 0.95,
            }
            diag = ledger.diagnostics()
            benches = diag.get("benchmarks") or {}
            if "SPUS" in benches:
                rel = benches["SPUS"].get("relative") or {}
                report["beta_spus"] = rel.get("beta")
                report["tracking_error_spus"] = rel.get("tracking_error")
                report["alpha_spus"] = rel.get("alpha")
            if "SPY" in benches:
                report["beta_spy"] = (benches["SPY"].get("relative") or {}).get("beta")
            return report
    except Exception:
        pass
    frame = nav if nav is not None else _read_nav(root)
    if frame is None or frame.empty or "nav" not in frame.columns:
        return _empty("no NAV rows")
    frame = frame.copy()
    frame["as_of"] = pd.to_datetime(frame["as_of"])
    frame = frame.sort_values("as_of")
    values = pd.to_numeric(frame["nav"], errors="coerce").dropna()
    n = int(len(values))
    start = frame["as_of"].iloc[0].date().isoformat()
    end = frame["as_of"].iloc[-1].date().isoformat()
    report = {
        "window": f"{start} to {end}",
        "n_sessions": n,
        "sessions_required": MIN_SESSIONS,
        "max_drawdown": _max_drawdown(values) if n >= 2 else None,
        "sharpe": None,
        "sortino": None,
        "beta_spus": None,
        "beta_spy": None,
        "tracking_error_spus": None,
        "alpha_spus": None,
        "var_95": None,
        "cvar_95": None,
        "confidence": 0.95,
    }
    if n < MIN_SESSIONS:
        return report
    returns = values.pct_change().dropna()
    report["sharpe"] = _sharpe(returns)
    report["sortino"] = _sortino(returns)
    report["var_95"] = _var(returns)
    report["cvar_95"] = _cvar(returns)
    if benchmark is not None and not benchmark.empty:
        aligned = _align(frame, benchmark)
        if aligned is not None and len(aligned) >= MIN_SESSIONS:
            report["beta_spus"] = _beta(aligned["fund"], aligned["spus"]) if "spus" in aligned else None
            report["beta_spy"] = _beta(aligned["fund"], aligned["spy"]) if "spy" in aligned else None
            if "spus" in aligned:
                report["tracking_error_spus"] = _tracking_error(aligned["fund"], aligned["spus"])
                report["alpha_spus"] = _alpha(aligned["fund"], aligned["spus"], report["beta_spus"])
    return report


def _read_nav(root: Path | None) -> pd.DataFrame:
    path = ledger_path(root)
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _empty(reason: str) -> dict:
    return {
        "window": None,
        "n_sessions": 0,
        "sessions_required": MIN_SESSIONS,
        "reason": reason,
        "max_drawdown": None,
        "sharpe": None,
        "sortino": None,
        "beta_spus": None,
        "beta_spy": None,
        "tracking_error_spus": None,
        "alpha_spus": None,
        "var_95": None,
        "cvar_95": None,
        "confidence": 0.95,
    }


def _max_drawdown(values: pd.Series) -> float:
    peak = values.cummax()
    return float((values / peak - 1.0).min())


def _sharpe(returns: pd.Series) -> float | None:
    excess = returns - RF_ANNUAL / 252.0
    sigma = float(excess.std(ddof=1))
    if sigma <= 0 or math.isnan(sigma):
        return None
    return float(excess.mean() / sigma * math.sqrt(252))


def _sortino(returns: pd.Series) -> float | None:
    excess = returns - RF_ANNUAL / 252.0
    downside = excess[excess < 0]
    if len(downside) < 2:
        return None
    sigma = float(downside.std(ddof=1))
    if sigma <= 0 or math.isnan(sigma):
        return None
    return float(excess.mean() / sigma * math.sqrt(252))


def _var(returns: pd.Series) -> float:
    cutoff = float(returns.quantile(0.05))
    return float(-cutoff)


def _cvar(returns: pd.Series) -> float:
    cutoff = float(returns.quantile(0.05))
    tail = returns[returns <= cutoff]
    if tail.empty:
        return float(-cutoff)
    return float(-tail.mean())


def _beta(fund: pd.Series, bench: pd.Series) -> float | None:
    var = float(bench.var(ddof=1))
    if var <= 0 or math.isnan(var):
        return None
    return float(fund.cov(bench) / var)


def _tracking_error(fund: pd.Series, bench: pd.Series) -> float | None:
    active = fund - bench
    sigma = float(active.std(ddof=1))
    if math.isnan(sigma):
        return None
    return float(sigma * math.sqrt(252))


def _alpha(fund: pd.Series, bench: pd.Series, beta: float | None) -> float | None:
    if beta is None:
        return None
    rf = RF_ANNUAL / 252.0
    daily = float((fund.mean() - rf) - beta * (bench.mean() - rf))
    return float(daily * 252)


def _align(nav: pd.DataFrame, benchmark: pd.DataFrame) -> pd.DataFrame | None:
    bench = benchmark.copy()
    bench["as_of"] = pd.to_datetime(bench["as_of"])
    bench = bench.sort_values("as_of")
    fund = nav[["as_of"]].copy()
    fund["fund"] = pd.to_numeric(nav["nav"], errors="coerce").pct_change()
    merged = fund.merge(bench, on="as_of", how="inner")
    for column in ("spus", "spy"):
        if column in merged.columns:
            merged[column] = pd.to_numeric(merged[column], errors="coerce").pct_change()
    merged = merged.dropna(subset=["fund"])
    return merged if not merged.empty else None
