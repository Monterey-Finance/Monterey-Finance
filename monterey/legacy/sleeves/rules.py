"""Frozen live-rule thresholds from papers 01, 02, 04, 05, and 06.

Override any field for a new hypothesis. Defaults match the white papers.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace


SHARE_CLASS_MAP = {"GOOGL": "GOOG", "FOX": "FOXA", "NWS": "NWSA"}

BENCHMARKS = {
    "S&P 500": "SPY",
    "Halal (SPUS)": "SPUS",
}

TECH_SECTORS = {
    "Technology",
    "Information Technology",
    "Communication Services",
}

CLEAN_ENERGY_KEYWORDS = (
    "solar",
    "wind",
    "renewable",
    "clean energy",
    "photovoltaic",
    "hydrogen",
    "fuel cell",
    "battery",
    "electric vehicle",
    "ev battery",
    "energy storage",
)

CLEAN_ENERGY_EXTRA = (
    "ENPH",
    "FSLR",
    "SEDG",
    "RUN",
    "NEE",
    "CEG",
    "VST",
    "GEV",
    "BE",
    "PLUG",
    "TSLA",
    "STEM",
    "SHLS",
    "ARRY",
    "NOVA",
    "CWEN",
    "AES",
    "ORA",
    "HASI",
)

FOCUS_BUCKETS = ("SaaS", "Healthcare", "MedTech")


@dataclass
class AaoifiRules:
    debt_threshold: float = 0.30
    cash_threshold: float = 0.30
    receivables_threshold: float = 0.70


@dataclass
class FcfQualityRules:
    """Paper 01 — top half of Halal names by FCF / sales, cap-weighted, monthly."""

    keep_quantile: float = 0.50
    min_holdings: int = 20
    drop_high_vol_quantile: float | None = None
    vol_lookback: int = 252
    paper_window: tuple[str, str] = ("2023-01-03", "2024-12-30")


@dataclass
class RoicRules:
    """Paper 02 — ROIC > 15% then top half by reinvestment, cap-weighted, monthly."""

    roic_min: float = 0.15
    roic_max: float = 5.0
    keep_quantile: float = 0.50
    min_holdings: int = 20
    capital_light_only: bool = False
    paper_window: tuple[str, str] = ("2022-10-31", "2024-12-30")


@dataclass
class DualMomentumRules:
    """Paper 04 — 12–1 relative strength top quintile; cash when SPY < 200-day SMA."""

    keep_quantile: float = 0.20
    min_holdings: int = 15
    mom_lookback: int = 252
    mom_skip: int = 21
    sma_window: int = 200
    regime_ticker: str = "SPY"
    apply_sma: bool = True
    paper_window: tuple[str, str] = ("2019-12-19", "2024-12-30")


@dataclass
class HighBetaRules:
    """Paper 05 — top-quintile trailing beta in Halal tech / clean energy."""

    keep_quantile: float = 0.20
    min_holdings: int = 8
    beta_window: int = 252
    market_ticker: str = "SPY"
    restrict_tech: bool = True
    equal_weight_universe: bool = False
    paper_window: tuple[str, str] = ("2020-01-31", "2025-12-30")


@dataclass
class SueRules:
    """Paper 06 — robust SUE > 2σ, t+1 entry, 21-day equal-weight hold."""

    sue_threshold: float = 2.0
    hold_trading_days: int = 21
    min_holdings: int = 1
    min_prior_errors: int = 6
    equal_weight: bool = True
    apply_halal: bool = True
    paper_window: tuple[str, str] = ("2020-01-31", "2025-12-30")


@dataclass
class BookRules:
    """Defaults for papers 07–09 (blend, caps, whole-book throttle)."""

    sleeve_weights: dict[str, float] = field(
        default_factory=lambda: {
            "fcf_quality": 0.40,
            "roic": 0.40,
            "sue": 0.20,
            "dual_momentum": 0.0,
            "high_beta": 0.0,
        }
    )
    name_cap: float | None = 0.08
    sector_cap: float | None = None
    throttle: str | None = "spy_sma"
    collapse_share_classes: bool = True
    cost_bps: float = 10.0
    risk_free_rate: float = 0.02
    rebalance_freq: str = "ME"
    # Paper 10: what to do when a held name fails AAOIFI between rebalances.
    # month_end = status quo (drop at the next scheduled screen).
    # same_day = drop on the first session the fail is known.
    # next_open = drop on the session after that.
    breach_exit: str = "month_end"
    breach_monitor: str = "filings"  # filings | daily
    # Paper 11: when impure dividend cash leaves the investor path.
    # off = keep it (gross backtest). ex_date = donate on the ex-session.
    # quarter_end / year_end = let it ride, then write one cheque.
    purify_schedule: str = "off"


@dataclass
class FrozenRules:
    """One object a new paper can load, copy, and tweak."""

    aaoifi: AaoifiRules = field(default_factory=AaoifiRules)
    fcf: FcfQualityRules = field(default_factory=FcfQualityRules)
    roic: RoicRules = field(default_factory=RoicRules)
    dual_momentum: DualMomentumRules = field(default_factory=DualMomentumRules)
    high_beta: HighBetaRules = field(default_factory=HighBetaRules)
    sue: SueRules = field(default_factory=SueRules)
    book: BookRules = field(default_factory=BookRules)

    def copy(self) -> "FrozenRules":
        return deepcopy(self)

    def with_fcf(self, **kwargs) -> "FrozenRules":
        out = self.copy()
        out.fcf = replace(out.fcf, **kwargs)
        return out

    def with_roic(self, **kwargs) -> "FrozenRules":
        out = self.copy()
        out.roic = replace(out.roic, **kwargs)
        return out

    def with_dual_momentum(self, **kwargs) -> "FrozenRules":
        out = self.copy()
        out.dual_momentum = replace(out.dual_momentum, **kwargs)
        return out

    def with_high_beta(self, **kwargs) -> "FrozenRules":
        out = self.copy()
        out.high_beta = replace(out.high_beta, **kwargs)
        return out

    def with_sue(self, **kwargs) -> "FrozenRules":
        out = self.copy()
        out.sue = replace(out.sue, **kwargs)
        return out

    def with_book(self, **kwargs) -> "FrozenRules":
        out = self.copy()
        out.book = replace(out.book, **kwargs)
        return out


SLEEVE_IDS = (
    "fcf_quality",
    "roic",
    "dual_momentum",
    "high_beta",
    "sue",
)

SLEEVE_LABELS = {
    "fcf_quality": "Halal FCF quality",
    "roic": "Halal ROIC compounders",
    "dual_momentum": "Halal dual momentum",
    "high_beta": "High-beta low-debt tech",
    "sue": "Halal SUE > 2σ PEAD",
}
