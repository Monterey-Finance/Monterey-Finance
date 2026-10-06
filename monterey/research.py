"""Notebook start for every research sprint.

    from monterey.research import boot, run_book, compare
    rd = boot("paper-16", start="2019-12-01", end="2026-09-30")
    base = run_book("fcf-sma-v2-baseline", rd, paper="paper-16")

One call replaces the old setup cell (pip install, sys.path edits, reading a
frozen paper-07 cache). The snapshot hash goes into every figure caption.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from monterey.data import ResearchData, load_research_data, load_snapshot
from monterey.paths import LEDGERS, SNAPSHOTS
from monterey.spec import BookSpec

SPRINT_WINDOW = ("2020-01-02", "2026-09-30")


def boot(
    paper: str,
    start: str = "2019-12-01",
    end: str = "2026-09-30",
    *,
    snapshot: str | None = None,
    refresh: bool = False,
    figures: bool = True,
    quiet: bool = False,
) -> ResearchData:
    """Load the frozen research data for ``paper`` and set notebook defaults.

    ``snapshot`` is a hash under ``data/snapshots/`` (the v2 run's
    ``data_snapshot``). That skips the cache and uses the same facts the live
    book already replayed.
    """
    pd.set_option("display.width", 160)
    pd.set_option("display.max_columns", 40)
    pd.set_option("display.float_format", lambda v: f"{v:,.4f}")
    try:
        import matplotlib

        matplotlib.rcParams.update({"figure.figsize": (10, 4.5), "axes.grid": True, "grid.alpha": 0.3, "figure.dpi": 110})
    except ImportError:
        pass
    if figures:
        Path("figures").mkdir(exist_ok=True)
    if snapshot:
        folder = Path(snapshot)
        if not folder.exists():
            folder = SNAPSHOTS / snapshot
        data = load_snapshot(folder)
    else:
        data = load_research_data(start, end, refresh=refresh, progress=not quiet)
    data.manifest["paper"] = paper
    if not quiet:
        print(data.describe().to_string(index=False))
    return data


def run_book(
    spec: BookSpec | str,
    data: ResearchData,
    *,
    paper: str | None = None,
    start: str = SPRINT_WINDOW[0],
    end: str = SPRINT_WINDOW[1],
    write: bool = True,
    **changes,
):
    """
    Simulate one book. ``changes`` are spec section edits, e.g.
    ``run_book("fcf-sma-v2-baseline", rd, overlay={"confirm_days": 2}, id="confirm-2")``.

    Experiment ledgers go under ``ledgers/experiments/<paper>/<book id>/<hash>/``.
    """
    from monterey.sim.engine import simulate

    book = spec if isinstance(spec, BookSpec) else BookSpec.load(spec)
    new_id = changes.pop("id", None)
    label = changes.pop("label", None)
    if changes or new_id or label:
        book = book.replace(id=new_id, label=label, **changes)
    root = None
    if write:
        root = LEDGERS / "experiments" / paper if paper else LEDGERS
    return simulate(book, data, start=start, end=end, root=root, mode="experiment" if paper else "replay")


def compare(ledgers, data: ResearchData | None = None, benchmarks: bool = True) -> pd.DataFrame:
    """One row per ledger: CAGR, max drawdown, Calmar, Sharpe, turnover, costs, dividends."""
    from monterey.diagnostics.performance import scorecard

    rows = [scorecard(ledger) for ledger in ledgers]
    if benchmarks and data is not None and ledgers:
        nav = ledgers[0].nav
        dates = pd.to_datetime(nav["date"]) if not nav.empty else pd.DatetimeIndex([])
        for symbol in ("SPUS", "SPY"):
            series = data.total_return(symbol)
            aligned = series.reindex(dates).ffill()
            aligned.index = dates
            rows.append(scorecard(aligned, label=f"{symbol} (total return)"))
    return pd.DataFrame(rows).set_index("book")


def run_v2_baseline(progress: bool = True):
    """Simulate the gap-fixed book and write Research/diagnostics/v2-baseline.md."""
    from monterey.diagnostics import diagnose, write_audit
    from monterey.paths import ROOT
    from monterey.sim.engine import simulate

    spec = BookSpec.load("fcf-sma-v2-baseline")
    data = load_research_data("2020-01-02", "2026-09-30", progress=progress)
    ledger = simulate(spec, data, "2020-01-02", "2026-09-30", root=LEDGERS, mode="replay", progress=progress)
    diag = diagnose(ledger, data)
    write_audit(
        diag,
        ROOT / "Research" / "diagnostics" / "v2-baseline.md",
        title="v2 baseline — 2020-01-02 to 2026-09-30",
    )
    return ledger, diag
