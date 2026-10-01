"""Five frozen sleeve selectors. Thresholds come from FrozenRules."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .compliance import collapse_issuers, halal_pass, last_snapshot_on_or_before
from .fundamentals import (
    latest_events_as_of,
    qualifying_prints,
    score_cash_generation,
    score_compounding,
)
from .prices import rolling_beta, trading_days_between, trailing_return, trailing_volatility
from .rules import FOCUS_BUCKETS, FrozenRules
from .universe import classify_focus, is_tech_or_clean_energy
from .weighting import assign_cap_weights, assign_equal_weights


def _positive_cap(passed: pd.DataFrame) -> pd.DataFrame:
    if passed is None or passed.empty or "market_cap" not in passed.columns:
        return pd.DataFrame() if passed is None or passed.empty else passed.iloc[0:0]
    return passed[pd.to_numeric(passed["market_cap"], errors="coerce") > 0]


def select_fcf_quality(
    panel: pd.DataFrame,
    as_of: date | str,
    rules: FrozenRules | None = None,
    price_panel: pd.DataFrame | None = None,
) -> pd.DataFrame:
    rules = rules or FrozenRules()
    empty_cols = [
        "symbol",
        "fcf_margin",
        "fcf_yield",
        "market_cap",
        "weight",
        "debt_ratio",
        "cash_ratio",
        "receivables_ratio",
    ]
    snap = last_snapshot_on_or_before(panel, as_of)
    passed = halal_pass(snap, rules)
    if passed.empty:
        return pd.DataFrame(columns=empty_cols)
    passed = score_cash_generation(passed)
    passed = passed[
        passed["fcf"].notna()
        & (pd.to_numeric(passed["fcf"], errors="coerce") > 0)
        & passed["fcf_margin"].notna()
        & np.isfinite(passed["fcf_margin"])
        & (pd.to_numeric(passed["market_cap"], errors="coerce") > 0)
    ]
    cfg = rules.fcf
    if len(passed) < cfg.min_holdings:
        return pd.DataFrame(columns=empty_cols)

    cutoff = passed["fcf_margin"].quantile(1.0 - cfg.keep_quantile)
    selected = passed[passed["fcf_margin"] >= cutoff].copy()
    if len(selected) < cfg.min_holdings:
        selected = passed.nlargest(cfg.min_holdings, "fcf_margin").copy()

    if cfg.drop_high_vol_quantile and price_panel is not None and not price_panel.empty:
        vol_by_symbol = trailing_volatility(price_panel, as_of, lookback=cfg.vol_lookback)
        selected["vol"] = selected["symbol"].map(vol_by_symbol)
        vol_ok = selected["vol"].dropna()
        if len(vol_ok) >= cfg.min_holdings:
            vol_cut = vol_ok.quantile(1 - cfg.drop_high_vol_quantile)
            filtered = selected[selected["vol"].isna() | (selected["vol"] <= vol_cut)]
            if len(filtered) >= cfg.min_holdings:
                selected = filtered

    selected = assign_cap_weights(selected)
    keep = [c for c in empty_cols + ["vol"] if c in selected.columns]
    return selected[keep].sort_values("weight", ascending=False)


def select_roic(
    panel: pd.DataFrame,
    as_of: date | str,
    rules: FrozenRules | None = None,
    focus_map: dict[str, str] | None = None,
) -> pd.DataFrame:
    rules = rules or FrozenRules()
    empty_cols = [
        "symbol",
        "roic",
        "reinvestment_rate",
        "nopat",
        "invested_capital",
        "market_cap",
        "weight",
        "debt_ratio",
        "cash_ratio",
        "receivables_ratio",
        "focus_bucket",
    ]
    snap = last_snapshot_on_or_before(panel, as_of)
    passed = halal_pass(snap, rules)
    if passed.empty:
        return pd.DataFrame(columns=empty_cols)
    passed = score_compounding(passed)
    cfg = rules.roic

    if focus_map:
        passed["focus_bucket"] = passed["symbol"].map(focus_map).fillna("Other")
    elif "sector" in passed.columns or "industry" in passed.columns:
        passed["focus_bucket"] = [
            classify_focus(r.get("sector", ""), r.get("industry", ""))
            for _, r in passed.iterrows()
        ]
    else:
        passed["focus_bucket"] = "Other"

    if cfg.capital_light_only:
        passed = passed[passed["focus_bucket"].isin(FOCUS_BUCKETS)].copy()

    passed = passed[
        passed["roic"].notna()
        & np.isfinite(passed["roic"])
        & (passed["roic"] > cfg.roic_min)
        & (passed["roic"] < cfg.roic_max)
        & (passed["nopat"] > 0)
        & (passed["invested_capital"] > 0)
        & passed["reinvestment_rate"].notna()
        & np.isfinite(passed["reinvestment_rate"])
        & (passed["reinvestment_rate"] > 0)
        & (pd.to_numeric(passed["market_cap"], errors="coerce") > 0)
    ]
    effective_min = min(cfg.min_holdings, max(5, len(passed)))
    if len(passed) < 5:
        return pd.DataFrame(columns=empty_cols)

    cutoff = passed["reinvestment_rate"].quantile(1.0 - cfg.keep_quantile)
    selected = passed[passed["reinvestment_rate"] >= cutoff].copy()
    if len(selected) < effective_min:
        selected = passed.nlargest(effective_min, "reinvestment_rate").copy()

    selected = assign_cap_weights(selected)
    keep = [c for c in empty_cols if c in selected.columns]
    return selected[keep].sort_values("weight", ascending=False)


def select_dual_momentum(
    panel: pd.DataFrame,
    price_panel: pd.DataFrame,
    as_of: date | str,
    rules: FrozenRules | None = None,
) -> pd.DataFrame:
    rules = rules or FrozenRules()
    empty_cols = [
        "symbol",
        "mom_12_1",
        "rel_mom",
        "market_cap",
        "weight",
        "debt_ratio",
        "cash_ratio",
        "receivables_ratio",
    ]
    snap = last_snapshot_on_or_before(panel, as_of)
    passed = _positive_cap(halal_pass(snap, rules))
    if passed.empty:
        return pd.DataFrame(columns=empty_cols)

    cfg = rules.dual_momentum
    spy_mom = trailing_return(
        price_panel, cfg.regime_ticker, as_of, cfg.mom_lookback, cfg.mom_skip
    )
    rows = []
    for _, r in passed.iterrows():
        mom = trailing_return(
            price_panel, r["symbol"], as_of, cfg.mom_lookback, cfg.mom_skip
        )
        if pd.isna(mom) or not np.isfinite(mom):
            continue
        rel = mom - spy_mom if pd.notna(spy_mom) else mom
        rows.append({**r.to_dict(), "mom_12_1": mom, "rel_mom": rel})
    if not rows:
        return pd.DataFrame(columns=empty_cols)

    scored = pd.DataFrame(rows)
    effective_min = min(cfg.min_holdings, max(5, len(scored)))
    if len(scored) < 5:
        return pd.DataFrame(columns=empty_cols)

    cutoff = scored["rel_mom"].quantile(1.0 - cfg.keep_quantile)
    selected = scored[scored["rel_mom"] >= cutoff].copy()
    if len(selected) < effective_min:
        selected = scored.nlargest(effective_min, "rel_mom").copy()

    selected = assign_cap_weights(selected)
    keep = [c for c in empty_cols if c in selected.columns]
    return selected[keep].sort_values("weight", ascending=False)


def select_high_beta(
    panel: pd.DataFrame,
    price_panel: pd.DataFrame,
    as_of: date | str,
    rules: FrozenRules | None = None,
) -> pd.DataFrame:
    rules = rules or FrozenRules()
    empty_cols = [
        "symbol",
        "beta",
        "market_cap",
        "weight",
        "debt_ratio",
        "cash_ratio",
        "receivables_ratio",
    ]
    snap = last_snapshot_on_or_before(panel, as_of)
    passed = halal_pass(snap, rules)
    cfg = rules.high_beta
    if cfg.restrict_tech and not passed.empty:
        if "sector" in passed.columns or "industry" in passed.columns:
            mask = [
                is_tech_or_clean_energy(
                    str(r.get("sector", "") or ""),
                    str(r.get("industry", "") or ""),
                    str(r["symbol"]),
                )
                for _, r in passed.iterrows()
            ]
            passed = passed.loc[mask].copy()
    passed = _positive_cap(passed)
    if passed.empty:
        return pd.DataFrame(columns=empty_cols)

    rows = []
    for _, r in passed.iterrows():
        beta = rolling_beta(
            price_panel, r["symbol"], cfg.market_ticker, as_of, cfg.beta_window
        )
        if pd.isna(beta) or not np.isfinite(beta):
            continue
        rows.append({**r.to_dict(), "beta": beta})
    if not rows:
        return pd.DataFrame(columns=empty_cols)

    scored = pd.DataFrame(rows)
    if cfg.equal_weight_universe:
        selected = scored.copy()
        selected["weight"] = 1.0 / len(selected)
        keep = [c for c in empty_cols if c in selected.columns]
        return selected[keep].sort_values("beta", ascending=False)

    effective_min = min(cfg.min_holdings, max(3, len(scored)))
    if len(scored) < 3:
        return pd.DataFrame(columns=empty_cols)

    cutoff = scored["beta"].quantile(1.0 - cfg.keep_quantile)
    selected = scored[scored["beta"] >= cutoff].copy()
    if len(selected) < effective_min:
        selected = scored.nlargest(effective_min, "beta").copy()

    selected = assign_cap_weights(selected)
    keep = [c for c in empty_cols if c in selected.columns]
    return selected[keep].sort_values("weight", ascending=False)


def select_sue(
    panel: pd.DataFrame,
    sue_events: pd.DataFrame,
    price_index: pd.DatetimeIndex,
    as_of: date | str,
    rules: FrozenRules | None = None,
) -> pd.DataFrame:
    rules = rules or FrozenRules()
    empty_cols = [
        "symbol",
        "sue",
        "ue",
        "sigma_ue",
        "announce_date",
        "days_since_print",
        "market_cap",
        "weight",
        "debt_ratio",
        "cash_ratio",
        "receivables_ratio",
    ]
    if sue_events is None or sue_events.empty or "sue" not in sue_events.columns:
        return pd.DataFrame(columns=empty_cols)
    cfg = rules.sue
    as_of_d = pd.Timestamp(as_of).date()
    live = latest_events_as_of(qualifying_prints(sue_events, cfg.sue_threshold), as_of_d)
    if live.empty:
        return pd.DataFrame(columns=empty_cols)

    live["days_since_print"] = live["announce_date"].map(
        lambda d: trading_days_between(price_index, d, as_of_d)
    )
    live = live[
        (live["days_since_print"] >= 1) & (live["days_since_print"] <= cfg.hold_trading_days)
    ].copy()
    if live.empty:
        return pd.DataFrame(columns=empty_cols)

    snap = last_snapshot_on_or_before(panel, as_of_d)
    passed = collapse_issuers(halal_pass(snap, rules, apply_halal=cfg.apply_halal))
    if passed.empty:
        return pd.DataFrame(columns=empty_cols)
    keep_cols = [
        c
        for c in ("symbol", "market_cap", "debt_ratio", "cash_ratio", "receivables_ratio")
        if c in passed.columns
    ]
    live = live.merge(passed[keep_cols], on="symbol", how="inner")
    if live.empty or len(live) < cfg.min_holdings:
        return pd.DataFrame(columns=empty_cols)

    selected = assign_equal_weights(live) if cfg.equal_weight else assign_cap_weights(live)
    keep = [c for c in empty_cols if c in selected.columns]
    return selected[keep].sort_values("weight", ascending=False)


SELECTORS = {
    "fcf_quality": select_fcf_quality,
    "roic": select_roic,
    "dual_momentum": select_dual_momentum,
    "high_beta": select_high_beta,
    "sue": select_sue,
}
