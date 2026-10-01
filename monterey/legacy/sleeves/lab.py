"""Lab session: load frames once, then select / trigger / blend sleeves."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from .backtest import holdings_to_weights
from .fundamentals import attach_latest_fcf, attach_latest_roic
from .prices import to_price_panel
from .rules import FrozenRules, SLEEVE_IDS, SLEEVE_LABELS
from .select import (
    select_dual_momentum,
    select_fcf_quality,
    select_high_beta,
    select_roic,
    select_sue,
)
from .triggers import TriggerState, monthly_trigger, sma_trigger, sue_trigger


@dataclass
class SleeveState:
    sleeve_id: str
    label: str
    as_of: date
    triggered: bool
    reason: str
    holdings: pd.DataFrame
    n_holdings: int
    extras: dict = field(default_factory=dict)

    def weights(self) -> pd.Series:
        return holdings_to_weights(self.holdings)


@dataclass
class Lab:
    """Reusable research session for papers 07–15.

    Pass already-fetched frames (typical after a notebook download cell), or
    call :meth:`from_halalquant` once and reuse.
    """

    rules: FrozenRules = field(default_factory=FrozenRules)
    metrics: pd.DataFrame = field(default_factory=pd.DataFrame)
    prices: pd.DataFrame = field(default_factory=pd.DataFrame)
    fcf_history: pd.DataFrame = field(default_factory=pd.DataFrame)
    roic_history: pd.DataFrame = field(default_factory=pd.DataFrame)
    sue_events: pd.DataFrame = field(default_factory=pd.DataFrame)
    start: str | None = None
    end: str | None = None
    _fcf_panel: pd.DataFrame | None = field(default=None, repr=False)
    _roic_panel: pd.DataFrame | None = field(default=None, repr=False)
    _price_panel: pd.DataFrame | None = field(default=None, repr=False)

    @classmethod
    def from_frames(
        cls,
        metrics: pd.DataFrame,
        prices: pd.DataFrame,
        *,
        rules: FrozenRules | None = None,
        fcf_history: pd.DataFrame | None = None,
        roic_history: pd.DataFrame | None = None,
        sue_events: pd.DataFrame | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> "Lab":
        return cls(
            rules=rules or FrozenRules(),
            metrics=metrics,
            prices=prices,
            fcf_history=fcf_history if fcf_history is not None else pd.DataFrame(),
            roic_history=roic_history if roic_history is not None else pd.DataFrame(),
            sue_events=sue_events if sue_events is not None else pd.DataFrame(),
            start=start,
            end=end,
        )

    @classmethod
    def from_halalquant(
        cls,
        symbols: list[str],
        start: str,
        end: str,
        *,
        rules: FrozenRules | None = None,
        freq: str = "ME",
        cache=True,
    ) -> "Lab":
        """Download AAOIFI metrics + prices. Signal histories still passed in separately."""
        import halalquant as hq

        rules = rules or FrozenRules()
        metrics = hq.get_financial_metrics(symbols, start=start, end=end, freq=freq, cache=cache)
        extras = ["SPY", "SPUS"]
        tickers = sorted(set(symbols) | set(extras))
        prices = hq.download(tickers, start=start, end=end, cache=cache)
        prices["date"] = pd.to_datetime(prices["date"])
        return cls(rules=rules, metrics=metrics, prices=prices, start=start, end=end)

    def price_panel(self) -> pd.DataFrame:
        if self._price_panel is None:
            self._price_panel = to_price_panel(self.prices)
        return self._price_panel

    def fcf_panel(self) -> pd.DataFrame:
        if self._fcf_panel is None:
            base = self.metrics.copy()
            if "fcf" not in base.columns or base["fcf"].isna().all():
                if "free_cash_flow" in base.columns:
                    base["fcf"] = pd.to_numeric(base["free_cash_flow"], errors="coerce")
            if self.fcf_history is None or self.fcf_history.empty:
                self._fcf_panel = base
            else:
                self._fcf_panel = attach_latest_fcf(base, self.fcf_history)
        return self._fcf_panel

    def roic_panel(self) -> pd.DataFrame:
        if self._roic_panel is None:
            if self.roic_history is None or self.roic_history.empty:
                self._roic_panel = self.metrics
            else:
                self._roic_panel = attach_latest_roic(self.metrics, self.roic_history)
        return self._roic_panel

    def spy_series(self) -> pd.Series:
        panel = self.price_panel()
        ticker = self.rules.dual_momentum.regime_ticker
        if ticker not in panel.columns:
            return pd.Series(dtype=float)
        return panel[ticker].dropna()

    def regime(self, as_of: date | str) -> TriggerState:
        return sma_trigger(self.spy_series(), as_of, self.rules)

    def holdings(self, sleeve_id: str, as_of: date | str) -> pd.DataFrame:
        if sleeve_id == "fcf_quality":
            return select_fcf_quality(
                self.fcf_panel(), as_of, self.rules, price_panel=self.price_panel()
            )
        if sleeve_id == "roic":
            return select_roic(self.roic_panel(), as_of, self.rules)
        if sleeve_id == "dual_momentum":
            holds = select_dual_momentum(
                self.metrics, self.price_panel(), as_of, self.rules
            )
            if self.rules.dual_momentum.apply_sma and not self.regime(as_of).on:
                return holds.iloc[0:0]
            return holds
        if sleeve_id == "high_beta":
            return select_high_beta(self.metrics, self.price_panel(), as_of, self.rules)
        if sleeve_id == "sue":
            return select_sue(
                self.metrics,
                self.sue_events,
                self.price_panel().index,
                as_of,
                self.rules,
            )
        raise KeyError(f"Unknown sleeve {sleeve_id!r}. Choose from {SLEEVE_IDS}.")

    def evaluate(self, as_of: date | str, sleeves: tuple[str, ...] | None = None) -> dict[str, SleeveState]:
        """Holdings + trigger flags for every requested sleeve on one date."""
        as_of_d = pd.Timestamp(as_of).date()
        sleeves = sleeves or SLEEVE_IDS
        regime = self.regime(as_of_d)
        monthly = monthly_trigger(self.metrics, as_of_d)
        out: dict[str, SleeveState] = {}
        for sleeve_id in sleeves:
            holds = self.holdings(sleeve_id, as_of_d)
            if sleeve_id in {"fcf_quality", "roic", "high_beta"}:
                trig = monthly
                triggered = trig.on and not holds.empty
                reason = trig.reason if triggered else (trig.reason if not trig.on else "screen too thin")
            elif sleeve_id == "dual_momentum":
                apply_sma = self.rules.dual_momentum.apply_sma
                if apply_sma and not regime.on:
                    triggered = False
                    reason = regime.reason
                    holds = holds.iloc[0:0]
                else:
                    triggered = monthly.on and not holds.empty
                    reason = regime.reason if apply_sma else monthly.reason
            else:
                sue_t = sue_trigger(holds, as_of_d)
                triggered = sue_t.on
                reason = sue_t.reason
            out[sleeve_id] = SleeveState(
                sleeve_id=sleeve_id,
                label=SLEEVE_LABELS[sleeve_id],
                as_of=as_of_d,
                triggered=triggered,
                reason=reason,
                holdings=holds,
                n_holdings=0 if holds.empty else len(holds),
                extras={"regime": regime, "monthly": monthly},
            )
        return out

    def book(self, **kwargs):
        from .book import SleeveBook

        return SleeveBook(self, **kwargs)

    def save_cache(self, path: str | Path) -> Path:
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        self.metrics.to_parquet(path / "metrics.parquet", index=False)
        self.prices.to_parquet(path / "prices.parquet", index=False)
        if not self.fcf_history.empty:
            self.fcf_history.to_parquet(path / "fcf_history.parquet", index=False)
        if not self.roic_history.empty:
            self.roic_history.to_parquet(path / "roic_history.parquet", index=False)
        if not self.sue_events.empty:
            self.sue_events.to_parquet(path / "sue_events.parquet", index=False)
        return path

    @classmethod
    def load_cache(cls, path: str | Path, rules: FrozenRules | None = None) -> "Lab":
        path = Path(path)

        def _read(name: str) -> pd.DataFrame:
            file = path / name
            return pd.read_parquet(file) if file.exists() else pd.DataFrame()

        return cls.from_frames(
            metrics=_read("metrics.parquet"),
            prices=_read("prices.parquet"),
            rules=rules,
            fcf_history=_read("fcf_history.parquet"),
            roic_history=_read("roic_history.parquet"),
            sue_events=_read("sue_events.parquet"),
        )
