"""Combine sleeves into one NAV with optional SMA throttle and name caps."""

from __future__ import annotations

import warnings
from datetime import date
from typing import TYPE_CHECKING

import pandas as pd

from .backtest import holdings_to_weights, run_weight_schedule
from .exits import apply_breach_exits, detect_breaches
from .prices import spy_sma_risk_on
from .rules import FrozenRules, SLEEVE_IDS
from .triggers import rebalance_dates
from .weighting import blend_sleeve_weights, collapse_share_classes

if TYPE_CHECKING:
    from .lab import Lab


class SleeveBook:
    def __init__(
        self,
        lab: "Lab",
        sleeve_weights: dict[str, float] | None = None,
        name_cap: float | None = None,
        throttle: str | None = None,
        rules: FrozenRules | None = None,
    ) -> None:
        self.lab = lab
        self.rules = rules or lab.rules
        book = self.rules.book
        self.sleeve_weights = sleeve_weights or dict(book.sleeve_weights)
        self.name_cap = name_cap if name_cap is not None else book.name_cap
        resolved = throttle if throttle is not None else book.throttle
        if resolved is None or str(resolved).lower() in {"off", "none", ""}:
            self.throttle = None
        else:
            self.throttle = resolved

    def active_sleeves(self) -> list[str]:
        return [
            sid
            for sid, w in self.sleeve_weights.items()
            if w and w > 0 and sid in SLEEVE_IDS
        ]

    def blended_holdings(self, as_of: date | str, apply_throttle: bool = True) -> pd.DataFrame:
        as_of_d = pd.Timestamp(as_of).date()
        if apply_throttle and self.throttle == "spy_sma":
            spy = self.lab.spy_series()
            if not spy_sma_risk_on(spy, as_of_d, self.rules.dual_momentum.sma_window):
                return pd.DataFrame(columns=["symbol", "weight", "sleeve"])

        parts: dict[str, pd.Series] = {}
        for sid in self.active_sleeves():
            holds = self.lab.holdings(sid, as_of_d)
            if self.rules.book.collapse_share_classes and not holds.empty:
                holds = collapse_share_classes(holds)
                if "weight" in holds.columns:
                    holds["weight"] = holds.groupby("symbol")["weight"].transform("sum")
                    holds = holds.drop_duplicates("symbol")
                    total = float(holds["weight"].sum())
                    if total > 0:
                        holds["weight"] = holds["weight"] / total
            parts[sid] = holdings_to_weights(holds)

        blended = blend_sleeve_weights(parts, self.sleeve_weights, name_cap=self.name_cap)
        if blended.empty:
            return pd.DataFrame(columns=["symbol", "weight"])
        return (
            blended.rename("weight")
            .reset_index()
            .rename(columns={"index": "symbol"})
            .sort_values("weight", ascending=False)
        )

    def run(self, start: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Daily book returns and the rebalance log of blended weights.

        Deprecated: this path uses ``run_weight_schedule`` (same-day SMA).
        New work should use ``monterey.sim.simulate``.
        """
        warnings.warn(
            "SleeveBook.run is deprecated. Use monterey.sim.simulate for next-open execution.",
            DeprecationWarning,
            stacklevel=2,
        )
        dates = set(rebalance_dates(self.lab.metrics))
        if (
            "sue" in self.active_sleeves()
            and self.lab.sue_events is not None
            and not self.lab.sue_events.empty
        ):
            extra = pd.to_datetime(self.lab.sue_events["announce_date"]).dt.date.tolist()
            dates |= set(extra)
        eval_dates = sorted(
            d for d in dates if start is None or pd.Timestamp(d) >= pd.Timestamp(start)
        )

        weights_by_date: dict[date, pd.Series] = {}
        log_frames: list[pd.DataFrame] = []
        for as_of in eval_dates:
            # Stock list every rebalance, even if the SMA is off. Cash is applied
            # as throttle_on below (same as paper 09). Skipping month-ends while
            # in cash would reuse a stale list when the switch turns back on.
            blended = self.blended_holdings(as_of, apply_throttle=False)
            weights_by_date[as_of] = holdings_to_weights(blended)
            log_frames.append(blended.assign(as_of=as_of))

        log = (
            pd.concat(log_frames, ignore_index=True)
            if log_frames
            else pd.DataFrame(columns=["symbol", "weight", "as_of"])
        )

        throttle_on = None
        price_index = self.lab.price_panel().index
        if self.throttle == "spy_sma":
            spy = self.lab.spy_series()
            window = self.rules.dual_momentum.sma_window
            throttle_on = pd.Series(
                [spy_sma_risk_on(spy, dt, window) for dt in price_index],
                index=pd.to_datetime(price_index),
            )

        lag = str(getattr(self.rules.book, "breach_exit", "month_end") or "month_end")
        monitor = str(getattr(self.rules.book, "breach_monitor", "filings") or "filings")
        if lag.lower() not in {"month_end", "none", "off", ""} and not log.empty:
            events = detect_breaches(
                self.lab.metrics,
                log,
                self.lab.price_panel(),
                rules=self.rules,
                monitor=monitor,
                end=self.lab.end,
                throttle_on=throttle_on,
            )
            weights_by_date = apply_breach_exits(
                weights_by_date,
                events,
                price_index,
                lag=lag,
                name_cap=self.name_cap,
            )

        returns = run_weight_schedule(
            self.lab.prices,
            weights_by_date,
            start=start or self.lab.start,
            throttle_on=throttle_on,
        )
        return returns, log


def run_sleeve(
    lab: "Lab",
    sleeve_id: str,
    start: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Standalone sleeve path (100% weight, no book throttle, no name cap)."""
    return SleeveBook(
        lab,
        sleeve_weights={sleeve_id: 1.0},
        name_cap=None,
        throttle="off",
    ).run(start=start)
