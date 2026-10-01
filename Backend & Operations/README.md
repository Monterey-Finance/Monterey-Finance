<div align="center">
<img width="2477" height="449" alt="Banner 5" src="https://github.com/user-attachments/assets/52026cf0-28ac-45b8-b3b0-3846e583a121" />

# Backend & Operations — Shadow Fund

**Goal:** A paper Halal equity book that marks NAV from fills every session, with Shariah screens and costs visible — no investor capital.

<p>
  <img src="https://img.shields.io/badge/Mandate-Steady%20growth-0A66C2" alt="Steady growth">
  <img src="https://img.shields.io/badge/Phase-2%20Shadow%20fund-f97316" alt="Phase 2 Shadow fund">
  <img src="https://img.shields.io/badge/Capital-Paper-64748b" alt="Paper capital">
  <img src="https://img.shields.io/badge/Book-fcf--sma--v2--baseline-22c55e" alt="v2 baseline">
  <img src="https://img.shields.io/badge/Engine-monterey.sim-0A66C2" alt="monterey.sim">
</p>

</div>

The shadow fund is **not** a registered vehicle. There is no custodian, no LP subscriptions, and no charity wire. This folder is the operator contract: how a session is run, what is official, and what the desk is allowed to show.

Strategy lives in a YAML **BookSpec**. Market facts live in **halalquant**. Execution and NAV live in **`monterey/`**. `ops/` is the weekday loop around that engine. `desk/` only reads ledgers.

---

## How the fund is wired

Live, replay, and notebooks share one path. A signal decided at close `t` never earns day `t`.

```text
halalquant v0.4.0
    PIT membership, sectors, open/close/adj, dividends, 10-Q/10-K events
        │
monterey.data          freeze a snapshot under data/snapshots/<hash>/
        │
books/<id>.yaml        BookSpec (hash stamped on every ledger)
        │
layers                 universe → screen (sector + AAOIFI) → brain
                       → construction (cap, name/sector lids)
                       → overlay (SPY 200-day) → execution → accounting
        │
monterey.sim           daily engine: ex-date dividends, next-open fills
                       (sells first, whole shares, cash-limited, 10 bp),
                       breach exits, close mark
        │
ledgers/<book>/<hash>/
    spec.yaml  manifest.json  nav.parquet  diagnostics.json
    positions  orders  fills  cashflows  events     ← R2, not git
        │
        ├── python -m ops run / replay / schedule
        ├── python -m desk          [ ] ledger picker; tabs 6–7
        └── monterey.research.boot  notebooks
```

`Research/sleeves` is a compatibility shim. Do not add a second backtest.

### Session semantics

1. Holders at the prior close receive the dividend if ex-date is today; the impure slice leaves cash.
2. Orders created at yesterday’s close fill at today’s **open**.
3. At the close: SMA exposure, monthly FCF rebuild on a new metrics stamp, filing breaches, target weights.
4. New orders wait for tomorrow’s open. The **first** session fills at that day’s close so a NAV exists.
5. A name with no price for a week is cashed at last close.

---

## Live book

**Spec:** [`books/fcf-sma-v2-baseline.yaml`](../books/fcf-sma-v2-baseline.yaml) (`LIVE_BOOK` in `ops/live_rules.py`).

| | |
| --- | --- |
| Universe | S&P 500, point-in-time |
| Screen | Excluded activities + debt/cash/recv 30/30/70 |
| Brain | `fcf_quality`, keep quantile 0.5, min 20 |
| Construction | Cap weight, 10% name cap, no sector cap |
| Overlay | SPY 200-day SMA → 0% invested when off |
| Execution | `daily_to_target`, min trade $100, next-open |
| Accounting | $1M start, dividends on, 10 bp, purify on ex-date |

ROIC, SUE, dual-momentum, and high-beta stay out of the traded book (`FORBIDDEN_SLEEVES`). Change a live field only through `ops rules propose` / `confirm` (audit log + overlay JSON). That bumps the spec hash; a new ledger folder starts.

**Archived v1** (`ledgers/fcf-sma-v1/`): today’s 503 names, no sector screen, no dividend credit, no costs. Frozen. New research is judged against **v2**, not v1.

Baseline window 2020-01-02 → 2026-09-30: +106% total, 11.4% CAGR, −24.8% max DD. Write-up in `Research/diagnostics/v2-baseline.md`.

---

## Commands

```bash
pip install -e ".[dev]"

python -m ops run --as-of today              # refresh + one session
python -m ops run --as-of today --skip-refresh
python -m ops run --as-of today --targets-only   # old SleeveBook path, no trade
python -m ops replay --start 2020-01-02 --end 2026-09-30
python -m ops health
python -m ops rules propose --actor ada --reason "…" --name-cap 0.08
python -m ops rules confirm --id <proposal> --actor ada

python -m monterey run fcf-sma-v2-baseline --start 2020-01-02 --end 2026-09-30
python -m monterey v2-baseline
python -m desk
```

`ops run` loads the live spec, steps `monterey.sim` for that date, writes the ledger, mirrors `ops/state/nav.csv` / `account.json`, and skips if the day is already marked or the account is halted.

### What is official

| Path | Role |
| --- | --- |
| `ledgers/<book>/<hash>/nav.parquet` | Official NAV |
| `ledgers/.../diagnostics.json` | Attribution, switch cost, concentration, compliance |
| `ledgers/.../spec.yaml` | Exact rules for that run |
| `ops/state/account.json` | Paper cash, shares, pending, halt |
| `ops/state/nav.csv` | Cutover mirror for older readers |
| `ops/state/rules_overlay.json` | Confirmed spec edits |

Git commits spec, `nav.parquet`, `diagnostics.json`, and the nav CSV. Positions/orders/fills/cashflows/events sync to R2. Per-day `ops/runs/<day>/` folders are no longer the production store.

Weekday Action (22:30 UTC): `pip install -e .` → cache from R2 → catch-up replay of the live book → commit the git files → upload ledgers and cache.

Offline tests: `pytest monterey/tests ops/tests desk/tests`.

---

## Desk

`python -m desk` is the operator terminal. It does not trade.

- Loads the live ledger if present, else the last `ops/state` snapshot.
- `[` / `]` cycle `ledgers/` (live v2, archived v1, experiments).
- Holdings marked at the **session close**, with a screen reason (sector / ratios).
- Rules panel comes from **that ledger’s spec**, not from live code.
- Tab 6 renders `diagnostics.json`. Tab 7 overlays two NAV paths.

Investor and operator **product** shells (Geist, white/black) are still specified in [PRD.md](PRD.md) and [DESIGN.md](DESIGN.md). They must read the same ledger. A research equity curve is never a substitute.

---

## How research feeds production

1. Notebook: `boot("paper-N")` → vary one spec section → `run_book(..., paper=…)` writes `ledgers/experiments/…`.
2. Score against **v2 baseline** with the kill rules in `Research/book-construction-status.md`.
3. Promote with `ops rules propose` (allowed keys: name cap, throttle, drift band, sector cap, confirm days, …).
4. After confirm, the next live session uses the new hash.

October sprints 16–20 (throttle, PIT effect, execution, FCF layers, concentration) are the current queue. See the root [`README.md`](../README.md).

---

## Shadow vs live fund

| This phase | Not this phase |
| --- | --- |
| Paper account, cache prices | Client capital, prime broker |
| Internal NAV from fills | Fund-admin NAV |
| Desk + paper purification ledger | KYC, charity wires, Shariah-board ops |
| Kill switch on halt / stale data | Legal vehicle, offering docs |

UX rules for a later product UI (transparency, density vs disclosure, confirm-to-trade) stay in this folder’s PRD. They do not change how the engine runs.

## Out of this folder

- Factor papers and sprint notebooks → [`Research/`](../Research/README.md)
- Screens, PIT membership, prices, filings → **halalquant**
- Spec, simulator, ledger schema, diagnostics → [`monterey/`](../monterey/)
- Live capital and marketing of a track record
