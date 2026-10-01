"""When each sleeve is allowed to fire.

Monthly sleeves fire on the latest metrics `as_of` on or before the evaluation date.
The SMA throttle is a book-level (or dual-momentum) on/off switch.
SUE fires on event-time membership, not the month-end calendar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from .prices import spy_sma_risk_on
from .rules import FrozenRules


@dataclass
class TriggerState:
    name: str
    as_of: date
    on: bool
    reason: str


def rebalance_dates(panel: pd.DataFrame) -> list[date]:
    if panel is None or panel.empty or "as_of" not in panel.columns:
        return []
    return sorted(pd.to_datetime(panel["as_of"].dropna().unique()).date)


def last_rebalance_on_or_before(dates: list[date], as_of: date | str) -> date | None:
    as_of_d = pd.Timestamp(as_of).date()
    prior = [d for d in dates if d <= as_of_d]
    return prior[-1] if prior else None


def monthly_trigger(panel: pd.DataFrame, as_of: date | str) -> TriggerState:
    as_of_d = pd.Timestamp(as_of).date()
    dates = rebalance_dates(panel)
    last = last_rebalance_on_or_before(dates, as_of_d)
    if last is None:
        return TriggerState("monthly_rebalance", as_of_d, False, "no metrics snapshot yet")
    if last == as_of_d:
        return TriggerState("monthly_rebalance", as_of_d, True, "rebalance date")
    return TriggerState(
        "monthly_rebalance",
        as_of_d,
        True,
        f"hold last rebalance {last.isoformat()}",
    )


def sma_trigger(
    spy_series: pd.Series,
    as_of: date | str,
    rules: FrozenRules | None = None,
) -> TriggerState:
    rules = rules or FrozenRules()
    as_of_d = pd.Timestamp(as_of).date()
    window = rules.dual_momentum.sma_window
    if spy_series is None or spy_series.empty:
        return TriggerState("spy_sma", as_of_d, False, "no SPY series")
    on = spy_sma_risk_on(spy_series, as_of_d, sma_window=window)
    reason = (
        f"SPY above {window}-day SMA"
        if on
        else f"SPY at or below {window}-day SMA — cash"
    )
    return TriggerState("spy_sma", as_of_d, on, reason)


def sue_trigger(holdings: pd.DataFrame, as_of: date | str) -> TriggerState:
    as_of_d = pd.Timestamp(as_of).date()
    n = 0 if holdings is None or holdings.empty else len(holdings)
    if n == 0:
        return TriggerState("sue_event", as_of_d, False, "no qualifying prints in hold window")
    return TriggerState("sue_event", as_of_d, True, f"{n} names in 21-day PEAD window")
