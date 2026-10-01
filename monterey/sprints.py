"""October research sprints 16–20. Each varies one spec family against v2 baseline."""

from __future__ import annotations

from pathlib import Path

from monterey.diagnostics import diagnose
from monterey.paths import ROOT
from monterey.research import boot, compare, run_book

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
    rd = rd or boot(name)
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
from monterey.sprints import run_sprint

rd = boot("paper-{name}", start="2019-12-01", end="2026-09-30")
ledgers, table = run_sprint("{number}", rd)
table
```
'''


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
            "ask": "Measure how much of the v1 path came from survivorship (today's S&P 500 list) versus the point-in-time members in v2 baseline.",
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
            "cells": [
                {"cell_type": "markdown", "metadata": {}, "source": md},
                {
                    "cell_type": "code",
                    "metadata": {},
                    "execution_count": None,
                    "outputs": [],
                    "source": [
                        "from monterey.research import boot, compare\n",
                        "from monterey.sprints import run_sprint, score_against_baseline\n",
                        "\n",
                        f'rd = boot("paper-{info["folder"]}", start="2019-12-01", end="2026-09-30")\n',
                        f'print("snapshot", rd.manifest.get("hash"))\n',
                    ],
                },
                {
                    "cell_type": "code",
                    "metadata": {},
                    "execution_count": None,
                    "outputs": [],
                    "source": [
                        f'ledgers, table = run_sprint("{number}", rd)\n',
                        "table\n",
                    ],
                },
                {
                    "cell_type": "code",
                    "metadata": {},
                    "execution_count": None,
                    "outputs": [],
                    "source": [
                        "baseline, *rest = ledgers\n",
                        "for book in rest:\n",
                        "    verdict = score_against_baseline(book, baseline, rd)\n",
                        '    print(book.spec.id, "KILLED" if verdict["killed"] else "keep", "; ".join(verdict["reasons"]) or "pass")\n',
                    ],
                },
            ],
        }
        path = dest / "code.ipynb"
        path.write_text(json.dumps(nb, indent=1) + "\n", encoding="utf-8")
        (dest / "README.md").write_text(notebook_source(number), encoding="utf-8")
        written.append(path)
    return written
