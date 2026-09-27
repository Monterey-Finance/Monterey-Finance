# Product requirements — shadow fund surfaces

**Status:** planning. **Phase:** 2 shadow fund. **Capital:** paper only.

This document specifies the investor and operator interfaces for the Monterey Finance shadow fund. The book they display is the frozen Phase 1B book already run by [`ops/`](../ops/). Visual rules live in [DESIGN.md](DESIGN.md). Strategy rules stay in [`Research/`](../Research/README.md). Market facts stay in **halalquant**.

The interfaces are not a live fund. There is no investor capital, no custodian, no KYC, and no charity wire. A screen that looks finished still sits on a paper account.

---

## 1. What these surfaces are for

The shadow fund exists to prove that the Phase 1B book can run every session: target weights, paper orders, a NAV from fills, and a visible Shariah record.

The UI does not compute that book. It reads the ledger the ops loop writes, and it sends a small set of explicit actions back into that loop (confirm a paper rebalance, post a purification ledger entry, record a paper deposit, record an audit note).

Two people use it.

| Person | Job to be done | Density |
| --- | --- | --- |
| Investor | See whether the paper account is growing, why every holding is there, and what slice of income is impure | High-level first. Detail on click |
| Operator (manager, quant, Shariah reviewer) | See whether today's run is honest, and commit or halt the next paper orders with a full diff | Dense grids, always |

One official NAV exists. Investor charts and operator grids must both read `ops/state/nav.csv` and the dated files under `ops/runs/`. A research equity curve from `Research/papers/` is never a substitute.

---

## 2. Experience principles

These four rules decide what a screen is allowed to hide.

### Transparency over abstraction

Hidden fees and unexplained holdings are *gharar*. Every weight, rebalance, cash day, and purification dollar has a drill-down: the name, the rule that included or excluded it, the filing date, and the ratio versus the line it is judged on.

The traded standard on screen is **AAOIFI**, at the frozen **30 / 30 / 70** lines:

- Debt to market cap under 30%
- Interest-bearing securities to market cap under 30%
- Receivables plus cash to market cap under 70%

A DJIM-style 33% marker may be drawn as a comparison tick. It is never the pass/fail line of this book.

### Progressive disclosure on the investor end, density on the operator end

The investor home is a few widgets: NAV, a compliance status, purification owed, and the holdings that matter. Statements, ratios, and order diffs open on demand.

The operator end keeps Sharpe, drift, costs, and the order matrix on one surface. The investor never lands in that terminal by default.

### Friction on irreversible actions

Paper rebalances, large sells, and purification posts move through **Draft → Approved → Executing → Completed**. The confirmation shows weight before and weight after, estimated cost, and what will be written to the ledger. Theme changes, chart ranges, and search do not use this friction.

### Deterministic feedback

Every figure has an as-of timestamp from the run that produced it. Pending orders, a running job, a halted book, and a stale cache each have their own visible state. A spinner with no as-of time is a defect.

---

## 3. Scope

### In this phase

- Investor profiling on a paper profile: goal, ethics overlay, risk questionnaire
- Investor dashboard, holding inspection, paper activity, paper contribution plan
- Operator book view, health grid, order matrix, purification ledger, audit log
- Both ends in white and black, with the motion in [DESIGN.md](DESIGN.md)
- All numbers sourced from the ops ledger and halalquant facts

### Later, and labeled as such wherever the UI mentions them

- A live paper-broker API (Alpaca, IBKR, or similar)
- Real subscriptions, redemptions, KYC, and a transfer agent
- Charity wires and a Shariah board's legal sign-off
- Fund-admin NAV, audit opinions, and regulatory filings

### Never silently in scope

The shadow UI must not retune the frozen book. Knobs may **display** the live rule (one FCF quality funnel, 10% name cap, whole-NAV SPY 200-day cash throttle, next-session AAOIFI exit, ex-date purification, 10 bp cost stub). Changing a knob requires an explicit rules-version bump recorded in the audit log. ROIC, a dual-momentum sleeve, SUE, high-beta, and CVaR sizing stay out of the traded book.

Investor profiling does not create a second engine. If a paper profile adds an extra activity exclusion, names the fund still holds are shown as **in the book, outside your overlay**, with weight and reason. They are not dropped from the official NAV.

---

## 4. Information architecture

```text
Investor
  Home            NAV, compliance, purification, goal
  Holdings        weights, allocation, “why this is Halal”
  Activity        deposits, fills, accruals, cash-throttle days
  Contribute      paper deposit and monthly paper contribution
  Settings        profile, theme, sessions

Operator
  Today           run health, halt state, as-of
  Book            frozen rule, universe context, breach flags
  Health          risk and exposure grid
  Orders          target vs current, diff, confirm
  Purification    quarterly ledger and export
  Audit           overrides, approvals, documents
```

Investor and operator are separate shells. A person who has both roles switches shells explicitly. The investor shell has no path that commits orders.

A persistent **Paper** chip sits in the top bar of both shells, with the NAV as-of date beside it. That chip is the shadow-fund disclosure. It stays visible while scrolling.

---

## 5. Investor end

Goal: a non-technical reader can see growth, see that the book is Halal, and see what must be purified, without sitting in front of a terminal.

### 5.1 Onboarding and profiling

Three short steps, then the home. Progress is a step list, not a percentage of a sales funnel. The profile is stored for this paper account. It can be edited later from Settings.

**Step 1 — Goal.** One choice, presented as cards:

| Goal | What the home emphasizes |
| --- | --- |
| Wealth growth | NAV chart and drawdown |
| Halal dividend yield | Distributions and the impure slice |
| Capital preservation | Cash throttle days, max drawdown, and the preservation goal |

A single-choice card is the control. A slider is allowed only for a numeric target the investor states themselves (a paper goal amount, or a horizon in years). The goal does not change target weights.

**Step 2 — Shariah and ethics.** AAOIFI is fixed and labeled as the standard this book trades. The investor may add optional overlays on top: extra activity exclusions (weapons, a named ESG concern, an eco-clean screen). Overlays are preferences. The copy on this step says the official book stays on AAOIFI, and any name inside the book but outside the overlay will be listed, not hidden.

DJIM 33% cutoffs are explained here as a comparison the holding card can show. They are not offered as a switch that changes the book.

**Step 3 — Risk.** Three questions, one screen each or one short page:

1. Largest peak-to-trough decline the investor can sit through
2. Time horizon
3. Whether paper contributions are intended as a lump sum, monthly, or both

The result is a plain-language risk note on the home (“You said you can sit through a 20% decline. The paper book’s max drawdown to date is X.”). It is not a suitability license and it does not size positions.

**Account gate.** The shadow phase has no KYC. The account step collects a display name and confirms the paper disclosure: this account is fake money, the NAV is from paper fills, and purification is a ledger entry. Continuing requires that confirmation.

**Acceptance**

- Completing the three steps lands on Home with the goal reflected in which widget leads
- Skipping is unavailable; each step has a Back path
- Re-opening Settings shows the saved choices and the AAOIFI lock
- No step writes `intended_book.csv` or changes `FrozenRules`

### 5.2 Home — portfolio dashboard

The home is the Hexis / Finpoint pattern applied to one paper account: a rail, one hero number, a short stat row, one chart, then a small set of cards. Contents:

**Hero.** Total net asset value from the latest row of `ops/state/nav.csv`, with the day change in green or red. The as-of session date sits under the number. Starting paper capital is the configured capital (default $1,000,000) until paper deposits exist.

**Stat row, under the hero.**

| Stat | Source |
| --- | --- |
| Invested | Market value of equity positions |
| Cash | Paper cash, including days the SPY 200-day throttle is off |
| Purification payable | Impure income accrued and not yet posted |
| Holdings | Count of names with weight above zero |

**Chart.** Account growth against a Halal benchmark. **SPUS** is the default comparison in this lab. MSCI World Islamic is an optional second series, shown only when that series is actually loaded. Ranges: 1M, 3M, YTD, 1Y, All. The All range starts at the first NAV row, not at a backtest start date. Hovering a point shows date, NAV, and benchmark.

**Shariah health.** One status badge for the book, driven by the latest run:

| State | Meaning |
| --- | --- |
| Compliant | No open AAOIFI fail in the held book |
| Review | A filing breach is flagged and the next-session sell is queued or not yet filled |
| Halted | Reconciliation failed; the kill switch is on |

The badge opens a short list: pass count, names in review, and the run id. “100%” is shown only when every held name passes. A single fail is not rounded into a green badge.

**Purification tracker.** The impure slice of dividends (interest-income proxy and other non-permissible income halalquant already measures), the ex-dates included, and the payable amount. **One-Click Purify** opens a confirm step. Confirming posts a ledger entry that reduces paper cash and clears the payable for those accruals. The button label on the confirm step is **Post to ledger**. The sheet states that no charity wire is sent. If nothing is payable, the button is quiet and disabled, with the next expected ex-date if one is known.

**Goal card.** The profiling goal, the paper progress toward a stated amount if the investor set one, and a single sentence that this is a paper target. This is the milestone pattern: one large figure, one percent pill, one secondary figure. It is not a promised return.

**Cash-throttle note.** When the whole-NAV SPY 200-day switch is off, the home says the book is in cash, names the signal, and shows the session it turned off. The chart still shows NAV. It does not imply the strategy is “broken” on a flat cash day.

**Acceptance**

- Hero, chart, and payable match the latest `nav.csv` row and that day’s `summary.json` within one cent
- A halted account replaces the green badge with Halted and links to the operator halt reason in investor language (“Trading is paused until the paper account is reconciled”)
- One-Click Purify does not appear to succeed until the ledger write returns
- The chart has an empty state when fewer than two NAV points exist: the hero still shows, and the chart says the series starts after the next session

### 5.3 Holdings and inspection

**List.** Each holding shows name, ticker, weight, market value, day change, and a pass / review chip. Sector and geography roll up into one allocation widget (donut on the investor end). A treemap is the alternate view, same data. Sorting defaults to weight.

**Allocation.** Sectors the book actually holds (Technology, Healthcare, Industrials, and the rest of the live classification) and geography. Unclassified is its own slice, never dropped.

**Why this is Halal.** Opening a holding reveals one card, in this order:

1. Business-activity screen: pass or fail, with the activity that was tested
2. Debt to market cap, the value, and the 30% AAOIFI line. A 33% tick may sit on the same bar, labeled DJIM
3. Interest-bearing securities to market cap, against 30%
4. Receivables and cash to market cap, against 70%
5. Filing source and period (10-Q or 10-K, period end)
6. Why the name is in the book: FCF quality rank, weight before the 10% cap, weight after the cap, and whether the cap clipped it
7. Overlay status, if the investor set one: inside the overlay, or in the book and outside the overlay

Failing a ratio does not disappear from the list while the shares are still in the paper account. The chip says Review, and the card says the rule is to sell at the next session open after the filing fail.

**Price.** The investor chart for a name is a line. A candlestick is reserved for the operator inspector. Range pills match the home chart.

**Acceptance**

- Ratios match the halalquant facts used for that run, and the threshold labels read 30 / 30 / 70
- A clipped name shows both the uncapped and capped weight
- Names outside an ethics overlay remain visible and counted in NAV
- The allocation sums to 100% of invested equity, with cash called out separately so a cash-throttle day does not distort sector slices

### 5.4 Activity, deposits, and the monthly contribution

**Activity list.** A single ledger, newest first:

- Paper deposits and withdrawals
- Fills (buy and sell, session, price, shares)
- Purification accruals on ex-date, and posts when the investor or operator purifies
- Cash-throttle changes (invested to cash, or cash back to the book)

Each row has an amount, a date, and a type chip. Opening a fill shows the order id and the run directory it came from.

**Contribute.** Two actions on the paper account:

- A one-time paper deposit or withdrawal, with the amount and the resulting cash
- A monthly paper contribution toggle: on or off, amount, and the next date

Until the deposit job exists, this screen still specifies the interaction, and it stays behind the build order in the README (onboarding and paper deposits last). The projected compounding chart is **illustrative**. It uses a clearly labeled assumption the investor can see (the rate, the contribution, the horizon). It is not the NAV forecast and it does not use words that promise a return. The chart updates as the amount or the monthly toggle changes.

Withdrawal and any deposit large enough to move cash by more than 10% of NAV use the confirm sheet (amount, cash before, cash after). Fills themselves are not requested from this screen.

**Acceptance**

- The activity list is the paper account, not a sample of marketing transactions
- Illustrative compounding is captioned as an illustration and never shares the hero NAV’s visual rank
- The monthly toggle’s on/off state survives a reload
- A halted book can still show history; it cannot submit a new paper deposit until the halt clears

---

## 6. Operator end

Goal: tell whether the loop is honest, and commit paper orders with a record of what changed.

The operator shell uses the same widget language as the investor shell, at higher density: more columns, monospace figures, split panels. It is the same white / black theme, not a separate visual product.

### 6.1 Today

The first operator screen is run health, using the session-list pattern: one row per dependency, a status dot, a timestamp, and a one-line result.

| Row | Green | Red | Neutral |
| --- | --- | --- | --- |
| Data refresh | Prices, filings, dividends updated for the session | Refresh failed | Skipped (`--skip-refresh`) |
| Target book | `intended_book.csv` written | Target job failed | Not yet run |
| Paper broker | Fills match the orders for the session | Position or cash break | No orders this session |
| NAV mark | Row appended to `nav.csv` | Mark missing | Already marked; second run did not trade |
| Kill switch | Clear | **Halted**, with the reason from `summary.json` | — |

The halt reason is the full operator string (gap above 3 percentage points, missing price, or negative cash). Clearing a halt is an audited action: the operator records why the account file was corrected. The UI does not clear the flag by itself.

A second panel summarizes the session the way `summary.json` does: SMA on or off, NAV, fill count, cash.

### 6.2 Book — construction and the Shariah filter

This screen **displays** the frozen rule. It is not a strategy sandbox.

Visible, read-only unless a version bump is in progress:

- Quality funnel: Halal screens, then FCF top half, cap-weighted
- 10% single-name cap
- SPY 200-day throttle, and today’s on/off state
- Breach exit: next session
- Purification: impure slice on the ex-date
- Cost stub: 10 bp

Universe filters (for example Halal large cap) are labeled **audit context**. They document the universe the run used. They are not a second book.

**Breach queue.** Names whose latest 10-Q or 10-K crossed an AAOIFI line. Columns: ticker, ratio that failed, value, line, filing type, period end, action (sell at next open, already ordered, filled). This is the “compliance drift” view. A name still inside the line but within 2 percentage points of it is marked **Near limit**, so the reviewer sees it before it fails. Near-limit is informational. It does not create an order.

**Version bump.** Editing a frozen parameter is a separate flow: proposed change, reason, diff against the current rule, confirm. The audit log stores the old rule, the new rule, and the actor. Until that entry exists, the next run keeps the previous rule.

### 6.3 Health

An institutional grid, one row of definitions and one row of figures, for the paper NAV series:

- Sharpe
- Sortino
- Beta to SPUS (and to SPY, labeled as the all-stock reference)
- Tracking error versus SPUS
- Alpha versus SPUS
- Max drawdown
- Value at Risk and CVaR, with the window and confidence printed next to the number

Each metric shows the window it was computed on. A series too short for a metric shows an em dash and the number of sessions still required, not a zero.

Exposure sits beside the grid: sector weights, single-name weights against the 10% cap, and cash weight. A name on the cap is marked clipped.

### 6.4 Orders

The matrix before anything is committed:

| Column | Content |
| --- | --- |
| Name | Ticker and company |
| Current weight | Paper account |
| Target weight | Today’s intended book, after the cash switch and the cap |
| Drift | Target minus current, in percentage points |
| Side | Buy, sell, or none |
| Notional | Estimated dollars |
| Cost | Estimated at 10 bp |
| Reason | Cap clip, SMA cash, filing breach, monthly rebuild, deposit rebalance |

Dust that the OMS will skip is shown and marked skipped, so a missing ticket is explained.

**Commit path.** Draft (the matrix) → Approved (explicit confirm, weight-before / weight-after for every name with a ticket) → Executing → Completed, or Halted if reconciliation fails. Cancelling from Draft writes nothing. A commit is idempotent with the ops rule: a second run on the same date does not trade again, and the screen says so.

The investor shell cannot open this matrix.

### 6.5 Purification ledger

Quarterly view across held names: ex-date, gross dividend, impure ratio, impure amount, status (accrued or posted). Totals for the quarter and for the life of the paper book.

Export: PDF and CSV, with the run ids and the ratio source, suitable to hand to a future Shariah board. The export header states that the figures are paper-ledger amounts, not wires.

Posting the quarter uses the same confirm friction as the investor One-Click Purify. Either end can post; the ledger records which end posted. A second post of the same accrual is rejected.

### 6.6 Audit log

Append-only. Event types:

- Run completed, skipped, or halted
- Order batch approved
- Purification posted
- Rules version bumped
- Manual compliance override or a recorded board note, with the document name attached
- Halt cleared

An override stores the actor, the timestamp, the name or rule affected, the reason, and the attachment reference. In this phase the attachment is a file recorded in the shadow system. The entry is labeled **recorded, not a legal sign-off**.

The log filters by type and date. It does not support edit or delete.

---

## 7. Shared behaviors

**As-of.** Any widget bound to the ledger shows the session date. Widgets bound to a filing show the filing period. If the latest run is older than the last weekday session, the Paper chip’s companion text says the book is stale and names the last good session.

**Kill switch.** Halt is global. Investor home shows Halted. Operator Today shows the reason. Orders, deposits, and purification posts that would change the account wait until the halt is cleared. Reading history stays available.

**Theme.** White and black are both first-class. The choice is per browser profile, available from the top bar and from Settings, and it does not change data.

**Search.** Investor search filters holdings. Operator search filters tickers, runs, and audit events. Search never executes an order.

**Empty paper book.** Before the first successful run, both shells explain that NAV appears after the first session fills at the close. They do not invent a chart.

**Errors.** A failed load names the file or endpoint it could not read and keeps the last good figures on screen with their original as-of. It does not blank the hero into a skeleton with no date.

**Access.** Operator routes reject an investor session. This phase can use a simple role flag. It is not an identity-provider project.

---

## 8. Data the screens are allowed to trust

| UI need | Ledger |
| --- | --- |
| Official NAV path | `ops/state/nav.csv` |
| Cash, shares, pending orders, halt | `ops/state/account.json` |
| Session result, SMA flag, halt reason | `ops/runs/YYYY-MM-DD/summary.json` |
| Target weights after the cash switch | `ops/runs/YYYY-MM-DD/intended_book.csv` |
| FCF list if the switch were on | `ops/runs/YYYY-MM-DD/invested_book.csv` |
| New AAOIFI fails | `ops/runs/YYYY-MM-DD/filing_fails.csv` |
| Orders and fills | `orders.csv`, `fills.csv` for that session |
| Ratios, activities, dividends | halalquant facts for the same as-of |

If a figure cannot be tied to one of these, it is not shown. Benchmark series are identified by name (SPUS, and MSCI World Islamic only when loaded).

---

## 9. Build sequence

Matches the README. The investor home is not staffed with sample numbers to look finished before the ledger exists.

1. Operator Today and Orders, read-only, on the current `ops/` outputs
2. Investor Home and Holdings, read-only, from the same NAV
3. Commit path for paper orders, with the status steps and the idempotent same-day rule
4. Purification ledger, export, and post
5. Audit log, including halt clearance and rule-version bumps
6. Profiling, paper deposits, monthly contribution, and illustrative compounding

Steps 1 and 2 are the proof that the loop is honest. Step 6 is last.

---

## 10. Done, for this phase

- An operator can open Today after `python -m ops run --as-of today` and see the same NAV, SMA flag, fills, and halt reason as `summary.json`
- An investor can open Home and Holdings and explain, for any name, the activity result, the three ratios against 30 / 30 / 70, and whether the 10% cap clipped it
- A purification post reduces paper payable once, and the export says the amount is a ledger figure
- A same-day second commit does not create a second set of fills
- White and black both render every widget in [DESIGN.md](DESIGN.md), and the paper disclosure stays visible
- No screen writes a live order, a wire, or a change to `FrozenRules` without an audit entry
