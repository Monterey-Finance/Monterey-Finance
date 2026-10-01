"""Forced AAOIFI exits between monthly rebalances (paper 10).

The live book screens at month-end. A 10-Q can land mid-month, and a price
path can push 24-month market-cap ratios over the line. This module:

1. Finds the first date a *held* name fails after the last rebalance.
2. Builds a patched weight schedule for a chosen lag
   (``same_day``, ``next_open``, or ``month_end``).
3. Once a name is cut, it stays out until the next scheduled rebalance.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .rules import AaoifiRules, FrozenRules
from .weighting import apply_name_cap

LAGS = ("month_end", "same_day", "next_open")
MONITORS = ("filings", "daily")


def _aaoifi(rules: FrozenRules | AaoifiRules | None) -> AaoifiRules:
    if isinstance(rules, FrozenRules):
        return rules.aaoifi
    return rules or AaoifiRules()


def _as_date(value) -> date:
    return pd.Timestamp(value).date()


def session_on_or_after(price_index: pd.DatetimeIndex, as_of) -> date | None:
    """First trading day on or after ``as_of``."""
    if price_index is None or len(price_index) == 0:
        return None
    idx = pd.to_datetime(price_index).sort_values()
    hit = idx[idx >= pd.Timestamp(as_of)]
    if hit.empty:
        return None
    return hit[0].date()


def session_after(price_index: pd.DatetimeIndex, as_of) -> date | None:
    """First trading day strictly after ``as_of``."""
    if price_index is None or len(price_index) == 0:
        return None
    idx = pd.to_datetime(price_index).sort_values()
    hit = idx[idx > pd.Timestamp(as_of)]
    if hit.empty:
        return None
    return hit[0].date()


def exit_session(price_index: pd.DatetimeIndex, detect: date | str, lag: str) -> date | None:
    """Map a known-fail date onto a trade date."""
    lag = (lag or "month_end").lower()
    if lag in {"month_end", "none", "off"}:
        return None
    known = session_on_or_after(price_index, detect)
    if known is None:
        return None
    if lag == "same_day":
        return known
    if lag == "next_open":
        return session_after(price_index, known)
    raise ValueError(f"Unknown breach lag {lag!r}. Choose from {LAGS}.")


def unique_filings(metrics: pd.DataFrame) -> pd.DataFrame:
    """One row per (symbol, filed_date): the first month-end that used that 10-Q/K."""
    if metrics is None or metrics.empty:
        return pd.DataFrame()
    need = {"symbol", "filed_date"}
    if not need.issubset(metrics.columns):
        return pd.DataFrame()
    work = metrics.copy()
    work["filed_date"] = pd.to_datetime(work["filed_date"])
    work["as_of"] = pd.to_datetime(work["as_of"])
    work = work.dropna(subset=["symbol", "filed_date"])
    return work.sort_values("as_of").groupby(["symbol", "filed_date"], as_index=False).head(1)


def _num(value) -> float:
    v = pd.to_numeric(value, errors="coerce")
    if v is None or pd.isna(v) or not np.isfinite(float(v)):
        return 0.0
    return float(v)


def _ratio_row(
    total_debt,
    cash_and_equiv,
    ibs,
    receivables,
    liquid_assets,
    market_cap_24m,
    rules: AaoifiRules,
) -> dict:
    mc = float(market_cap_24m) if pd.notna(market_cap_24m) else np.nan
    if not np.isfinite(mc) or mc <= 0:
        return {
            "is_compliant": False,
            "debt_ratio": np.nan,
            "cash_ratio": np.nan,
            "receivables_ratio": np.nan,
            "reason": "missing market cap",
        }
    debt = _num(total_debt)
    cash = _num(cash_and_equiv) + _num(ibs)
    recv = _num(receivables) + _num(liquid_assets)
    debt_r = debt / mc
    cash_r = cash / mc
    recv_r = recv / mc
    if debt_r >= rules.debt_threshold:
        reason = "debt ratio exceeds threshold"
        ok = False
    elif cash_r >= rules.cash_threshold:
        reason = "cash ratio exceeds threshold"
        ok = False
    elif recv_r >= rules.receivables_threshold:
        reason = "receivables ratio exceeds threshold"
        ok = False
    else:
        reason = "passes AAOIFI financial screens"
        ok = True
    return {
        "is_compliant": ok,
        "debt_ratio": debt_r,
        "cash_ratio": cash_r,
        "receivables_ratio": recv_r,
        "reason": reason,
    }


def _px(panel: pd.DataFrame, symbol: str, as_of) -> float:
    if panel is None or panel.empty or symbol not in panel.columns:
        return np.nan
    s = panel[symbol].dropna()
    s = s.loc[: pd.Timestamp(as_of)]
    if s.empty:
        return np.nan
    return float(s.iloc[-1])


def scaled_mc24(
    mc24_ref: float,
    spot_ref: float,
    px_ref: float,
    px_now: float,
) -> float:
    """Move the 24-month average by about 1/24 of the spot move since the snapshot."""
    if not np.isfinite(mc24_ref) or mc24_ref <= 0:
        return np.nan
    if not np.isfinite(spot_ref) or spot_ref <= 0 or not np.isfinite(px_ref) or px_ref <= 0:
        return mc24_ref
    if not np.isfinite(px_now) or px_now <= 0:
        return mc24_ref
    return mc24_ref + spot_ref * (px_now / px_ref - 1.0) / 24.0


def _filing_fundamentals(row: pd.Series) -> dict:
    return {
        "total_debt": row.get("total_debt"),
        "cash_and_equiv": row.get("cash_and_equiv"),
        "ibs": row.get("interest_bearing_securities"),
        "receivables": row.get("receivables"),
        "liquid_assets": row.get("liquid_assets"),
    }


def _metrics_by_symbol(metrics: pd.DataFrame) -> dict[str, pd.DataFrame]:
    work = metrics.copy()
    work["as_of"] = pd.to_datetime(work["as_of"]).dt.date
    return {sym: g.sort_values("as_of") for sym, g in work.groupby("symbol", sort=False)}


def _row_on_or_before(frame: pd.DataFrame | None, as_of) -> pd.Series | None:
    if frame is None or frame.empty:
        return None
    as_of_d = _as_date(as_of)
    prior = frame[frame["as_of"] <= as_of_d]
    if prior.empty:
        return None
    return prior.iloc[-1]


def _mc_from_row(row: pd.Series | None) -> tuple[float, float]:
    if row is None:
        return np.nan, np.nan
    mc24 = pd.to_numeric(row.get("market_cap_24m", row.get("market_cap")), errors="coerce")
    spot = pd.to_numeric(row.get("market_cap", mc24), errors="coerce")
    return float(mc24) if pd.notna(mc24) else np.nan, float(spot) if pd.notna(spot) else np.nan


def detect_breaches(
    metrics: pd.DataFrame,
    holdings_log: pd.DataFrame,
    price_panel: pd.DataFrame,
    rules: FrozenRules | None = None,
    monitor: str = "filings",
    end: date | str | None = None,
    throttle_on: pd.Series | None = None,
) -> pd.DataFrame:
    """First intra-month AAOIFI fail for each holding spell.

    ``monitor="filings"`` only re-screens when a new ``filed_date`` is known.
    ``monitor="daily"`` also walks the price path with a 24-month MC approximation.
    """
    rules = rules or FrozenRules()
    aaoifi = _aaoifi(rules)
    monitor = (monitor or "filings").lower()
    if monitor not in MONITORS:
        raise ValueError(f"Unknown monitor {monitor!r}. Choose from {MONITORS}.")
    empty_cols = [
        "symbol",
        "rebalance",
        "next_rebalance",
        "detect_date",
        "weight",
        "source",
        "reason",
        "debt_ratio",
        "cash_ratio",
        "receivables_ratio",
        "filed_date",
    ]
    if holdings_log is None or holdings_log.empty or metrics is None or metrics.empty:
        return pd.DataFrame(columns=empty_cols)

    log = holdings_log.copy()
    log["as_of"] = pd.to_datetime(log["as_of"]).dt.date
    if "as_of" in metrics.columns:
        rebals = sorted({pd.Timestamp(d).date() for d in metrics["as_of"].dropna().unique()})
        if log["as_of"].notna().any():
            lo, hi = min(log["as_of"]), max(log["as_of"])
            rebals = [d for d in rebals if lo <= d <= hi]
    else:
        rebals = sorted(log["as_of"].dropna().unique())
    by_sym = _metrics_by_symbol(metrics)
    filings = unique_filings(metrics)
    filings_by_sym: dict[str, pd.DataFrame] = {}
    if not filings.empty:
        filings = filings.copy()
        filings["filed_date"] = pd.to_datetime(filings["filed_date"]).dt.date
        filings["as_of"] = pd.to_datetime(filings["as_of"]).dt.date
        filings_by_sym = {
            sym: g.sort_values("filed_date") for sym, g in filings.groupby("symbol", sort=False)
        }

    end_d = _as_date(end) if end is not None else (
        price_panel.index.max().date() if price_panel is not None and len(price_panel) else rebals[-1]
    )

    events: list[dict] = []
    throttle = None
    if throttle_on is not None and not throttle_on.empty:
        throttle = throttle_on.copy()
        throttle.index = pd.to_datetime(throttle.index)

    for i, reb in enumerate(rebals):
        nxt = rebals[i + 1] if i + 1 < len(rebals) else end_d
        if throttle is not None:
            ts = pd.Timestamp(reb)
            if ts in throttle.index and not bool(throttle.loc[ts]):
                continue
            span = throttle.loc[(throttle.index > ts) & (throttle.index <= pd.Timestamp(nxt))]
            off = span[~span.astype(bool)]
            if not off.empty:
                nxt = off.index[0].date()
        held = log[log["as_of"] == reb]
        if held.empty:
            continue
        sessions = None
        if monitor == "daily" and price_panel is not None and not price_panel.empty:
            sessions = price_panel.index[
                (price_panel.index > pd.Timestamp(reb))
                & (price_panel.index < pd.Timestamp(nxt))
            ]

        for _, h in held.iterrows():
            symbol = h["symbol"]
            weight = float(h["weight"]) if pd.notna(h.get("weight")) else np.nan
            event = None
            hist = by_sym.get(symbol)

            mid = filings_by_sym.get(symbol)
            if mid is not None and not mid.empty:
                window = mid[(mid["filed_date"] > reb) & (mid["filed_date"] <= nxt)]
                px_ref = _px(price_panel, symbol, reb)
                for _, fil in window.iterrows():
                    mc24, spot = _mc_from_row(_row_on_or_before(hist, fil["filed_date"]))
                    px_now = _px(price_panel, symbol, fil["filed_date"])
                    mc_use = scaled_mc24(mc24, spot, px_ref, px_now)
                    if not np.isfinite(mc_use):
                        mc_use = mc24
                    fund = _filing_fundamentals(fil)
                    scored = _ratio_row(
                        fund["total_debt"],
                        fund["cash_and_equiv"],
                        fund["ibs"],
                        fund["receivables"],
                        fund["liquid_assets"],
                        mc_use,
                        aaoifi,
                    )
                    if not scored["is_compliant"]:
                        event = {
                            "symbol": symbol,
                            "rebalance": reb,
                            "next_rebalance": nxt,
                            "detect_date": fil["filed_date"],
                            "weight": weight,
                            "source": "filing",
                            "reason": scored["reason"],
                            "debt_ratio": scored["debt_ratio"],
                            "cash_ratio": scored["cash_ratio"],
                            "receivables_ratio": scored["receivables_ratio"],
                            "filed_date": fil["filed_date"],
                        }
                        break

            if event is None and monitor == "daily" and sessions is not None and len(sessions):
                row = _row_on_or_before(hist, reb)
                if row is not None:
                    fund = _filing_fundamentals(row)
                    mc24, spot = _mc_from_row(row)
                    px_ref = _px(price_panel, symbol, reb)
                    px_s = (
                        price_panel[symbol].reindex(sessions)
                        if symbol in price_panel.columns
                        else None
                    )
                    if px_s is not None:
                        for dt, px_now in px_s.items():
                            mc_use = scaled_mc24(mc24, spot, px_ref, float(px_now) if pd.notna(px_now) else np.nan)
                            scored = _ratio_row(
                                fund["total_debt"],
                                fund["cash_and_equiv"],
                                fund["ibs"],
                                fund["receivables"],
                                fund["liquid_assets"],
                                mc_use,
                                aaoifi,
                            )
                            if not scored["is_compliant"]:
                                event = {
                                    "symbol": symbol,
                                    "rebalance": reb,
                                    "next_rebalance": nxt,
                                    "detect_date": dt.date(),
                                    "weight": weight,
                                    "source": "price",
                                    "reason": scored["reason"],
                                    "debt_ratio": scored["debt_ratio"],
                                    "cash_ratio": scored["cash_ratio"],
                                    "receivables_ratio": scored["receivables_ratio"],
                                    "filed_date": pd.NaT,
                                }
                                break

            if event is not None:
                events.append(event)

    if not events:
        return pd.DataFrame(columns=empty_cols)
    out = pd.DataFrame(events)
    out["detect_date"] = pd.to_datetime(out["detect_date"]).dt.date
    return out.sort_values(["detect_date", "symbol"]).reset_index(drop=True)


def drop_name(weights: pd.Series, symbol: str, name_cap: float | None) -> pd.Series:
    w = weights.astype(float).copy()
    if symbol in w.index:
        w = w.drop(symbol)
    w = w[w > 0]
    if w.empty:
        return w
    w = w / float(w.sum())
    return apply_name_cap(w, name_cap)


def apply_breach_exits(
    weights_by_date: dict[date, pd.Series],
    events: pd.DataFrame,
    price_index: pd.DatetimeIndex,
    lag: str = "same_day",
    name_cap: float | None = 0.10,
) -> dict[date, pd.Series]:
    """Insert intra-month weight dates that drop failed names.

    ``month_end`` returns the schedule unchanged. Cuts are sticky until the
    next key already in ``weights_by_date``.
    """
    lag = (lag or "month_end").lower()
    schedule = {k: v.copy() for k, v in weights_by_date.items()}
    if lag in {"month_end", "none", "off"} or events is None or events.empty:
        return schedule

    cuts: list[tuple[date, str]] = []
    for _, ev in events.iterrows():
        trade = exit_session(price_index, ev["detect_date"], lag)
        if trade is None:
            continue
        reb = ev["rebalance"]
        reb_d = reb if isinstance(reb, date) else pd.Timestamp(reb).date()
        nxt = ev["next_rebalance"]
        nxt_d = nxt if isinstance(nxt, date) else (pd.Timestamp(nxt).date() if pd.notna(nxt) else None)
        if nxt_d is not None and trade >= nxt_d:
            continue
        if trade <= reb_d:
            continue
        cuts.append((trade, str(ev["symbol"])))

    for trade, symbol in sorted(cuts):
        prior = [d for d in sorted(schedule) if d <= trade]
        if not prior:
            continue
        schedule[trade] = drop_name(schedule[prior[-1]], symbol, name_cap)
    return schedule


def noncompliant_exposure(
    events: pd.DataFrame,
    price_index: pd.DatetimeIndex,
    lag: str,
) -> pd.DataFrame:
    """Name-days and weight-days still held after the fail is known."""
    rows = []
    if events is None or events.empty:
        return pd.DataFrame(
            columns=["symbol", "detect_date", "exit_date", "name_days", "weight_days"]
        )
    for _, ev in events.iterrows():
        detect = ev["detect_date"]
        nxt = ev["next_rebalance"]
        trade = exit_session(price_index, detect, lag)
        if trade is None:
            trade = nxt if isinstance(nxt, date) else pd.Timestamp(nxt).date()
        sessions = price_index[
            (price_index >= pd.Timestamp(detect))
            & (price_index < pd.Timestamp(trade))
        ]
        n = int(len(sessions))
        w = float(ev["weight"]) if pd.notna(ev.get("weight")) else np.nan
        rows.append(
            {
                "symbol": ev["symbol"],
                "detect_date": detect,
                "exit_date": trade,
                "name_days": n,
                "weight_days": n * w if np.isfinite(w) else np.nan,
                "weight": w,
                "reason": ev.get("reason"),
                "source": ev.get("source"),
            }
        )
    return pd.DataFrame(rows)


def extra_turnover(events: pd.DataFrame) -> float:
    """One-way weight sold at forced exits (also bought into remaining names)."""
    if events is None or events.empty or "weight" not in events.columns:
        return 0.0
    return float(pd.to_numeric(events["weight"], errors="coerce").fillna(0).sum())
