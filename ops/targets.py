"""Intended book for one session: target weights, cash flag, reason codes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from ops.live_rules import BOOK_VERSION
from ops.paths import ensure_research_on_path

ensure_research_on_path()

from sleeves.book import SleeveBook  # noqa: E402
from sleeves.lab import Lab  # noqa: E402
from sleeves.triggers import last_rebalance_on_or_before, rebalance_dates, sma_trigger  # noqa: E402

HOLDING_COLUMNS = (
    "as_of",
    "symbol",
    "target_weight",
    "invested_weight",
    "fcf_margin",
    "market_cap",
    "debt_ratio",
    "cash_ratio",
    "receivables_ratio",
    "name_capped",
)


@dataclass
class IntendedBook:
    as_of: date
    sma_on: bool
    sma_reason: str
    cash_weight: float
    name_cap: float
    book_version: str
    holdings: pd.DataFrame
    invested: pd.DataFrame

    def summary(self) -> dict[str, Any]:
        holds = self.holdings
        n = 0 if holds.empty else int((holds["target_weight"] > 0).sum())
        top = []
        if not holds.empty and n:
            top = (
                holds.sort_values("target_weight", ascending=False)
                .head(5)[["symbol", "target_weight"]]
                .to_dict("records")
            )
        return {
            "as_of": self.as_of.isoformat(),
            "book_version": self.book_version,
            "sma_on": self.sma_on,
            "sma_reason": self.sma_reason,
            "cash_weight": self.cash_weight,
            "n_holdings": n,
            "name_cap": self.name_cap,
            "top5": top,
        }


def clip_session(lab: Lab, as_of: date | str) -> date:
    """Last price date on or before as_of. Raises if SPY has no bar."""
    want = pd.Timestamp(as_of).date()
    spy = lab.spy_series()
    if spy is None or spy.empty:
        raise ValueError("No SPY prices. Refresh the cache and include SPY.")
    known = spy.loc[: pd.Timestamp(want)].dropna()
    if known.empty:
        raise ValueError(f"No SPY bar on or before {want.isoformat()}.")
    return pd.Timestamp(known.index[-1]).date()


def build_intended_book(
    lab: Lab,
    as_of: date | str,
    selection_cache: dict | None = None,
) -> IntendedBook:
    """Target weights for one session. Cash when the SPY SMA is off.

    ``selection_cache`` reuses the month's stock list. The cash switch is still
    decided from this session's prices.
    """
    rules = lab.rules
    session = clip_session(lab, as_of)
    regime = sma_trigger(lab.spy_series(), session, rules)
    snap = last_rebalance_on_or_before(rebalance_dates(lab.metrics), session)
    cached = None if selection_cache is None or snap is None else selection_cache.get(snap)
    if cached is None:
        book = SleeveBook(lab, rules=rules)
        invested = book.blended_holdings(session, apply_throttle=False)
        extras = lab.holdings("fcf_quality", session)
        name_cap = float(book.name_cap or 0.0)
        if selection_cache is not None and snap is not None:
            selection_cache[snap] = (invested, extras, name_cap)
    else:
        invested, extras, name_cap = cached

    invested_w = _weight_map(invested)
    if invested.empty or not regime.on:
        holdings = _empty_holdings(session)
        cash_weight = 1.0
    else:
        holdings = _attach_invested(invested, invested_w, extras, session, name_cap)
        cash_weight = max(0.0, 1.0 - float(holdings["target_weight"].sum()))

    invested_out = (
        _attach_invested(invested, invested_w, extras, session, name_cap)
        if not invested.empty
        else _empty_holdings(session)
    )
    if not invested_out.empty:
        invested_out["target_weight"] = invested_out["invested_weight"]

    return IntendedBook(
        as_of=session,
        sma_on=bool(regime.on),
        sma_reason=regime.reason,
        cash_weight=cash_weight if regime.on else 1.0,
        name_cap=name_cap,
        book_version=BOOK_VERSION,
        holdings=holdings,
        invested=invested_out,
    )


def _weight_map(frame: pd.DataFrame) -> dict[str, float]:
    if frame is None or frame.empty or "symbol" not in frame.columns:
        return {}
    return {
        str(row["symbol"]): float(row["weight"])
        for _, row in frame.iterrows()
        if pd.notna(row.get("weight"))
    }


def _empty_holdings(as_of: date) -> pd.DataFrame:
    return pd.DataFrame(columns=list(HOLDING_COLUMNS))


def _attach_invested(
    blended: pd.DataFrame,
    invested_w: dict[str, float],
    extras: pd.DataFrame,
    as_of: date,
    name_cap: float,
) -> pd.DataFrame:
    if blended is None or blended.empty:
        return _empty_holdings(as_of)
    extra_map = {}
    if extras is not None and not extras.empty:
        extra_map = extras.set_index("symbol").to_dict("index")
    rows = []
    for _, row in blended.iterrows():
        symbol = str(row["symbol"])
        weight = float(row.get("weight") or 0.0)
        invested = float(invested_w.get(symbol, weight))
        info = extra_map.get(symbol, extra_map.get(symbol.upper(), {}))
        rows.append(
            {
                "as_of": as_of,
                "symbol": symbol,
                "target_weight": weight,
                "invested_weight": invested,
                "fcf_margin": info.get("fcf_margin"),
                "market_cap": info.get("market_cap"),
                "debt_ratio": info.get("debt_ratio"),
                "cash_ratio": info.get("cash_ratio"),
                "receivables_ratio": info.get("receivables_ratio"),
                "name_capped": bool(name_cap and weight >= name_cap - 1e-9),
            }
        )
    out = pd.DataFrame(rows)
    return out.sort_values("target_weight", ascending=False).reset_index(drop=True)
