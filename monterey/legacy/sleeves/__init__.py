"""Reusable Halal sleeves for papers 07–15.

Typical notebook start:

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path("../..").resolve()))  # Research/

    from sleeves import FrozenRules, Lab

    rules = FrozenRules().with_fcf(keep_quantile=0.40).with_book(name_cap=0.05)
    lab = Lab.from_frames(metrics, prices, fcf_history=fcf_history, rules=rules)

    state = lab.evaluate("2022-06-30")
    state["dual_momentum"].triggered   # False if SPY is below the 200-day SMA
    state["fcf_quality"].holdings

    returns, log = lab.book(sleeve_weights={"fcf_quality": 0.8, "sue": 0.2}).run()
"""

from .book import SleeveBook, run_sleeve
from .costs import apply_flat_costs, trade_calendar
from .exits import apply_breach_exits, detect_breaches
from .purify import apply_purification, held_dividends
from .lab import Lab, SleeveState
from .rules import (
    SLEEVE_IDS,
    SLEEVE_LABELS,
    FrozenRules,
)
from .select import (
    SELECTORS,
    select_dual_momentum,
    select_fcf_quality,
    select_high_beta,
    select_roic,
    select_sue,
)
from .fundamentals import attach_sue, fetch_earnings_history
from .stats import calc_performance_stats, stats_table
from .triggers import sma_trigger
from .weighting import blend_sleeve_weights
from .diagnostics import (
    boundary_flags,
    cvar_weights,
    drop_near_boundary,
    mean_jaccard,
    overlap_weight,
    reweight_log_cvar,
)

__all__ = [
    "FrozenRules",
    "Lab",
    "SELECTORS",
    "SLEEVE_IDS",
    "SLEEVE_LABELS",
    "SleeveBook",
    "SleeveState",
    "apply_breach_exits",
    "apply_flat_costs",
    "apply_purification",
    "detect_breaches",
    "held_dividends",
    "run_sleeve",
    "trade_calendar",
    "blend_sleeve_weights",
    "boundary_flags",
    "cvar_weights",
    "drop_near_boundary",
    "mean_jaccard",
    "overlap_weight",
    "reweight_log_cvar",
    "calc_performance_stats",
    "attach_sue",
    "fetch_earnings_history",
    "select_dual_momentum",
    "select_fcf_quality",
    "select_high_beta",
    "select_roic",
    "select_sue",
    "sma_trigger",
    "stats_table",
]
