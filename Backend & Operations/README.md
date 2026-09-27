<div align="center">
<img width="2477" height="449" alt="Banner 5" src="https://github.com/user-attachments/assets/52026cf0-28ac-45b8-b3b0-3846e583a121" />

# Backend & Operations — Shadow Fund

**Goal:** Stand up a paper-money Halal equity book that trades every session, marks a real NAV from fills, and makes Shariah compliance and performance visible — without taking investor capital.

<p>
  <img src="https://img.shields.io/badge/Mandate-Steady%20growth-0A66C2" alt="Steady growth">
  <img src="https://img.shields.io/badge/Phase-2%20Shadow%20fund-f97316" alt="Phase 2 Shadow fund">
  <img src="https://img.shields.io/badge/Capital-Paper%20%2F%20fake%20accounts-64748b" alt="Paper capital">
  <img src="https://img.shields.io/badge/Book-FCF%20%2B%20SMA%20cash-22c55e" alt="FCF plus SMA cash">
  <img src="https://img.shields.io/badge/Status-Planning-eab308" alt="Planning">
</p>

</div>

`Backend & Operations/` is the **Phase 2 shadow fund** for Monterey Finance. It is **not** a registered, fully operable fund. There is no live investor money, no custodian, no subscriptions/redemptions, and no public raise. Work here is a **paper account + daily jobs + operator/investor UI** that prove the Phase 1B book can run.

Strategy rules stay frozen in [`Research/`](../Research/README.md). Market data and AAOIFI/DJIM screens stay in **halalquant**. This folder owns **target weights, orders, paper brokerage, NAV, and product surfaces**.

---

## Shadow fund vs fully operable fund

| This phase (shadow) | Not this phase (live fund) |
| --- | --- |
| Paper / fake brokerage accounts | Real client capital and a prime broker / custodian |
| Internal NAV from paper fills | Fund-admin NAV, audit, and regulatory filings |
| Operator UI + a read-only investor mock | KYC, onboarding of real LPs, transfer agent |
| Purification **ledger** (amounts owed) | Real charity wires and Shariah-board sign-off ops |
| Kill switch if data or broker disagrees | Legal fund vehicle, offering docs, marketing of returns |

Every feature list below is a **shadow-fund target**. Shipping a screen does not make the product a live fund.

---

## Feature list (planned)

All items below are in scope for the **shadow fund product**. None are production investor operations until a later phase.

### A. Investor end (user interface)

Goal: radical trust, continuous Shariah proof, portfolio growth that a non-technical investor can read.

- **Onboarding and investor profiling**
  - Goal setup: slider / card choice for financial targets (wealth growth, Halal dividend yield, capital preservation)
  - Shariah customization: AAOIFI as the live book standard, optional overlay (e.g. extra activity exclusions). DJIM 33% cutoffs may appear as a comparison, not as the traded rule
  - Instant risk assessment: short questionnaire for drawdown tolerance and time horizon
- **Main portfolio dashboard**
  - Total NAV and performance: clean line charts of account growth vs a Halal benchmark (SPUS in the lab; MSCI World Islamic as an optional display benchmark)
  - Shariah health indicator: prominent badge / status bar for book-level compliance
  - Dividend purification tracker: impure slice of dividends (interest-income proxy, cash-reserve income, etc.) and a **One-Click Purify** control that, in the shadow fund, posts a ledger entry rather than sending real charity wires
- **Fund and stock inspection**
  - “Why is this stock Halal?” card per holding
  - Business-activity screen pass / fail
  - Debt-to-market-cap ratio vs the live AAOIFI 30% line (UI mockups used 33% DJIM-style; the traded book stays 30 / 30 / 70)
  - Interest-bearing securities (cash) ratio
  - Receivables / liquid-assets ratio
  - Allocation views: donut / treemap by sector (Tech, Healthcare, Industrial, …) and geography
- **Transactions and automated deposit (paper)**
  - Clear paper-deposit flows with projected compounding (illustrative, not a return promise)
  - Automated monthly recurring contribution toggles against the paper account
  - Transaction history: deposits, trades, purification accruals, cash from the SMA throttle

### B. Operator end (fund manager / quant / Shariah auditor)

Goal: high-density layout, operational safety, automated rebalancing, and an audit trail of how the book was built.

- **Fund construction and strategy builder**
  - Factor and screening controls that **display** the frozen live book (FCF quality funnel, 10% name cap, whole-NAV SPY 200-day cash throttle). Changing knobs in the shadow UI must not silently retune the live rule without an explicit version bump
  - Universe filters (e.g. Halal large cap) as audit context, not a second undocumented engine
  - Real-time (session) Shariah filter: batch pipeline that flags names near or over ratio limits on the latest 10-Q / 10-K (e.g. leverage that just crossed the AAOIFI line)
- **Portfolio health and analytics terminal**
  - Risk and exposure grid: Sharpe, Sortino, beta, tracking error, alpha, max drawdown, VaR / CVaR
  - Rebalancing and order matrix: proposed target weights vs current weights, drift, estimated costs **before** tickets go to the paper broker
- **Purification and audit console**
  - Purification ledger: quarterly non-permissible income across holdings; export PDF / CSV for a future Shariah board
  - Audit log and override system: manual compliance overrides or board approvals with attached documents (shadow: recorded, not legally binding)

### C. Backend loop (what must exist for the UI to tell the truth)

- **halalquant data refresh:** incremental daily prices, filings, AAOIFI metrics, dividends (no full S&P rebuild every night)
- **Target-weight engine (PMS):** `as_of` → intended weights, cash %, SMA on/off, cap clips, reason codes (wraps `Research/sleeves`)
- **OMS-lite:** intended book minus paper positions → buy/sell tickets; idempotent; skip dust
- **Paper broker adapter:** positions, cash, submit next-session orders (one paper venue)
- **Reconciliation and kill switch:** halt if broker holdings or cash disagree with the intended book beyond a band
- **NAV ledger:** official daily NAV, holdings snapshot, daily return, purification payable — **this** is what dashboards chart, not a research equity curve
- **Scheduler:** weekday refresh → targets → (month-end FCF rebuild, daily SMA and breach exits) → orders → after-close NAV mark
- **Secrets and isolation:** broker keys never in the frontend; operator actions logged

---

## How the shadow fund is structured

This is not a typical CRUD app that “is the fund.” The UI only **reads** a ledger the ops loop writes.

```text
[ halalquant ]          market data, SEC filings, AAOIFI / DJIM, purification ratios
        │
        ▼
[ Target book / PMS ]   FrozenRules + Lab → intended weights (and cash)
        │
        ▼
[ OMS-lite ]            tickets = target − paper holdings
        │
        ▼
[ Paper broker ]        fake money, real market prices, real fills
        │
        ▼
[ Middle office ]       recon, NAV, cash, purification payable, audit log
        │
        ▼
[ Operator UI ]         dense grids, diffs, confirm-to-trade
[ Investor UI ]         NAV, Shariah health, holdings, purify tracker
```

Cadence is **batch**, not high-frequency:

- **Daily:** mark NAV, SPY 200-day on/off, filing-breach watch, next-open sells
- **Month-end:** rebuild the FCF quality list and cap-weighted book (10% name lid)
- **Ex-date:** accrue purification; cheque ops may batch quarterly even in paper

Servers for V1 are a **reliable worker + API + database**, not co-located trading boxes. Reliability, idempotency, and audit matter more than latency.

---

## Frozen live book (what the shadow fund is allowed to trade)

From Phase 1B ([`Research/README.md`](../Research/README.md)):

1. One quality funnel (Halal screens, then FCF top half, cap-weighted) — not a 40/40/20 sleeve mix
2. 10% single-name cap
3. Whole-NAV SPY trend throttle; **cash** when off
4. AAOIFI fail on a new filing → sell at the **next session**
5. Donate the impure dividend slice on the **ex-date** (ledger in shadow; wire later)
6. 10 bp cost stub for reporting; do not pretend capacity past ~$800M without spreading SMA switches

ROIC, dual-momentum as a 20% sleeve, SUE, high-beta, and CVaR sizing stay **out** of the traded shadow book.

---

## UX principles (from the product layout)

These rules apply to both ends. They stop the product from looking like generic fintech while hiding how the book works.

1. **Transparency over abstraction (eliminate the black box)**  
   In Halal finance, hidden fees and unclear holdings breed *gharar*. Every portfolio, weight change, or rebalance must drill down: why the name is in the book and how it qualifies.

2. **Functional high-density vs progressive disclosure**  
   Operators need dense tables, controls, and multi-panel grids. Investors see high-level metrics first, then statements on click. Do not dump the operator terminal on the client.

3. **Irreversible action friction (safety first)**  
   Rebalances, large paper sells, and purification posts use multi-step confirmations: draft → approved → executing → completed, with diffs and a weight-before / weight-after view.

4. **Deterministic real-time feedback**  
   Pending paper orders, background jobs, and connection state are explicit. Do not leave NAV or compliance as a spinner with no as-of time.

Screen-level requirements are in [PRD.md](PRD.md). Type, theme, widgets, and motion are in [DESIGN.md](DESIGN.md).

---

## Implementation (current)

Code lives in [`ops/`](../ops/). `halalquant` supplies facts. This package runs the **paper fund**.

```bash
python -m ops run --as-of today
python -m ops run --as-of today --skip-refresh
python -m ops run --as-of today --targets-only
python -m ops run --as-of today --coverage
```

What one `run` does:

1. Refresh prices, filings, and dividends (`--skip-refresh` to use the cache as it is).
2. Write today’s target weights (FCF list, 10% cap, cash if the SPY 200-day average is off).
3. Fill paper orders. The **first** session fills at that day’s **close** so a NAV exists. Later sessions fill yesterday’s orders at today’s **open**, then queue new orders for the next open.
4. If holdings do not match the weights just traded (gap above 3 percentage points, missing price, or negative cash), **halt**. No new orders until the account file is cleared.
5. Accrue ex-date purification from cached dividends when an impure ratio is known. That cash leaves NAV. It is not a real charity payment.
6. Append `ops/state/nav.csv`. A second run on the same date does not trade again.

| Path | Meaning |
| --- | --- |
| `ops/runs/YYYY-MM-DD/summary.json` | SMA flag, NAV, fills, halt reason |
| `ops/runs/YYYY-MM-DD/intended_book.csv` | Target weights after the cash switch |
| `ops/runs/YYYY-MM-DD/invested_book.csv` | FCF list if the switch were on |
| `ops/runs/YYYY-MM-DD/filing_fails.csv` | New AAOIFI fails. Reported here. Sold on a later open via the order diff |
| `ops/runs/YYYY-MM-DD/orders.csv` | Orders created this session |
| `ops/runs/YYYY-MM-DD/fills.csv` | Paper fills |
| `ops/state/account.json` | Cash, shares, pending orders, halt flag |
| `ops/state/nav.csv` | Official paper NAV path |

Starting paper cash is **$1,000,000** (`--capital`). This is not a broker API. It is a local paper account marked with cache prices.

Offline tests: `pytest ops/tests`.

**Not built yet:** a live paper-broker API (Alpaca / IBKR), operator UI, investor UI.

---

## Build order

1. Incremental **halalquant** refresh + filing-event breach feed — **done in [halalquant v0.3.0](https://github.com/regional-specter/halalquant/releases/tag/v0.3.0)**
2. Target-weight job — **in `ops/`**
3. OMS-lite + local paper broker — **in `ops/`**
4. Reconciliation, kill switch, NAV ledger — **in `ops/`**
5. Operator terminal (health + order matrix) so we can see if the loop is honest
6. Investor dashboard (NAV, Shariah badge, holdings, purification tracker)
7. Onboarding, paper deposits, and audit-console polish last

The investor UI is worthless until step 4 exists. Charts must come from paper NAV, not from `Research/papers/` figures.

---

## What stays out of this folder

- Factor discovery and white papers → [`Research/`](../Research/README.md)
- Raw screens, prices, and purification math → **halalquant**
- Live capital, fund administration, legal entity, and marketing of a live track record
