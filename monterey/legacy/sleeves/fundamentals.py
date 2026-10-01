"""Point-in-time joins for FCF, ROIC, and SUE signals."""

from __future__ import annotations

import numpy as np
import pandas as pd


def attach_latest_value(
    metrics: pd.DataFrame,
    history: pd.DataFrame,
    value_cols: list[str],
    on_date: str = "filed_date",
) -> pd.DataFrame:
    """As-of join: latest filing known on each metrics snapshot (no look-ahead)."""
    if metrics.empty:
        return metrics.copy()
    if history is None or history.empty:
        out = metrics.copy()
        for col in value_cols:
            if col not in out.columns:
                out[col] = np.nan
        return out

    hist = history.copy()
    hist[on_date] = pd.to_datetime(hist[on_date])
    keep = ["symbol", on_date] + [c for c in value_cols if c in hist.columns]
    hist = hist[keep].dropna(subset=["symbol", on_date]).sort_values(["symbol", on_date])

    pieces: list[pd.DataFrame] = []
    for as_of, snap in metrics.groupby("as_of", sort=True):
        as_of_ts = pd.Timestamp(as_of)
        known = hist[hist[on_date] <= as_of_ts]
        if known.empty:
            extra = snap.copy()
            for col in value_cols:
                if col not in extra.columns:
                    extra[col] = np.nan
            pieces.append(extra)
            continue
        latest = known.sort_values(on_date).groupby("symbol", as_index=False).tail(1)
        drop_cols = [c for c in value_cols if c in snap.columns]
        left = snap.drop(columns=drop_cols, errors="ignore")
        pieces.append(left.merge(latest.drop(columns=[on_date]), on="symbol", how="left"))
    return pd.concat(pieces, ignore_index=True)


def attach_latest_fcf(metrics: pd.DataFrame, fcf_history: pd.DataFrame) -> pd.DataFrame:
    return attach_latest_value(metrics, fcf_history, ["fcf"])


def attach_latest_roic(metrics: pd.DataFrame, roic_history: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "roic",
        "reinvestment_rate",
        "nopat",
        "invested_capital",
        "capex_to_sales",
        "rd",
    ]
    return attach_latest_value(metrics, roic_history, cols)


def score_cash_generation(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel.copy()
    fcf = pd.to_numeric(out["fcf"], errors="coerce")
    revenue = pd.to_numeric(out.get("total_revenue"), errors="coerce")
    cap = pd.to_numeric(out.get("market_cap"), errors="coerce")
    debt = pd.to_numeric(out.get("total_debt"), errors="coerce").fillna(0)
    cash = pd.to_numeric(out.get("cash_and_equiv"), errors="coerce").fillna(0)
    out["fcf_margin"] = fcf / revenue.replace(0, np.nan)
    out["market_cap"] = cap
    ev = cap + debt - cash
    out["fcf_yield"] = fcf / ev.replace(0, np.nan)
    return out


def score_compounding(panel: pd.DataFrame) -> pd.DataFrame:
    out = panel.copy()
    for col in ("roic", "reinvestment_rate", "nopat", "invested_capital", "market_cap"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def robust_sigma(hist: pd.Series) -> float:
    h = hist.dropna().astype(float)
    if len(h) < 3:
        return np.nan
    lo, hi = h.quantile(0.05), h.quantile(0.95)
    clipped = h.clip(lo, hi)
    sigma = float(clipped.std(ddof=1))
    floor = 0.5 * float(h.abs().median())
    sigma = max(sigma, floor, 1e-8)
    return sigma if np.isfinite(sigma) else np.nan


def attach_sue(earnings: pd.DataFrame, min_prior: int = 6) -> pd.DataFrame:
    """Point-in-time SUE on % surprise when available, else EPS forecast error."""
    if earnings.empty:
        out = earnings.copy()
        out["sue"] = pd.Series(dtype=float)
        out["sigma_ue"] = pd.Series(dtype=float)
        out["n_prior"] = pd.Series(dtype=int)
        out["sue_source"] = pd.Series(dtype=str)
        return out

    pieces: list[pd.DataFrame] = []
    for _, grp in earnings.groupby("symbol", sort=False):
        g = grp.sort_values("announce_date").copy()
        pct = (
            g["surprise_pct"].astype(float)
            if "surprise_pct" in g.columns
            else pd.Series(np.nan, index=g.index)
        )
        ue = g["ue"].astype(float)
        sigmas, sues, priors, srcs = [], [], [], []
        for i in range(len(g)):
            hist_pct = pct.iloc[:i].dropna()
            hist_ue = ue.iloc[:i].dropna()
            if len(hist_pct) >= min_prior and pd.notna(pct.iloc[i]):
                sigma = robust_sigma(hist_pct)
                n_prior = int(len(hist_pct))
                src = "surprise_pct"
                err = float(pct.iloc[i])
            elif len(hist_ue) >= min_prior:
                sigma = robust_sigma(hist_ue)
                n_prior = int(len(hist_ue))
                src = "ue"
                err = float(ue.iloc[i])
            else:
                sigmas.append(np.nan)
                sues.append(np.nan)
                priors.append(int(max(len(hist_pct), len(hist_ue))))
                srcs.append("")
                continue
            priors.append(n_prior)
            srcs.append(src)
            if not np.isfinite(sigma) or sigma <= 0:
                sigmas.append(np.nan)
                sues.append(np.nan)
                continue
            sigmas.append(sigma)
            sues.append(err / sigma)
        g["sigma_ue"] = sigmas
        g["sue"] = sues
        g["n_prior"] = priors
        g["sue_source"] = srcs
        pieces.append(g)
    return pd.concat(pieces, ignore_index=True)


def qualifying_prints(sue_events: pd.DataFrame, sue_threshold: float = 2.0) -> pd.DataFrame:
    if sue_events is None or sue_events.empty or "sue" not in sue_events.columns:
        return pd.DataFrame(
            columns=["symbol", "announce_date", "sue", "ue", "sigma_ue"]
        )
    return sue_events[
        sue_events["sue"].notna()
        & np.isfinite(sue_events["sue"])
        & (sue_events["sue"] > sue_threshold)
        & (sue_events["ue"].fillna(0) > 0)
    ].copy()


def latest_events_as_of(sue_events: pd.DataFrame, as_of) -> pd.DataFrame:
    if sue_events.empty:
        return sue_events.iloc[0:0].copy()
    as_of_d = pd.Timestamp(as_of).date()
    snap = sue_events[pd.to_datetime(sue_events["announce_date"]).dt.date <= as_of_d].copy()
    if snap.empty:
        return snap
    snap = snap.sort_values(["symbol", "announce_date"])
    return snap.groupby("symbol", as_index=False).tail(1)


def _to_naive_ts(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if getattr(ts, "tzinfo", None) is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts.normalize()


def _col(frame: pd.DataFrame, *names: str) -> pd.Series | None:
    lookup = {str(c).strip().lower(): c for c in frame.columns}
    for name in names:
        hit = lookup.get(name.strip().lower())
        if hit is not None:
            return frame[hit]
    # substring fallback: "Reported EPS" matches "reported eps"
    for name in names:
        needle = name.strip().lower()
        for key, col in lookup.items():
            if needle in key:
                return frame[col]
    return None


def fetch_earnings_history(symbols: list[str], limit: int = 40) -> pd.DataFrame:
    """Quarterly consensus vs actual EPS from Yahoo earnings dates.

    Column names vary by yfinance version (Reported EPS vs epsActual). Empty
    result with a printed sample means the parser missed a new schema.
    """
    import yfinance as yf

    from .weighting import collapse_share_classes

    rows: list[dict] = []
    n = len(symbols)
    sample_cols: list[str] | None = None
    for i, symbol in enumerate(symbols, 1):
        if i == 1 or i % 25 == 0 or i == n:
            print(f"  Earnings calendar {i}/{n}", flush=True)
        try:
            ticker = yf.Ticker(symbol)
            try:
                raw = ticker.get_earnings_dates(limit=limit)
            except TypeError:
                raw = ticker.get_earnings_dates()
            if raw is None or not isinstance(raw, pd.DataFrame) or raw.empty:
                raw = getattr(ticker, "earnings_dates", None)
            if raw is None or not isinstance(raw, pd.DataFrame) or raw.empty:
                continue
        except Exception:
            continue

        frame = raw.copy()
        if not isinstance(frame.index, pd.RangeIndex):
            frame = frame.reset_index()
        if sample_cols is None:
            sample_cols = [str(c) for c in frame.columns]

        date_col = None
        for candidate in frame.columns:
            key = str(candidate).strip().lower().replace("_", " ")
            if key in {"earnings date", "date", "index", "announce date"}:
                date_col = candidate
                break
        if date_col is None:
            for candidate in frame.columns:
                if pd.api.types.is_datetime64_any_dtype(frame[candidate]):
                    date_col = candidate
                    break
        if date_col is None:
            continue

        actual = _col(frame, "Reported EPS", "reported EPS", "epsActual", "reported_eps")
        estimate = _col(frame, "EPS Estimate", "epsEstimate", "eps_estimate")
        surprise = _col(frame, "Surprise(%)", "surprisePercent", "surprise_pct")
        if actual is None or estimate is None:
            continue

        for loc in frame.index:
            try:
                announce = _to_naive_ts(frame.at[loc, date_col])
            except Exception:
                continue
            act = pd.to_numeric(actual.at[loc], errors="coerce")
            est = pd.to_numeric(estimate.at[loc], errors="coerce")
            if pd.isna(act) or pd.isna(est):
                continue
            spr = np.nan
            if surprise is not None:
                spr = pd.to_numeric(surprise.at[loc], errors="coerce")
            if pd.isna(spr) and float(est) != 0:
                spr = (float(act) - float(est)) / abs(float(est))
            rows.append(
                {
                    "symbol": symbol,
                    "announce_date": announce.date(),
                    "eps_actual": float(act),
                    "eps_estimate": float(est),
                    "ue": float(act) - float(est),
                    "surprise_pct": float(spr) if pd.notna(spr) else np.nan,
                }
            )

    empty = pd.DataFrame(
        columns=["symbol", "announce_date", "eps_actual", "eps_estimate", "ue", "surprise_pct"]
    )
    if not rows:
        if sample_cols:
            print("  Yahoo earnings columns were:", sample_cols)
        return empty
    out = pd.DataFrame(rows).drop_duplicates(subset=["symbol", "announce_date"])
    return collapse_share_classes(out.sort_values(["symbol", "announce_date"]).reset_index(drop=True))
