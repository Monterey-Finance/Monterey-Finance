"""Registered brains. The five Phase 1 selectors plus the October FCF layers."""

from __future__ import annotations

import numpy as np
import pandas as pd

from monterey.layers.signals.registry import Context, brain
from monterey.legacy.sleeves.fundamentals import attach_latest_roic, score_cash_generation
from monterey.legacy.sleeves.rules import FrozenRules
from monterey.legacy.sleeves.select import (
    select_dual_momentum,
    select_fcf_quality,
    select_high_beta,
    select_roic,
    select_sue,
)


def _rules(ctx: Context) -> FrozenRules:
    s = ctx.spec.screen
    rules = FrozenRules()
    rules.aaoifi.debt_threshold = float(s["debt"])
    rules.aaoifi.cash_threshold = float(s["cash"])
    rules.aaoifi.receivables_threshold = float(s["receivables"])
    return rules


def _snapshot(ctx: Context) -> pd.DataFrame:
    """Metrics for index members in force. Sector bans apply when the spec asks."""
    snap = ctx.snapshot(compliant_only=False)
    if snap.empty:
        return snap
    members = set(ctx.screen["symbol"].astype(str)) if ctx.screen is not None and not ctx.screen.empty else set()
    if members:
        snap = snap[snap["symbol"].astype(str).isin(members)]
    if ctx.spec.screen.get("sectors"):
        allowed = set(ctx.screen.loc[ctx.screen["sector_allowed"].astype(bool), "symbol"].astype(str))
        snap = snap[snap["symbol"].astype(str).isin(allowed)]
    return snap


def _price_panel(ctx: Context) -> pd.DataFrame:
    return ctx.data.prices.adj_close.ffill().loc[: pd.Timestamp(ctx.as_of)]


def _finish(selected: pd.DataFrame, score: str) -> pd.DataFrame:
    if selected is None or selected.empty:
        return pd.DataFrame(columns=["symbol", "score", "market_cap"])
    out = selected.copy()
    out["score"] = pd.to_numeric(out[score], errors="coerce")
    return out.sort_values("score", ascending=False)


@brain("fcf_quality")
def fcf_quality(
    ctx: Context,
    keep_quantile: float = 0.5,
    min_holdings: int = 20,
    drop_high_vol_quantile: float | None = None,
) -> pd.DataFrame:
    """Paper 01: top ``keep_quantile`` of compliant names by FCF / sales, cap-weighted."""
    rules = _rules(ctx).with_fcf(
        keep_quantile=float(keep_quantile),
        min_holdings=int(min_holdings),
        drop_high_vol_quantile=drop_high_vol_quantile,
    )
    snap = _snapshot(ctx)
    selected = select_fcf_quality(snap, ctx.as_of, rules, price_panel=_price_panel(ctx))
    return _finish(selected, "fcf_margin")


@brain("roic")
def roic(ctx: Context, roic_min: float = 0.15, keep_quantile: float = 0.5, min_holdings: int = 20) -> pd.DataFrame:
    """Paper 02: ROIC above the floor, top half by reinvestment. Needs ``extras['roic_history']``."""
    history = ctx.data.extras.get("roic_history")
    if history is None or history.empty:
        raise ValueError("roic brain needs data.extras['roic_history']")
    rules = _rules(ctx).with_roic(roic_min=float(roic_min), keep_quantile=float(keep_quantile), min_holdings=int(min_holdings))
    panel = attach_latest_roic(_snapshot(ctx), history)
    return _finish(select_roic(panel, ctx.as_of, rules), "reinvestment_rate")


@brain("dual_momentum")
def dual_momentum(ctx: Context, keep_quantile: float = 0.2, min_holdings: int = 15) -> pd.DataFrame:
    """Paper 04 stock list: top quintile by 12–1 return relative to SPY (no SMA inside; use the overlay)."""
    rules = _rules(ctx).with_dual_momentum(keep_quantile=float(keep_quantile), min_holdings=int(min_holdings), apply_sma=False)
    return _finish(select_dual_momentum(_snapshot(ctx), _price_panel(ctx), ctx.as_of, rules), "rel_mom")


@brain("high_beta")
def high_beta(ctx: Context, keep_quantile: float = 0.2, min_holdings: int = 8) -> pd.DataFrame:
    """Paper 05: top-quintile trailing beta in Halal tech / clean energy."""
    rules = _rules(ctx).with_high_beta(keep_quantile=float(keep_quantile), min_holdings=int(min_holdings))
    snap = _snapshot(ctx)
    snap["sector"] = snap["sector"].fillna("").str.title()
    snap["industry"] = ""
    return _finish(select_high_beta(snap, _price_panel(ctx), ctx.as_of, rules), "beta")


@brain("sue")
def sue(ctx: Context, sue_threshold: float = 2.0, hold_trading_days: int = 21) -> pd.DataFrame:
    """Paper 06: robust SUE above 2σ in the 21-day drift window. Needs ``extras['sue_events']``."""
    events = ctx.data.extras.get("sue_events")
    if events is None or events.empty:
        raise ValueError("sue brain needs data.extras['sue_events']")
    rules = _rules(ctx).with_sue(sue_threshold=float(sue_threshold), hold_trading_days=int(hold_trading_days))
    out = select_sue(_snapshot(ctx), events, ctx.data.sessions, ctx.as_of, rules)
    return _finish(out, "sue")


@brain("fcf_layers")
def fcf_layers(
    ctx: Context,
    keep_quantile: float = 0.5,
    min_holdings: int = 20,
    conversion_min: float | None = None,
    stability_lookback: int = 36,
    stability_min_positive: float | None = None,
    stability_max_cv: float | None = None,
    yield_drop_quantile: float | None = None,
) -> pd.DataFrame:
    """
    FCF quality in layers. Each layer is off when its parameter is None.

    1. Margin: top ``keep_quantile`` by FCF / sales (paper 01).
    2. Conversion: FCF / EBITDA at least ``conversion_min``.
    3. Stability: over ``stability_lookback`` month-end snapshots, the share with
       positive FCF is at least ``stability_min_positive`` and the coefficient
       of variation of FCF margin is at most ``stability_max_cv``.
    4. Valuation: drop the ``yield_drop_quantile`` most expensive names by FCF / EV.

    A layer that would leave fewer than ``min_holdings`` names is skipped for that date.
    """
    rules = _rules(ctx)
    snap = _snapshot(ctx)
    from monterey.legacy.sleeves.compliance import halal_pass

    passed = halal_pass(snap, rules)
    if passed.empty:
        return pd.DataFrame(columns=["symbol", "score", "market_cap"])
    passed = score_cash_generation(passed)
    fcf = pd.to_numeric(passed["fcf"], errors="coerce")
    passed = passed[(fcf > 0) & np.isfinite(passed["fcf_margin"]) & (pd.to_numeric(passed["market_cap"], errors="coerce") > 0)].copy()
    if len(passed) < min_holdings:
        return pd.DataFrame(columns=["symbol", "score", "market_cap"])
    cutoff = passed["fcf_margin"].quantile(1.0 - float(keep_quantile))
    stage = passed[passed["fcf_margin"] >= cutoff].copy()
    if len(stage) < min_holdings:
        stage = passed.nlargest(int(min_holdings), "fcf_margin").copy()
    stage["layers"] = "margin"

    def apply(mask: pd.Series, name: str) -> None:
        nonlocal stage
        kept = stage[mask.reindex(stage.index).fillna(False).astype(bool)]
        if len(kept) >= min_holdings:
            stage = kept.copy()
            stage["layers"] = stage["layers"] + f"+{name}"

    if conversion_min is not None and "ebitda" in stage.columns:
        ebitda = pd.to_numeric(stage["ebitda"], errors="coerce")
        stage["fcf_conversion"] = pd.to_numeric(stage["fcf"], errors="coerce") / ebitda.where(ebitda > 0)
        apply(stage["fcf_conversion"] >= float(conversion_min), "conversion")

    if stability_min_positive is not None or stability_max_cv is not None:
        stats = _fcf_stability(ctx, list(stage["symbol"]), int(stability_lookback))
        stage = stage.merge(stats, on="symbol", how="left")
        mask = pd.Series(True, index=stage.index)
        if stability_min_positive is not None:
            mask &= stage["fcf_positive_share"] >= float(stability_min_positive)
        if stability_max_cv is not None:
            mask &= stage["fcf_margin_cv"] <= float(stability_max_cv)
        apply(mask, "stability")

    if yield_drop_quantile is not None:
        floor = stage["fcf_yield"].quantile(float(yield_drop_quantile))
        apply(stage["fcf_yield"] >= floor, "yield")

    stage["score"] = stage["fcf_margin"]
    keep = [c for c in ("symbol", "score", "market_cap", "fcf_margin", "fcf_yield", "fcf_conversion", "fcf_positive_share", "fcf_margin_cv", "layers", "debt_ratio", "cash_ratio", "receivables_ratio") if c in stage.columns]
    return stage[keep].sort_values("score", ascending=False)


def _fcf_stability(ctx: Context, symbols: list[str], lookback: int) -> pd.DataFrame:
    metrics = ctx.data.metrics
    end = pd.Timestamp(ctx.as_of)
    start = end - pd.DateOffset(months=int(lookback))
    window = metrics[(metrics["as_of"] > start) & (metrics["as_of"] <= end) & metrics["symbol"].isin(symbols)].copy()
    if window.empty:
        return pd.DataFrame({"symbol": symbols, "fcf_positive_share": np.nan, "fcf_margin_cv": np.nan})
    fcf = pd.to_numeric(window.get("fcf", window.get("free_cash_flow")), errors="coerce")
    revenue = pd.to_numeric(window["total_revenue"], errors="coerce").where(lambda s: s > 0)
    window["margin"] = fcf / revenue
    window["positive"] = fcf > 0
    grouped = window.groupby("symbol")
    mean = grouped["margin"].mean()
    std = grouped["margin"].std(ddof=0)
    out = pd.DataFrame(
        {
            "fcf_positive_share": grouped["positive"].mean(),
            "fcf_margin_cv": (std / mean.abs().where(mean.abs() > 1e-9)),
        }
    ).reset_index()
    return out
