"""October research sprints 16–20. Each varies one spec family against v2 baseline."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from monterey.diagnostics import diagnose
from monterey.ledger import Ledger
from monterey.paths import LEDGERS, ROOT
from monterey.research import boot, compare, run_book
from monterey.spec import BookSpec

KILL = {
    "train": ("2020-01-02", "2022-12-31"),
    "test": ("2023-01-01", "2024-12-31"),
}


def score_against_baseline(candidate, baseline, data) -> dict:
    """Frozen kill rules from Research/book-construction-status.md."""
    import pandas as pd

    from monterey.diagnostics.performance import stats, yearly

    def window(series: pd.Series, start: str, end: str) -> pd.Series:
        return series[(series.index >= pd.Timestamp(start)) & (series.index <= pd.Timestamp(end))]

    def year_return(series: pd.Series, year: int) -> float | None:
        table = yearly(series)
        return float(table.loc[year, "return"]) if year in table.index else None

    cand_nav = candidate.nav_series()
    base_nav = baseline.nav_series()
    spus = data.total_return("SPUS").reindex(cand_nav.index).ffill()
    train_c = stats(window(cand_nav, *KILL["train"]))
    train_s = stats(window(spus, *KILL["train"]))
    train_b = stats(window(base_nav, *KILL["train"]))
    cand = stats(cand_nav)
    base = stats(base_nav)
    reasons = []
    c2022, s2022 = year_return(cand_nav, 2022), year_return(spus, 2022)
    if c2022 is not None and s2022 is not None and (c2022 - s2022) < -0.05:
        reasons.append("2022 calendar more than 5pp worse than SPUS")
    if train_c.get("max_drawdown") is not None and train_s.get("max_drawdown") is not None:
        if train_c["max_drawdown"] < train_s["max_drawdown"]:
            reasons.append("train max drawdown worse than SPUS")
    if train_c.get("calmar") is not None and train_b.get("calmar") is not None and train_s.get("calmar") is not None:
        if train_c["calmar"] < min(train_b["calmar"], train_s["calmar"]):
            reasons.append("train Calmar below both v2 baseline and SPUS")
    c2023, b2023 = year_return(cand_nav, 2023), year_return(base_nav, 2023)
    if c2023 is not None and b2023 is not None and (c2023 - b2023) < -0.15:
        reasons.append("2023 calendar more than 15pp worse than v2 baseline")
    return {"killed": bool(reasons), "reasons": reasons, "candidate": cand, "baseline": base, "train": train_c}


def v2_baseline_ledger():
    """The scored v2 book, if a ledger already sits under ``ledgers/``."""
    spec = BookSpec.load("fcf-sma-v2-baseline")
    path = LEDGERS / spec.id / spec.hash()
    if (path / "nav.parquet").exists():
        return Ledger.read(path)
    return None


def v2_snapshot_hash() -> str | None:
    ledger = v2_baseline_ledger()
    if ledger is None:
        return None
    return ledger.manifest.get("data_snapshot") or (ledger.diagnostics() or {}).get("data_snapshot")


def month_end_sessions(rd, start, end) -> pd.DatetimeIndex:
    days = rd.sessions_between(start, end)
    if days.empty:
        return days
    return pd.DatetimeIndex(pd.Series(days, index=days).groupby(days.to_period("M")).max())


def universe_survivorship(rd, start=None, end=None) -> pd.DataFrame:
    """Month-end PIT members vs the frozen end-date list.

    ``joiners`` are on today's list but were not in the index that month.
    ``leavers`` were in the index that month but are gone from today's list.
    """
    start = start or rd.start
    end = end or rd.end
    rows = []
    for day in month_end_sessions(rd, start, end):
        pit = set(rd.members(day, pit=True))
        current = set(rd.members(day, pit=False))
        rows.append(
            {
                "date": day,
                "n_pit": len(pit),
                "n_current": len(current),
                "joiners": len(current - pit),
                "leavers": len(pit - current),
            }
        )
    return pd.DataFrame(rows)


def survivorship_in_book(ledger, rd) -> pd.DataFrame:
    """Held names that the other universe rule would not have allowed that day."""
    pos = ledger.positions
    if pos is None or pos.empty:
        return pd.DataFrame(columns=["date", "symbol", "weight", "kind"])
    held = pos[pd.to_numeric(pos["shares"], errors="coerce").fillna(0) > 0].copy()
    if held.empty:
        return pd.DataFrame(columns=["date", "symbol", "weight", "kind"])
    held["date"] = pd.to_datetime(held["date"]).dt.normalize()
    held["symbol"] = held["symbol"].astype(str)
    dates = held["date"].drop_duplicates()
    pit_by = {day: set(rd.members(day, pit=True)) for day in dates}
    current_by = {day: set(rd.members(day, pit=False)) for day in dates}
    rows = []
    for row in held.itertuples(index=False):
        day = row.date
        symbol = str(row.symbol)
        in_pit = symbol in pit_by[day]
        in_current = symbol in current_by[day]
        if in_pit == in_current:
            continue
        weight = float(row.weight) if pd.notna(row.weight) else 0.0
        kind = "joiner" if in_current and not in_pit else "leaver"
        rows.append({"date": day, "symbol": symbol, "weight": weight, "kind": kind})
    return pd.DataFrame(rows, columns=["date", "symbol", "weight", "kind"])


def paper_16(rd, baseline):
    """Honest regime throttle: confirmation, hysteresis, partial, vol target, always on."""
    variants = [
        ("always-on", {"overlay": {"kind": "none"}}),
        ("confirm-2", {"overlay": {"confirm_days": 2}}),
        ("confirm-5", {"overlay": {"confirm_days": 5}}),
        ("band-2pct", {"overlay": {"band": 0.02}}),
        ("partial-50", {"overlay": {"off_exposure": 0.5}}),
        ("vol-12", {"overlay": {"vol_target": 0.12}}),
    ]
    ledgers = [baseline]
    for name, changes in variants:
        ledgers.append(run_book("fcf-sma-v2-baseline", rd, paper="16-honest-throttle", id=name, **changes))
        diagnose(ledgers[-1], rd)
    return ledgers


def paper_17(rd, baseline):
    """Point-in-time universe vs today's list (survivorship)."""
    current = run_book("fcf-sma-v2-baseline", rd, paper="17-pit-universe", id="current-list", universe={"pit": False})
    diagnose(current, rd)
    census = universe_survivorship(rd)
    ghosts = survivorship_in_book(current, rd)
    leavers = survivorship_in_book(baseline, rd)
    if not census.empty:
        print(
            "universe census (month-end mean): "
            f"PIT {census['n_pit'].mean():.0f} vs current {census['n_current'].mean():.0f}; "
            f"joiners {census['joiners'].mean():.0f}, leavers {census['leavers'].mean():.0f}"
        )
    if not ghosts.empty:
        print(
            "current-list book held "
            f"{ghosts.loc[ghosts['kind'] == 'joiner', 'symbol'].nunique()} joiner names "
            f"that were not in the index that day"
        )
    if not leavers.empty:
        print(
            "PIT book held "
            f"{leavers.loc[leavers['kind'] == 'leaver', 'symbol'].nunique()} leaver names "
            f"missing from today's list"
        )
    return [baseline, current]


def paper_18(rd, baseline):
    """Execution policy: drift band and min trade vs daily re-target."""
    variants = [
        ("on-signal", {"execution": {"rebalance": "on_signal"}}),
        ("drift-1pct", {"execution": {"drift_band": 0.01}}),
        ("min-2500", {"execution": {"min_trade": 2500.0}}),
        ("drift-1pct-min-2500", {"execution": {"drift_band": 0.01, "min_trade": 2500.0}}),
    ]
    ledgers = [baseline]
    for name, changes in variants:
        ledgers.append(run_book("fcf-sma-v2-baseline", rd, paper="18-execution", id=name, **changes))
        diagnose(ledgers[-1], rd)
    return ledgers


def paper_19(rd, baseline):
    """FCF layers: conversion, stability, yield on top of margin."""
    variants = [
        ("conversion", {"signal": {"brain": "fcf_layers", "params": {"conversion_min": 0.5, "min_holdings": 20}}}),
        ("stability", {"signal": {"brain": "fcf_layers", "params": {"stability_min_positive": 0.75, "min_holdings": 20}}}),
        ("yield-drop", {"signal": {"brain": "fcf_layers", "params": {"yield_drop_quantile": 0.2, "min_holdings": 20}}}),
        ("all-layers", {"signal": {"brain": "fcf_layers", "params": {"conversion_min": 0.5, "stability_min_positive": 0.75, "yield_drop_quantile": 0.2, "min_holdings": 20}}}),
    ]
    ledgers = [baseline]
    for name, changes in variants:
        ledgers.append(run_book("fcf-sma-v2-baseline", rd, paper="19-fcf-layers", id=name, **changes))
        diagnose(ledgers[-1], rd)
    return ledgers


def paper_20(rd, baseline):
    """Concentration and sector lid against the IT-heavy book."""
    variants = [
        ("sector-40", {"construction": {"sector_cap": 0.40}}),
        ("sector-50", {"construction": {"sector_cap": 0.50}}),
        ("name-8", {"construction": {"name_cap": 0.08}}),
        ("sector-40-name-8", {"construction": {"sector_cap": 0.40, "name_cap": 0.08}}),
    ]
    ledgers = [baseline]
    for name, changes in variants:
        ledgers.append(run_book("fcf-sma-v2-baseline", rd, paper="20-concentration", id=name, **changes))
        diagnose(ledgers[-1], rd)
    return ledgers


PAPERS = {
    "16": ("16-honest-throttle", paper_16),
    "17": ("17-pit-universe", paper_17),
    "18": ("18-execution", paper_18),
    "19": ("19-fcf-layers", paper_19),
    "20": ("20-concentration", paper_20),
}


def run_sprint(number: str, rd=None, baseline=None):
    name, fn = PAPERS[str(number)]
    if rd is None:
        rd = boot(name, snapshot=v2_snapshot_hash())
    if baseline is None:
        baseline = v2_baseline_ledger()
        if baseline is None:
            baseline = run_book("fcf-sma-v2-baseline", rd, paper=name, id="v2-baseline")
            diagnose(baseline, rd)
    ledgers = fn(rd, baseline)
    table = compare(ledgers, data=rd)
    print(table.to_string())
    return ledgers, table


def notebook_source(number: str) -> str:
    name, _ = PAPERS[str(number)]
    titles = {
        "16": "Honest regime throttle",
        "17": "Point-in-time universe effect",
        "18": "Execution policy",
        "19": "FCF layers",
        "20": "Concentration and sector lid",
    }
    return f'''# Paper {number}: {titles[str(number)]}

Scored against **v2 baseline**. Kill rules are frozen in `Research/book-construction-status.md`.

```python
from monterey.research import boot, compare
from monterey.sprints import run_sprint, v2_snapshot_hash

rd = boot("paper-{name}", snapshot=v2_snapshot_hash())
ledgers, table = run_sprint("{number}", rd)
table
```
''' if str(number) == "17" else f'''# Paper {number}: {titles[str(number)]}

Scored against **v2 baseline**. Kill rules are frozen in `Research/book-construction-status.md`.

```python
from monterey.research import boot, compare
from monterey.sprints import run_sprint

rd = boot("paper-{name}", start="2019-12-01", end="2026-09-30")
ledgers, table = run_sprint("{number}", rd)
table
```
'''


def _code_cell(source: list[str]) -> dict:
    return {"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [], "source": source}


def _notebook_cells(number: str, info: dict, md: list[str]) -> list[dict]:
    if number == "17":
        return [
            {"cell_type": "markdown", "metadata": {}, "source": md},
            _code_cell(
                [
                    "from pathlib import Path\n",
                    "\n",
                    "from monterey.diagnostics.performance import yearly\n",
                    "from monterey.research import boot, compare\n",
                    "from monterey.sprints import (\n",
                    "    run_sprint,\n",
                    "    score_against_baseline,\n",
                    "    survivorship_in_book,\n",
                    "    universe_survivorship,\n",
                    "    v2_snapshot_hash,\n",
                    ")\n",
                    "\n",
                    'rd = boot("paper-17-pit-universe", snapshot=v2_snapshot_hash())\n',
                    'print("snapshot", rd.manifest.get("hash"))\n',
                    "census = universe_survivorship(rd)\n",
                    'print(census.agg({"n_pit": "mean", "n_current": "mean", "joiners": "mean", "leavers": "mean"}))\n',
                    "census.tail()\n",
                ]
            ),
            _code_cell(
                [
                    'ledgers, table = run_sprint("17", rd)\n',
                    "table\n",
                ]
            ),
            _code_cell(
                [
                    "baseline, current = ledgers\n",
                    "ghosts = survivorship_in_book(current, rd)\n",
                    "leavers = survivorship_in_book(baseline, rd)\n",
                    'joiners = ghosts[ghosts["kind"] == "joiner"] if not ghosts.empty else ghosts\n',
                    'gone = leavers[leavers["kind"] == "leaver"] if not leavers.empty else leavers\n',
                    'print("current-list names held before they joined the index")\n',
                    'print(joiners.groupby("symbol")["weight"].agg(["count", "mean", "max"]).sort_values("max", ascending=False).head(20) if not joiners.empty else joiners)\n',
                    'print("PIT names held after they left today\'s list")\n',
                    'print(gone.groupby("symbol")["weight"].agg(["count", "mean", "max"]).sort_values("max", ascending=False).head(20) if not gone.empty else gone)\n',
                ]
            ),
            _code_cell(
                [
                    "import matplotlib.pyplot as plt\n",
                    "\n",
                    "figures = Path(\"figures\")\n",
                    "figures.mkdir(exist_ok=True)\n",
                    "fig, axes = plt.subplots(2, 1, figsize=(10, 8))\n",
                    'axes[0].plot(census["date"], census["n_pit"], label="PIT members")\n',
                    'axes[0].plot(census["date"], census["n_current"], label="today\'s list")\n',
                    'axes[0].set_title("S&P 500 membership: point-in-time vs end-date list")\n',
                    "axes[0].legend()\n",
                    "for book in ledgers:\n",
                    "    nav = book.nav_series()\n",
                    "    axes[1].plot(nav.index, nav / nav.iloc[0], label=book.spec.id)\n",
                    'spus = rd.total_return("SPUS").reindex(ledgers[0].nav_series().index).ffill()\n',
                    "axes[1].plot(spus.index, spus / spus.iloc[0], label=\"SPUS\", alpha=0.7)\n",
                    'axes[1].set_title("NAV, start = 1")\n',
                    "axes[1].legend()\n",
                    "fig.tight_layout()\n",
                    'fig.savefig(figures / "pit-vs-current.png")\n',
                    "plt.close(fig)\n",
                    'print("wrote", figures / "pit-vs-current.png")\n',
                    'print(yearly(ledgers[0].nav_series()).join(yearly(ledgers[1].nav_series()), lsuffix="_pit", rsuffix="_current"))\n',
                ]
            ),
            _code_cell(
                [
                    "verdict = score_against_baseline(current, baseline, rd)\n",
                    'print(current.spec.id, "KILLED" if verdict["killed"] else "looks fine on kill bars", "; ".join(verdict["reasons"]) or "pass")\n',
                    'print("Architecture: keep universe.pit=true. current-list is survivorship, not a live rule.")\n',
                ]
            ),
        ]
    return [
        {"cell_type": "markdown", "metadata": {}, "source": md},
        _code_cell(
            [
                "from monterey.research import boot, compare\n",
                "from monterey.sprints import run_sprint, score_against_baseline\n",
                "\n",
                f'rd = boot("paper-{info["folder"]}", start="2019-12-01", end="2026-09-30")\n',
                'print("snapshot", rd.manifest.get("hash"))\n',
            ]
        ),
        _code_cell(
            [
                f'ledgers, table = run_sprint("{number}", rd)\n',
                "table\n",
            ]
        ),
        _code_cell(
            [
                "baseline, *rest = ledgers\n",
                "for book in rest:\n",
                "    verdict = score_against_baseline(book, baseline, rd)\n",
                '    print(book.spec.id, "KILLED" if verdict["killed"] else "keep", "; ".join(verdict["reasons"]) or "pass")\n',
            ]
        ),
    ]


def write_notebooks(root: Path | None = None) -> list[Path]:
    import json

    root = root or (ROOT / "Research" / "papers")
    written = []
    briefs = {
        "16": {
            "folder": "16-honest-throttle",
            "title": "Honest regime throttle",
            "ask": "Compare confirmation days, hysteresis bands, partial throttles, and a volatility target against always invested. The v2 baseline switch is still same-close, next-open, no confirmation.",
            "variants": "always-on, confirm-2, confirm-5, band-2pct, partial-50, vol-12",
        },
        "17": {
            "folder": "17-pit-universe",
            "title": "Point-in-time universe effect",
            "ask": "Measure how much of the v1 path came from survivorship (today's S&P 500 list) versus the point-in-time members in v2 baseline. Current-list is the leak, not a live candidate — keep PIT even if it looks better.",
            "variants": "v2-baseline (PIT) vs current-list (pit=false)",
        },
        "18": {
            "folder": "18-execution",
            "title": "Execution policy",
            "ask": "Compare a drift band and a minimum trade size against daily re-targeting. Score turnover, cost, and tracking versus v2 baseline.",
            "variants": "on-signal, drift-1pct, min-2500, drift-1pct-min-2500",
        },
        "19": {
            "folder": "19-fcf-layers",
            "title": "FCF layers",
            "ask": "Stack conversion (FCF / EBITDA), stability (positive-FCF share), then FCF yield on top of the margin screen. Each layer is the `fcf_layers` brain.",
            "variants": "conversion, stability, yield-drop, all-layers",
        },
        "20": {
            "folder": "20-concentration",
            "title": "Concentration and sector lid",
            "ask": "Put a sector cap and a tighter name cap on the IT-heavy FCF book. v2 baseline has no sector cap and a 10% name cap.",
            "variants": "sector-40, sector-50, name-8, sector-40-name-8",
        },
    }
    for number, info in briefs.items():
        dest = root / info["folder"]
        dest.mkdir(parents=True, exist_ok=True)
        md = [
            f"# Paper {number}: {info['title']}\n",
            "\n",
            f"{info['ask']}\n",
            "\n",
            "Scored against **v2 baseline**. Kill rules are frozen in `Research/book-construction-status.md`:\n",
            "\n",
            "- Train 2022 calendar more than 5pp worse than SPUS\n",
            "- Train max drawdown worse than SPUS\n",
            "- Train Calmar below both v2 baseline and SPUS\n",
            "- Test 2023 calendar more than 15pp worse than v2 baseline\n",
            "\n",
            f"**Variants.** {info['variants']}.\n",
        ]
        nb = {
            "nbformat": 4,
            "nbformat_minor": 5,
            "metadata": {
                "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                "language_info": {"name": "python", "pygments_lexer": "ipython3"},
            },
            "cells": _notebook_cells(number, info, md),
        }
        path = dest / "code.ipynb"
        path.write_text(json.dumps(nb, indent=1) + "\n", encoding="utf-8")
        if number != "17":
            (dest / "README.md").write_text(notebook_source(number), encoding="utf-8")
        written.append(path)
    return written
