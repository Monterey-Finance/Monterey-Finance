<div align="center">
<img width="1920" height="540" alt="Monterey" src="https://github.com/user-attachments/assets/0d458c16-9d00-4330-b31d-7f2b90d4d739" />

# Monterey Finance

Monterey Finance runs a **paper Halal equity book**. The mandate is steady growth: AAOIFI screens, a 10% name cap, a SPY 200-day cash throttle, and a NAV that comes from fills — not from a research chart. No live capital until the book is good enough to operate.

</div>

## Birds-eye view

One package, `monterey/`, is the fund. A YAML **BookSpec** names each layer (universe → screen → brain → construction → overlay → execution → accounting). **One simulator** steps every session the same way for live, replay, and notebooks. Every run writes the same parquet **ledger**. Ops, the desk, and research only read ledgers.

```text
halalquant v0.4.0     PIT S&P 500, sectors, prices, dividends, filings
        │
monterey.data         ResearchData snapshot (gitignored, hash in the manifest)
        │
BookSpec (books/*.yaml)
        │
layers                members → sector+AAOIFI screen → brain → weights/caps
                      → SMA overlay → next-open fills → dividends/costs/purify
        │
monterey.sim          one daily engine (signal at the close, fill at the next open)
        │
ledgers/<book>/<spec_hash>/
        │
        ├── ops          live/replay shadow fund
        ├── desk         Bloomberg-style TUI (ledger picker, Diagnostics, Compare)
        └── notebooks    October sprints 16–20, scored against v2 baseline
```

There is no second backtest engine. `Research/sleeves` is a shim over `monterey.legacy.sleeves` so papers 01–15 still open.

## Live book (v2 baseline)

**`fcf-sma-v2-baseline`** (hash `6ca86844209e`), $1M paper, 2020-01-02 → 2026-09-30.

| Layer | Rule |
| --- | --- |
| Universe | S&P 500, **point-in-time** (leavers included) |
| Screen | Excluded activities + AAOIFI 30 / 30 / 70; filing fails sell **next open** |
| Brain | FCF quality, top half by FCF / sales, min 20 names |
| Weights | Cap-weighted, 10% name cap, dual-class collapsed |
| Overlay | Whole NAV in cash when SPY is below its 200-day SMA |
| Execution | Signal at the close, fill at the **next open**; first session fills at close |
| Accounting | Dividends credited on the ex-date, **10 bp** charged on every fill, impure slice donated from credited cash |

Headline on that window: **+106% total, 11.4% CAGR, −24.8% max drawdown** (SPUS +212% / −31% DD). Calmar 0.46 vs SPUS 0.60. The switch cut 18 times; off-day fund return −26%, missed +45% of SPUS on switch-on days. IT is 66% of the last session. Full write-up: [`Research/diagnostics/v2-baseline.md`](Research/diagnostics/v2-baseline.md) (gitignored).

The archived v1 path (`1b-fcf-sma-v1` / `ledgers/fcf-sma-v1/`) is the old survivorship book: today’s list, no sector screen, dividends not credited, costs not charged. **Do not score new work against it.**

## How research works now

Fix the base, re-baseline, then research. A sprint varies **one spec family** against v2.

```python
from monterey.research import boot, run_book, compare
from monterey.sprints import run_sprint, score_against_baseline

rd = boot("paper-16", start="2019-12-01", end="2026-09-30")
ledgers, table = run_sprint("16", rd)   # or run_book("fcf-sma-v2-baseline", rd, overlay={"confirm_days": 2}, id="confirm-2")
table
```

`boot` loads halalquant once, freezes `data/snapshots/<hash>/`, and prints the snapshot hash for figure captions. Kill rules stay frozen in [`Research/book-construction-status.md`](Research/book-construction-status.md). Mandate metric is **Calmar / max drawdown**, not beating SPUS.

October sprints (notebooks under `Research/papers/16–20`):

| # | Question |
| --- | --- |
| 16 | Honest throttle: confirm days, hysteresis, partial off, vol target, always-on |
| 17 | Point-in-time universe vs today’s list (how much of v1 was survivorship) |
| 18 | Execution: drift band and min trade vs daily re-target |
| 19 | FCF layers: conversion, then stability, then yield |
| 20 | Sector cap and tighter name cap vs the IT-heavy book |

A winner becomes a spec proposal (`python -m ops rules propose …`) and, after audit confirm, the live v3 book.

## How the systems run

```bash
pip install -e ".[dev]"                 # pins halalquant v0.4.0

python -m monterey run fcf-sma-v2-baseline --start 2020-01-02 --end 2026-09-30
python -m monterey v2-baseline          # same run + diagnostics markdown
python -m ops run --as-of today         # one live session
python -m ops replay --start 2020-01-02 --end 2026-09-30
python -m desk                          # TUI; [ ] cycle ledgers; 6 diagnostics, 7 compare
```

Weekday GitHub Action: refresh cache → replay/catch up the live spec → commit `spec.yaml`, `nav.parquet`, `diagnostics.json` → bulk parquet to R2.

Ledger layout: `ledgers/<book_id>/<spec_hash>/` (`nav`, `positions`, `orders`, `fills`, `cashflows`, `events`, plus `spec.yaml` and `diagnostics.json`). Git keeps spec + NAV + diagnostics; the rest is R2.

## Phases

**Phase 1 (research)** — factor papers 01–15 are frozen. October 2026 is book design on the v2 engine.

**Phase 2 (shadow fund, paper)** — the loop above. Operator/investor product UIs are still planned; the desk is the operator terminal today. See [`Backend & Operations/README.md`](Backend%20%26%20Operations/README.md).

Live capital, a legal vehicle, and a marketed track record stay out of scope.

## Compliance

Banned activities and AAOIFI ratios are point-in-time. A failed 10-Q / 10-K sells at the next open. Impure dividend cash leaves NAV on the ex-date (paper ledger, not a charity wire).
