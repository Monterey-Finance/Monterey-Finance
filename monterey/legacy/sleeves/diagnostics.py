"""Diagnostics for papers 13–15: overlap, CVaR weights, AAOIFI boundary trims."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .weighting import apply_name_cap


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return np.nan
    union = a | b
    if not union:
        return np.nan
    return len(a & b) / len(union)


def overlap_weight(wa: pd.Series, wb: pd.Series) -> float:
    """Sum of min(weight_a, weight_b). 1.0 means identical books."""
    if wa is None or wb is None or wa.empty or wb.empty:
        return np.nan
    a, b = wa.astype(float).align(wb.astype(float), fill_value=0.0)
    return float(np.minimum(a, b).sum())


def holdings_sets(log: pd.DataFrame) -> dict[date, set[str]]:
    if log is None or log.empty:
        return {}
    work = log.dropna(subset=["symbol"]).copy()
    work["as_of"] = pd.to_datetime(work["as_of"]).dt.date
    return {d: set(g["symbol"].astype(str)) for d, g in work.groupby("as_of")}


def mean_jaccard(log_a: pd.DataFrame, log_b: pd.DataFrame) -> float:
    sa, sb = holdings_sets(log_a), holdings_sets(log_b)
    dates = sorted(set(sa) & set(sb))
    if not dates:
        return np.nan
    return float(np.nanmean([jaccard(sa[d], sb[d]) for d in dates]))


def daily_cvar(returns: pd.Series, alpha: float = 0.05) -> float:
    """Mean of the worst ``alpha`` tail. Negative on a losing name."""
    r = pd.to_numeric(returns, errors="coerce").dropna()
    if len(r) < 20:
        return np.nan
    cutoff = float(r.quantile(alpha))
    tail = r[r <= cutoff]
    if tail.empty:
        return np.nan
    return float(tail.mean())


def trailing_cvar_by_symbol(
    price_panel: pd.DataFrame,
    as_of,
    lookback: int = 60,
    alpha: float = 0.05,
) -> pd.Series:
    hist = price_panel.loc[: pd.Timestamp(as_of)].iloc[-lookback - 1 :]
    if hist.shape[0] < 25:
        return pd.Series(dtype=float)
    rets = hist.pct_change(fill_method=None).dropna(how="all")
    return rets.apply(lambda s: daily_cvar(s, alpha=alpha))


def cvar_weights(
    symbols: pd.Index | list[str],
    cvar: pd.Series,
    name_cap: float | None = 0.10,
) -> pd.Series:
    """More weight on names with milder left tails (smaller |CVaR|)."""
    idx = pd.Index(symbols)
    cv = cvar.reindex(idx)
    loss = (-cv).clip(lower=1e-6)
    inv = 1.0 / loss
    inv = inv.where(cv.notna(), np.nan).dropna()
    inv = inv[inv > 0]
    if inv.empty:
        return pd.Series(dtype=float)
    w = inv / float(inv.sum())
    return apply_name_cap(w, name_cap)


def reweight_log_cvar(
    log: pd.DataFrame,
    price_panel: pd.DataFrame,
    name_cap: float | None = 0.10,
    lookback: int = 60,
    alpha: float = 0.05,
) -> dict[date, pd.Series]:
    """Replace cap-weights in a holdings log with CVaR weights on the same names."""
    if log is None or log.empty:
        return {}
    work = log.dropna(subset=["symbol"]).copy()
    work["as_of"] = pd.to_datetime(work["as_of"]).dt.date
    out: dict[date, pd.Series] = {}
    for as_of, g in work.groupby("as_of"):
        names = g["symbol"].astype(str)
        cv = trailing_cvar_by_symbol(price_panel, as_of, lookback=lookback, alpha=alpha)
        w = cvar_weights(names, cv, name_cap=name_cap)
        if w.empty:
            continue
        out[as_of] = w
    return out


NEAR_DEBT = 0.28
NEAR_CASH = 0.28
NEAR_RECV = 0.68


def nearest_ratio_gap(row: pd.Series, debt=0.30, cash=0.30, recv=0.70) -> tuple[str, float]:
    d = pd.to_numeric(row.get("debt_ratio"), errors="coerce")
    c = pd.to_numeric(row.get("cash_ratio"), errors="coerce")
    r = pd.to_numeric(row.get("receivables_ratio"), errors="coerce")
    gaps = []
    if pd.notna(d):
        gaps.append(("debt", float(debt - d)))
    if pd.notna(c):
        gaps.append(("cash", float(cash - c)))
    if pd.notna(r):
        gaps.append(("recv", float(recv - r)))
    if not gaps:
        return ("none", np.nan)
    name, gap = min(gaps, key=lambda x: x[1])
    return name, gap


def is_near_boundary(row: pd.Series) -> bool:
    d = pd.to_numeric(row.get("debt_ratio"), errors="coerce")
    c = pd.to_numeric(row.get("cash_ratio"), errors="coerce")
    r = pd.to_numeric(row.get("receivables_ratio"), errors="coerce")
    if pd.notna(d) and d >= NEAR_DEBT:
        return True
    if pd.notna(c) and c >= NEAR_CASH:
        return True
    if pd.notna(r) and r >= NEAR_RECV:
        return True
    return False


def boundary_flags(log: pd.DataFrame, metrics: pd.DataFrame) -> pd.DataFrame:
    """Holdings whose latest snapshot ratios sit inside the warning band."""
    if log is None or log.empty or metrics is None or metrics.empty:
        return pd.DataFrame()
    hold = log.dropna(subset=["symbol"]).copy()
    hold["as_of"] = pd.to_datetime(hold["as_of"]).dt.date
    snap = metrics.copy()
    snap["as_of"] = pd.to_datetime(snap["as_of"]).dt.date
    keep = [
        "symbol",
        "as_of",
        "debt_ratio",
        "cash_ratio",
        "receivables_ratio",
    ]
    keep = [c for c in keep if c in snap.columns]
    merged = hold.merge(snap[keep], on=["symbol", "as_of"], how="left")
    rows = []
    for _, row in merged.iterrows():
        if not is_near_boundary(row):
            continue
        which, gap = nearest_ratio_gap(row)
        rows.append(
            {
                "symbol": row["symbol"],
                "as_of": row["as_of"],
                "weight": row.get("weight"),
                "debt_ratio": row.get("debt_ratio"),
                "cash_ratio": row.get("cash_ratio"),
                "receivables_ratio": row.get("receivables_ratio"),
                "near": which,
                "gap_to_limit": gap,
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                "symbol",
                "as_of",
                "weight",
                "debt_ratio",
                "cash_ratio",
                "receivables_ratio",
                "near",
                "gap_to_limit",
            ]
        )
    return pd.DataFrame(rows)


def drop_near_boundary(
    weights_by_date: dict[date, pd.Series],
    flags: pd.DataFrame,
    name_cap: float | None = 0.10,
) -> dict[date, pd.Series]:
    """Zero out warning-band names at that rebalance; leftover is renormalized."""
    flagged = set()
    if flags is not None and not flags.empty:
        flagged = set(zip(pd.to_datetime(flags["as_of"]).dt.date, flags["symbol"].astype(str)))
    out = {}
    for as_of, w in weights_by_date.items():
        drop = [s for s in w.index if (as_of, s) in flagged]
        nw = w.drop(index=drop, errors="ignore")
        nw = nw[nw > 0]
        if nw.empty:
            out[as_of] = nw
            continue
        nw = nw / float(nw.sum())
        out[as_of] = apply_name_cap(nw, name_cap)
    return out
