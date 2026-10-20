# Research pipeline

A notebook loads one snapshot of market facts, copies the v2 book, changes one section, and asks the simulator to step every session. The same path writes the ledger that ops and the desk read.

The live book is `books/fcf-sma-v2-baseline.yaml`, hash `6ca86844209e`. Package `monterey` 0.2.0. Facts come from `halalquant` 0.4.0. Papers 01–15 still open through `Research/sleeves/` (a shim over `monterey.legacy.sleeves`). A new paper uses the calls on this page.

Scored window: **2020-01-02 → 2026-09-30**. Load from **2019-12-01** so the 200-day average exists on the first session. The mandate score is **Calmar** and **max drawdown**. Kill rules are in [`book-construction-status.md`](book-construction-status.md).

## On this page

- [Starting a notebook](#starting-a-notebook) — `boot`, `run_book`, `run_sprint`
- [BookSpec](#bookspec) — `load`, `replace`, `hash`, every section argument
- [ResearchData](#researchdata) — membership, screens, prices, filings
- [One session](#one-session)
- [Universe and screen](#universe-and-screen)
- [Brains](#brains)
- [Construction](#construction)
- [Overlay](#overlay)
- [Execution](#execution)
- [Accounting](#accounting)
- [Simulator](#simulator)
- [Ledger](#ledger)
- [Scores](#scores)
- [Which argument a paper sets](#which-argument-a-paper-sets)
- [Adding a knob](#adding-a-knob)
- [Exemplars](#exemplars) — full notebook cells to copy, then change one section

---

## Starting a notebook

Run the notebook from `Research/papers/<id>/`. The first cell must put the repo root on `sys.path` or `import monterey` fails. Copy [Exemplar A](#a-first-cell) for that cell. Do not paste a function signature from this page into a cell — those lines are definitions, not calls.

A short trial after the first cell looks like this. Full grids, plots, and layer checks are in [Exemplars](#exemplars).

```python
from monterey.research import boot, compare, run_book
from monterey.sprints import score_against_baseline

rd = boot("paper-23", start="2019-12-01", end="2026-09-30")
base = run_book("fcf-sma-v2-baseline", rd, paper="23-spus-throttle", id="v2")
trial = run_book(
    "fcf-sma-v2-baseline", rd,
    paper="23-spus-throttle", id="spus-sma",
    overlay={"ticker": "SPUS"},
)
compare([base, trial], rd)
score_against_baseline(trial, base, rd)
```

`run_book` simulates **2020-01-02 → 2026-09-30** even when `boot` started in December 2019.

### `boot`

```python
boot(paper, start="2019-12-01", end="2026-09-30", *, snapshot=None, refresh=False, figures=True, quiet=False) -> ResearchData
```

Load the research facts and set pandas / matplotlib defaults. Prints `ResearchData.describe()`, including the snapshot hash to put in figure captions.

```python
rd = boot("paper-23", start="2019-12-01", end="2026-09-30")
rd = boot("paper-17", snapshot="ebbbefb35545")  # the freeze a previous run already wrote
```

**paper** : str
Name stored on `rd.manifest["paper"]`.

**start, end** : str
Window passed to the loader. Prices begin ~420 days earlier than `start`, so a 200-day average and 12–1 momentum exist on day one.

**snapshot** : str or None
A hash (or a folder) under `data/snapshots/`. Reopens that freeze and skips the halalquant cache.

**refresh** : bool, default `False`
Rebuild the snapshot from the cache.

**figures** : bool, default `True`
Create `./figures` in the notebook's working directory.

**quiet** : bool, default `False`
Skip the describe print.

### `run_book`

```python
run_book(spec, data, *, paper=None, start="2020-01-02", end="2026-09-30", write=True, **changes) -> Ledger
```

Simulate one book. `changes` are spec-section edits. Each key is a section name (`overlay`, `signal`, `construction`, …). Values merge into that section. `id` and `label` are not sections. They rename the book.

```python
trial = run_book(
    "fcf-sma-v2-baseline", rd,
    paper="18-execution",
    id="drift-1pct",
    execution={"drift_band": 0.01},
)
```

With `paper` set, the ledger is written to `ledgers/experiments/<paper>/<id>/<spec hash>/` and `manifest["mode"]` is `"experiment"`. Without `paper`, it is written under `ledgers/<id>/<hash>/` as a `"replay"`. `write=False` returns the ledger and leaves the disk alone.

An unknown section or an unknown key inside a section raises `ValueError` before any session runs.

### `run_sprint`

```python
run_sprint(number, rd=None, baseline=None) -> tuple[list[Ledger], DataFrame]
```

Run a prepared paper, **16–20 only**. Prints the comparison table and returns `(ledgers, table)`. The first ledger is v2.

```python
ledgers, table = run_sprint("16", rd)
```

| `number` | Variants the sprint builds |
| --- | --- |
| `"16"` | `kind: none`, `confirm_days` 2 and 5, `band` 0.02, `off_exposure` 0.5, `vol_target` 0.12 |
| `"17"` | `universe.pit: false` against the PIT baseline |
| `"18"` | `rebalance: on_signal`, `drift_band` 0.01, `min_trade` 2500, both together |
| `"19"` | `brain: fcf_layers` with conversion, stability, yield, then all three |
| `"20"` | `sector_cap` 0.40 and 0.50, `name_cap` 0.08, both together |

Papers 21–27 are not in this table. Call `run_book` yourself.

`v2_baseline_ledger()` reads `ledgers/fcf-sma-v2-baseline/<hash>/` when that folder already has `nav.parquet`. `v2_snapshot_hash()` is the `data_snapshot` stamped on that ledger. Pass it to `boot(..., snapshot=)` when the notebook must use the same facts as the scored book.

---

## BookSpec

One declarative description of a book. Seven sections. Defaults fill any key the YAML omits. The hash covers the rules only, so two runs with the same hash traded the same way.

```python
from monterey.spec import BookSpec

spec = BookSpec.load("fcf-sma-v2-baseline")
spec.hash()          # "6ca86844209e"
spec.summary()       # list of (label, value) for a terminal or a caption
spec.replace(id="spus-sma", overlay={"ticker": "SPUS"})
```

### `BookSpec.load`

```python
BookSpec.load(path) -> BookSpec
```

`path` is a filesystem path or a name under `books/` (`"fcf-sma-v2-baseline"`). Unknown YAML keys raise.

### `BookSpec.replace`

```python
spec.replace(*, id=None, label=None, **sections) -> BookSpec
```

Return a new spec. Section dicts are merged, key by key. `signal.params` is merged one level deeper, so you can change `keep_quantile` without restating `min_holdings`.

```python
spec.replace(signal={"params": {"keep_quantile": 0.4}})
spec.replace(construction={"sector_cap": 0.40, "name_cap": 0.08})
```

### `BookSpec.hash`

```python
spec.hash() -> str   # 12 hex characters
```

SHA-256 of the seven sections, keys sorted. `id`, `label`, `description`, and `benchmarks` are not in the hash. `screen.breach_complete: false` is dropped before hashing, so turning that flag on is what changes the v2 hash.

### Section arguments

These are the keys `replace` and `run_book` accept. Defaults are the v2 book unless a cell says otherwise.

#### `universe`

| Key | Default | Meaning |
| --- | --- | --- |
| `index` | `"sp500"` | Index name passed to the data layer. |
| `pit` | `True` | `True`: members on that date. `False`: the snapshot's end-date list, pasted onto every past date. |

#### `screen`

| Key | Default | Meaning |
| --- | --- | --- |
| `sectors` | `True` | Apply the banned-activity list. |
| `debt` | `0.30` | Max debt / 24-month market cap. |
| `cash` | `0.30` | Max cash and interest-bearing securities / 24-month market cap. |
| `receivables` | `0.70` | Max receivables / 24-month market cap. |
| `breach_exit` | `"next_open"` | `"next_open"` sells a failed 10-Q / 10-K at the next open. `"report_only"` writes the event and keeps the shares. |
| `breach_complete` | `False` | Keep a failed name in the exit set until its shares are zero, and sell the residual at the next real print. |
| `watch_band` | `0.02` | Distance to a ratio line that puts a passing name on the watch list. The watch list does not sell. |

#### `signal`

| Key | Default | Meaning |
| --- | --- | --- |
| `brain` | `"fcf_quality"` | Registered name. See [Brains](#brains). |
| `params` | `{}` | Keyword arguments for that brain. v2 sets `keep_quantile: 0.5` and `min_holdings: 20`. |

#### `construction`

| Key | Default | Meaning |
| --- | --- | --- |
| `weight` | `"cap"` | `"cap"` uses market cap. `"equal"` uses 1/N. `"score"` uses the brain's score, floored at 0. |
| `name_cap` | `0.10` | Max weight of one name. `None` leaves weights uncapped. |
| `sector_cap` | `None` | Max weight of one sector. `None` leaves sectors uncapped. |
| `collapse_share_classes` | `True` | Keep the larger listing of a dual class, then renormalise. |

Weights from this section sum to 1. The overlay has not been applied yet.

#### `overlay`

| Key | Default | Meaning |
| --- | --- | --- |
| `kind` | `"spy_sma"` | `"spy_sma"` is the moving-average switch. `"none"` (or `"off"` or `""`) is always invested, exposure 1, before any vol target. |
| `ticker` | `"SPY"` | Price series the switch reads. `"SPUS"` is a valid ticker. |
| `window` | `200` | Sessions in the simple moving average. |
| `confirm_days` | `0` | The switch flips after more than this many consecutive closes on the other side of the line. `0` flips on the first close. `2` flips on the third. |
| `band` | `0.0` | Hysteresis. On above `sma * (1 + band)`, off below `sma * (1 - band)`. |
| `off_exposure` | `0.0` | Fraction of the stock book kept when the switch is off. `0.5` still owns those stocks, at half size. |
| `vol_target` | `None` | Annualised volatility target on `ticker`. Exposure is scaled down to it, in steps of 5%. `None` turns it off. |
| `vol_lookback` | `20` | Sessions of daily returns used for that realised vol. |

`regime()` builds this series once, before the first session, from prices. It does not see the book's own NAV.

#### `execution`

| Key | Default | Meaning |
| --- | --- | --- |
| `signal_lag` | `"next_open"` | Orders written at the close fill at the next open. |
| `rebalance` | `"daily_to_target"` | `"daily_to_target"` trades every name back to target each session. `"on_signal"` trades on a new snapshot, a switch flip, a breach, and the first session. |
| `drift_band` | `0.0` | Skip a name already held when `abs(target weight − current weight)` is below this. Exits are still sold. |
| `min_trade` | `100.0` | Skip a non-exit whose notional is below this many dollars. |
| `first_fill` | `"close"` | The first session fills at that day's close, so a NAV exists. Later sessions fill at the next open. |

#### `accounting`

| Key | Default | Meaning |
| --- | --- | --- |
| `capital` | `1_000_000.0` | Starting cash. |
| `dividends` | `True` | Credit the dividend to holders of the prior close. |
| `cost_bps` | `10.0` | Commission on each fill, in basis points of notional. Charged inside the fill, taken out of cash. |
| `purify` | `"ex_date"` | `"ex_date"` donates `impure ratio × gross dividend` on the ex-date. `"off"` keeps it. |
| `purify_uncredited` | `False` | Donate even when `dividends` is false. v1 parity only. |

There is no cash-yield argument. Idle cash earns zero.

#### `benchmarks`

Default `("SPUS", "SPY")`. Reported beside the book. Not part of the hash.

---

## ResearchData

Every fact a book needs, loaded once. Notebooks usually receive it from `boot` and pass it through. Reach into it when the question is about the inputs (who was in the index, which filing failed) rather than about NAV.

```python
rd.members("2022-06-30", pit=True)
rd.halal("2022-06-30", pit=True, sectors=True, debt=0.30, cash=0.30, receivables=0.70)
rd.total_return("SPUS")
rd.describe()
```

**`members(as_of, pit=True)`** → `list[str]`
Index members on `as_of`. `pit=False` uses the snapshot end date for every call.

**`universe(as_of, pit=True)`** → DataFrame
Those symbols plus `sector`, `sector_allowed`, `in_index`.

**`metrics_on(as_of)`** → DataFrame
The month-end fundamentals snapshot in force: the last stamp on or before `as_of`.

**`snapshot_on_or_before(as_of)`** → `date` or None
The stamp itself. The simulator rebuilds the stock list only when this stamp changes.

**`halal(as_of, *, pit=True, sectors=True, debt=0.30, cash=0.30, receivables=0.70)`** → DataFrame
Members joined to ratios. `is_compliant` requires an allowed sector (when `sectors` is true) and a passing ratio snapshot. `reason` is the first failed test: missing sector, excluded activity, no metrics, or a named ratio. Columns include `debt_ratio`, `cash_ratio`, `receivables_ratio`, `market_cap`, `financial_pass`.

**`breaches_between(start, end, symbols=None)`** → DataFrame
10-Q / 10-K rows with `start < filed_date <= end` and `is_compliant` false. Columns: `symbol`, `filed_date`, `reason`.

**`impure_ratios(as_of)`** → `dict[str, float]`
Impure-income ratio from the snapshot in force. Used on the ex-date.

**`total_return(symbol)`** → Series
Adjusted close, the series `compare` uses for SPUS and SPY.

**`sessions`** / **`sessions_between(start, end)`**
Trading days, defined as dates with a SPY close.

**`prices`**
Wide date × symbol frames: `open`, `close`, `adj_close`, `volume`. Signals use `adj_close`. Fills use `open` and `close`.

**`dividends_by_day`**
`dict[Timestamp, list[(symbol, dividend per share)]]`.

**`sectors`**
`dict[symbol, sector]`. A sector is allowed when its lowercased label is absent from this set: alcohol, tobacco, gambling, pork, weapons, defense, adult entertainment, conventional banking, conventional insurance, interest-based finance. A label such as `"Financials"` is allowed. That is the grey-area list paper 27 is about.

**`extras`**
Optional frames. The `roic` brain reads `extras["roic_history"]`. The `sue` brain reads `extras["sue_events"]`. `boot` does not load either.

**`manifest["hash"]`**
Snapshot id. Same hash means the same facts.

---

## One session

`Simulator.step` runs this order for session `t`. A decision at the close of `t` fills at the open of `t+1`.

1. **Dividends.** Holders at the prior close receive dividends with ex-date `t`. Purification leaves cash.
2. **Fills.** Orders written at close `t−1` fill at open `t`. Sells first. Buys stop when cash runs out. Cost leaves cash.
3. **Targets.** Exposure for this close, the monthly selection (reused until the snapshot stamp changes), breach exits for filings known by `t`, then `target weight = invested weight × exposure`.
4. **Orders.** Written at close `t`, held for open `t+1`. The first session fills at the close.
5. **Delistings.** A held name with no price for 7 sessions is cashed at its last close.
6. **Mark.** NAV, positions, orders, fills, cashflows, and events for this close.

The stock list is cached on the fundamentals stamp. Daily work is the overlay, breaches, and share counts drifting as prices move.

---

## Universe and screen

### `members`

```python
members(data, as_of, spec) -> DataFrame
```

Index members on `as_of`, using `spec.universe["pit"]`. This is membership only. No Halal test.

```python
from monterey.layers import members
members(rd, "2022-06-30", spec)   # symbol, sector, sector_allowed, in_index
```

### `screen`

```python
screen(data, as_of, spec) -> DataFrame
```

Same membership, plus the sector ban and the AAOIFI lines from `spec.screen`. One row per name, with `is_compliant` and `reason`.

```python
from monterey.layers import screen
held = screen(rd, "2024-12-31", spec)
held.loc[held["is_compliant"], "symbol"]
```

The engine calls this inside `selection()`, then hands the table to the brain. Calling it yourself is how a notebook audits the screen without a full run.

### `watch_list`

```python
watch_list(table, spec) -> DataFrame
```

Compliant names whose nearest ratio sits inside `spec.screen["watch_band"]` of its line. Columns: `symbol`, `ratio`, `value`, `line`, `gap`. An empty band returns an empty frame. This is an ops list. The simulator does not sell from it.

```python
from monterey.layers import screen, watch_list
watch_list(screen(rd, "2024-12-31", spec), spec)
```

---

## Brains

A brain turns the screened names into a ranked table. It does not set weights, cash, or the SMA.

```python
@brain("name")
def name(ctx, **params) -> DataFrame:
    ...
```

The spec picks it with `signal.brain` and passes `signal.params` as keywords. The frame must contain `symbol`, `score`, and `market_cap`. Extra columns are the "why" stored on the position row when the column is one the ledger knows, and shown in the desk.

```python
from monterey.layers.signals import BRAINS, Context, run_brain

ctx = Context(data=rd, spec=spec, as_of=day.date(), screen=table)
run_brain(ctx)          # uses spec.signal["brain"] and spec.signal["params"]
sorted(BRAINS)          # registered names
```

**`Context.compliant`**
Symbols on the screen with `is_compliant`.

**`Context.snapshot(compliant_only=True)`**
`metrics_on(as_of)`, optionally limited to compliant names, with a `sector` column.

`run_brain` raises `KeyError` on an unknown name and `ValueError` if `symbol`, `score`, or `market_cap` is missing.

### `fcf_quality`

The live brain. Top slice of compliant names by FCF / sales (free cash flow over revenue).

```python
run_book(..., signal={"brain": "fcf_quality", "params": {"keep_quantile": 0.5, "min_holdings": 20}})
```

**keep_quantile** : float, default `0.5`
Keep names at or above the `(1 - keep_quantile)` quantile of FCF margin. `0.5` is the top half. This is a rank cutoff, not a margin of 50% or of 6%.

**min_holdings** : int, default `20`
If the quantile cut leaves fewer names, fill back with the next-highest FCF margins until this count. If the whole positive-FCF pool is smaller than this, the brain returns an empty table.

**drop_high_vol_quantile** : float or None, default `None`
Drop the highest-volatility slice of the selection. `None` keeps them.

Positive FCF and a positive market cap are required before the cut. The score column is `fcf_margin`.

### `fcf_layers`

Paper 19. Starts from the same margin cut, then applies whichever later layers you turn on. A layer whose parameter is `None` is off. A layer that would leave fewer than `min_holdings` names is skipped for that date, and the previous stage is kept.

```python
run_book(..., signal={
    "brain": "fcf_layers",
    "params": {"conversion_min": 0.5, "min_holdings": 20},
})
```

**keep_quantile** : float, default `0.5`
Same margin cut as `fcf_quality`.

**min_holdings** : int, default `20`
Floor for the margin cut and for every later layer.

**conversion_min** : float or None
Keep names with FCF / EBITDA at least this value. Needs an `ebitda` column.

**stability_lookback** : int, default `36`
Month-end snapshots used for the stability stats.

**stability_min_positive** : float or None
Minimum share of those snapshots with positive FCF.

**stability_max_cv** : float or None
Maximum coefficient of variation of FCF margin over that window.

**yield_drop_quantile** : float or None
Drop the cheapest-yield slice. `0.2` drops the 20% with the lowest FCF / enterprise value.

The returned frame adds `layers` (for example `margin+conversion`), and the layer columns that ran.

### Other registered brains

These call the frozen paper-01–06 selectors. They are available. They are not the October book.

| Brain | Params | Needs |
| --- | --- | --- |
| `roic` | `roic_min=0.15`, `keep_quantile=0.5`, `min_holdings=20` | `rd.extras["roic_history"]` |
| `dual_momentum` | `keep_quantile=0.2`, `min_holdings=15` | Prices through `as_of`. The SMA is the overlay, not this brain. |
| `high_beta` | `keep_quantile=0.2`, `min_holdings=8` | Prices. Halal tech and clean energy, top beta slice. |
| `sue` | `sue_threshold=2.0`, `hold_trading_days=21` | `rd.extras["sue_events"]` |

```python
run_book(..., id="always-on-roic", signal={"brain": "roic"}, overlay={"kind": "none"})
```

That raises `ValueError` until `roic_history` is placed on `rd.extras`.

---

## Construction

### `build_weights`

```python
build_weights(selected, spec, sectors=None) -> Series
```

The brain's table becomes weights that **sum to 1**. This is the fully invested book, before exposure.

```python
from monterey.layers import build_weights
weights = build_weights(detail, spec, rd.sectors)   # index: symbol, values sum to 1
```

`spec.construction["weight"]` chooses cap, equal, or score. Dual classes collapse when `collapse_share_classes` is true. `apply_name_cap` then clips `name_cap`. A set `sector_cap` calls `apply_sector_cap`. An empty selection returns an empty series, and the book holds cash.

### `apply_name_cap`

```python
apply_name_cap(weights, cap) -> Series
```

In `monterey/legacy/sleeves/weighting.py`. Clip every name to `cap` and spread the leftover across names still under the cap, for up to 20 passes. `cap is None` returns the positive weights unchanged.

### `apply_sector_cap`

```python
apply_sector_cap(weights, sectors, cap, name_cap=None, iterations=50) -> Series
```

Scale any sector above `cap` down to it. Spread the excess over the other sectors in proportion to their current weight. Re-apply `name_cap` each pass. If every sector is over the lid, the last pass is kept and the lid is not met.

```python
from monterey.layers import apply_sector_cap
apply_sector_cap(weights, rd.sectors, cap=0.40, name_cap=0.10)
```

This is a ceiling. A sector floor (paper 25: minimum weight in health care, industrials, staples) is not a parameter.

### `drop_and_renormalise`

```python
drop_and_renormalise(weights, names, spec, sectors=None) -> Series
```

Remove `names` (filing breaches), renormalise to 1, and re-apply the name cap and the sector cap. The engine calls this after the monthly selection, before multiplying by exposure.

---

## Overlay

### `regime`

```python
regime(data, spec, sessions) -> DataFrame
```

One row per session. Columns:

| Column | Meaning |
| --- | --- |
| `raw` | Close is above the moving average today. |
| `on` | Switch state after band and confirmation. |
| `exposure` | Number in `[0, 1]` the engine multiplies into target weights. |

```python
from monterey.layers import regime
frame = regime(rd, spec, rd.sessions)
frame.loc["2022-06-30", ["raw", "on", "exposure"]]
```

`kind: "none"` sets `on` and `raw` true and `exposure` to 1, then still applies `vol_target` if you set one. Any other `kind` raises `ValueError`.

The series is indexed by the close that decided it. The engine reads `exposure` at close `t` and the resulting orders fill at open `t+1`.

`off_exposure` is a fraction of the **stock** book. It is not a yield on cash. Cash is whatever NAV is left after `target weight × NAV` is spent on shares.

A brake on this book's own peak-to-trough path cannot be expressed here. `regime` runs in `Simulator.__init__`, before any NAV exists. That rule has to read `state.last_nav` inside `step`.

---

## Execution

Both functions work on any object with `.cash` (float) and `.positions` (`dict[symbol, shares]`). The simulator and the ops account share them.

### `equity`

```python
equity(account, closes) -> float
```

Cash plus shares marked at `closes`. A symbol with no positive price contributes nothing.

### `plan_orders`

```python
plan_orders(account, targets, closes, spec, *, as_of, reasons=None, default_reason="rebalance", exits_only=False, cost_bps=None) -> list[dict]
```

Orders that move holdings to `targets` (symbol → weight) at `closes`.

```python
from monterey.layers import plan_orders
orders = plan_orders(state, targets, closes, spec, as_of="2024-01-02", default_reason="monthly rebuild")
```

A name with weight 0 and shares still held is always a sell. `exits_only=True` (the engine sets this when `rebalance` is `"on_signal"` and nothing triggered) drops every other order.

For a name that stays in the book, the share change is `round(target_shares - held)`. The order is skipped when that rounds to 0, when notional is below `min_trade`, or when `drift_band > 0` and the weight gap is inside the band. `cost_bps` defaults to `spec.accounting["cost_bps"]` and is stored as `est_cost`. It is not charged here.

Each order dict carries `symbol`, `side`, `shares`, `target_weight`, `current_weight`, `drift`, `price_ref`, `notional`, `est_cost`, `created_as_of`, `status` (`"pending"` or `"rejected"`), `reason`. `"rejected"` with reason `"no close"` means there was no price.

### `fill_orders`

```python
fill_orders(account, orders, quotes, *, day, price_field, cost_bps=0.0) -> list[dict]
```

Sells first, then buys. A sell is capped at the whole shares held. A buy is capped at the cash on hand, cost included (`affordable = cash // (price * (1 + cost_bps/10000))`). Status is `"filled"`, `"partial"`, or `"rejected"`.

```python
fills = fill_orders(state, orders, opens, day="2024-01-03", price_field="open", cost_bps=10.0)
```

`price_field` is recorded on the fill (`"open"` or `"close"`). It does not choose the quote. `quotes` does. A missing quote rejects with detail `"no price"`. Cost leaves cash on both sides.

Whole-share rounding is why a tiny residual can survive a breach sale. `breach_complete` does not use this function for that residual. It uses `fill_flatten`.

### `fill_flatten`

```python
fill_flatten(account, orders, quotes, *, day, price_field, cost_bps=0.0) -> list[dict]
```

Sell the residual in full, including a fraction `int(round(...))` would have dropped. A missing quote rejects with detail `"no print"` and the shares stay. The engine then tries the next session, using that session's real open, or its real close if the open did not print. A forward-filled price is not used.

---

## Accounting

### `settle_dividends`

```python
settle_dividends(account, holders, dividends, impure, spec, *, day) -> list[dict]
```

Credit dividends to `holders` (symbol → shares at the **prior** close). `dividends` is an iterable of `(symbol, per_share)`. `impure` is `symbol → ratio`.

```python
from monterey.layers import settle_dividends
rows = settle_dividends(state, state.positions, paid, rd.impure_ratios(day), spec, day="2024-03-15")
```

Each credit is a cashflow row with `type: "dividend"` and a positive `amount`. When `spec.accounting["purify"]` is `"ex_date"` and the ratio is positive, a second row with `type: "purification"` and a negative amount leaves cash. `"off"` keeps the gross dividend. The function returns `[]` and does nothing when `holders` have no shares in the paying names.

The engine calls this only on sessions that have a dividend. A yield on idle cash would be a separate call, every session, and a new `accounting` key. That key does not exist yet.

---

## Simulator

### `simulate`

```python
simulate(spec, data, start=None, end=None, *, root=None, mode="replay", state=None, progress=False) -> Ledger
```

Step every session in `[start, end]` and return the ledger. `run_book` is the notebook wrapper. Call `simulate` when you already hold a `BookSpec` and want to choose the folder yourself.

```python
from monterey import BookSpec
from monterey.sim.engine import simulate

spec = BookSpec.load("fcf-sma-v2-baseline").replace(id="spus-sma", overlay={"ticker": "SPUS"})
ledger = simulate(spec, rd, "2020-01-02", "2026-09-30", root=None, progress=True)
```

**start, end**
Default to `data.start` and `data.end`. Sessions are SPY trading days inside the range.

**root**
Passed to `ledger.write`. `None` keeps the result in memory.

**mode**
Stored on the manifest (`"replay"`, `"experiment"`). It does not change the trades.

**state**
A `SimState` to resume from. Default is cash equal to `accounting.capital` and no positions.

**progress**
Print NAV every 250 sessions.

`SimState` fields a layer change might read or set: `cash`, `positions`, `pending` (orders waiting for the next open), `exposure`, `snapshot` (fundamentals stamp), `breached` (symbol → filed date), `last_nav`, `last_targets`, `last_day`.

While `screen.breach_complete` is true, a name in `breached` stays there until the share count is ~0, including across a new month-end snapshot. Each session it is still held writes an event `type: "breach_wait"`.

---

## Ledger

```text
ledgers/<book id>/<spec hash>/
    spec.yaml  manifest.json  diagnostics.json
    nav.parquet  positions.parquet  orders.parquet
    fills.parquet  cashflows.parquet  events.parquet
```

Experiment runs nest one level deeper: `ledgers/experiments/<paper>/<book id>/<spec hash>/`.

```python
ledger.nav_series()                 # NAV indexed by date, name = spec.id
ledger.nav, ledger.positions, ledger.fills, ledger.orders, ledger.cashflows, ledger.events
Ledger.read("ledgers/fcf-sma-v2-baseline/6ca86844209e")
```

### `nav` columns

`date`, `nav`, `cash`, `invested`, `daily_return`, `exposure`, `regime_on`, `regime_raw`, `n_positions`, `n_targets`, `n_fills`, `n_orders`, `traded_notional`, `costs`, `dividends`, `purification`, `snapshot`, `max_gap`.

`max_gap` is the largest absolute weight gap between holdings and targets after that session's fills. `exposure` is the overlay number, not the fraction of NAV that prices say is invested (that fraction is `invested / nav`).

### `positions` columns

`date`, `symbol`, `shares`, `price`, `value`, `weight`, `target_weight`, `invested_weight`, `sector`, `screen_reason`, `score`, `market_cap`, `debt_ratio`, `cash_ratio`, `receivables_ratio`.

`weight` is mark-to-market. `invested_weight` is the construction weight before exposure. `target_weight` is `invested_weight × exposure`. A row is written for every targeted name and every name still held, including a breach residual.

### Other tables

**orders** — created at the close. `side`, `shares`, `target_weight`, `current_weight`, `drift`, `notional`, `est_cost`, `status`, `reason`.

**fills** — executions. `price`, `notional`, `cost`, `price_field` (`open` or `close`), `status`, `reason`, `detail`.

**cashflows** — `type` is `dividend` (positive), `purification` (negative), or `cost` (negative, one row per session that traded).

**events** — `type` is `rebuild`, `switch`, `breach`, `breach_wait`, or `delisted`. `detail` is a short sentence.

```python
waits = ledger.events[ledger.events["type"] == "breach_wait"]
still = ledger.positions[ledger.positions["shares"] > 0]
```

---

## Scores

### `stats`

```python
stats(nav: Series) -> dict
```

`total_return`, `cagr`, `volatility`, `max_drawdown`, `calmar` (CAGR / |max drawdown|), `sharpe`, `sortino`, `var_95`, `cvar_95`, plus the peak and trough dates. Sharpe and Sortino use a 2% annual risk-free rate and 252 sessions. Volatility is the annualised standard deviation of daily returns.

```python
from monterey.diagnostics import stats, yearly
stats(ledger.nav_series())
yearly(ledger.nav_series())    # index: year. columns: return, intra_year_drawdown, year_end
```

### `relative`

```python
relative(fund: Series, bench: Series) -> dict
```

`beta`, `tracking_error`, `alpha`, `correlation`, `up_capture`, `down_capture` versus one benchmark, on daily returns aligned to `fund`.

### `scorecard` and `compare`

```python
scorecard(source, label=None) -> dict
compare(ledgers, data=None, benchmarks=True) -> DataFrame
```

`compare` stacks one `scorecard` per ledger and, when `data` is passed, a total-return row for SPUS and SPY over the first ledger's dates.

```python
compare([base, trial], rd)
```

Columns include `total_return`, `cagr`, `volatility`, `max_drawdown`, `calmar`, `sharpe`, `sortino`. Ledger rows also include `turnover` (one-way, annualised), `costs_pct`, `dividends_pct`, `avg_exposure`, `switches`, `hash`.

### `score_against_baseline`

```python
score_against_baseline(candidate, baseline, data) -> dict
```

Frozen kill rules. Pass ledgers, not the comparison table.

```python
verdict = score_against_baseline(trial, base, rd)
verdict["killed"]     # bool
verdict["reasons"]    # list of strings, empty when the bars pass
```

A reason is appended when any of these is true:

1. 2022 calendar return is more than 5 percentage points worse than SPUS.
2. Train max drawdown (2020-01-02 → 2022-12-31) is worse than SPUS.
3. Train Calmar is below both the v2 baseline and SPUS.
4. 2023 calendar return is more than 15 percentage points worse than the v2 baseline.

The dict also carries `candidate`, `baseline`, and `train` stat blocks.

### `diagnose`

```python
diagnose(ledger, data=None, benchmarks=("SPUS", "SPY"), write=True) -> dict
```

The full audit: performance, yearly, trading, concentration, sector mix, breach handling, purification, and (when `data` is passed) benchmark-relative figures. `write=True` saves `diagnostics.json` next to the ledger when `ledger.path` is set. `run_sprint` calls this on every variant.

```python
from monterey.diagnostics import diagnose
diag = diagnose(trial, rd)
diag["compliance"]["breaches"]
diag["sectors"]
```

`write_audit(diag, path, title=...)` turns that dict into a markdown report. `python -m monterey v2-baseline` writes `Research/diagnostics/v2-baseline.md` this way. That file is gitignored.

---

## Which argument a paper sets

Change one section. Leave the other six on v2. Papers 16–20 already have notebooks. `run_sprint` builds them.

| Paper | Call | Argument |
| --- | --- | --- |
| 16 Honest throttle | `run_sprint("16", rd)` | `overlay`: `kind`, `confirm_days`, `band`, `off_exposure`, `vol_target` |
| 17 PIT universe | `run_sprint("17", rd)` | `universe`: `pit=False` is the leak being measured. The live rule stays `pit=True`. |
| 18 Execution | `run_sprint("18", rd)` | `execution`: `rebalance`, `drift_band`, `min_trade` |
| 19 FCF layers | `run_sprint("19", rd)` | `signal`: `brain="fcf_layers"` and one of `conversion_min`, `stability_min_positive`, `yield_drop_quantile` |
| 20 Sector lid | `run_sprint("20", rd)` | `construction`: `sector_cap`, `name_cap` |
| 23 SPUS throttle | `run_book` | `overlay={"ticker": "SPUS"}`. A rule that needs SPY and SPUS both on is a new `overlay.kind`. |
| 26 Exit completeness | `run_book` | `screen={"breach_complete": True}`. The notebook then counts `breach_wait` events and residual shares. The behavior is already in `step`. |

These October ideas have no argument yet. Adding one is [the next section](#adding-a-knob).

| Paper | What is missing |
| --- | --- |
| 21 Halal cash | A yield on idle cash. `off_exposure` still holds stocks. |
| 22 NAV brake | A cut based on this book's peak NAV. `regime()` cannot see NAV. |
| 24 FCF floor | An absolute FCF-margin cutoff that does not backfill to `min_holdings`. `keep_quantile` is a rank. |
| 25 Sector floors | A minimum weight for sectors already in the book. `sector_cap` is a ceiling. |
| 27 Activity list | A tighter ban than `EXCLUDED_ACTIVITIES`, plus an allow list for names such as Visa. `"Financials"` currently passes. |

---

## Adding a knob

A new rule needs a key in `DEFAULTS` (`monterey/spec.py`) before `run_book` will accept it. Unknown keys raise. Then the one layer that owns the decision reads `spec.<section>["<key>"]`. The engine already calls that layer. You only change the engine when the decision depends on cash, shares, or NAV partway through the day.

`breach_complete` is the pattern to copy. The key lives on `screen`. The sell logic lives in `step`, because it has to remember a residual across sessions. The notebook only passes the flag:

```python
complete = run_book(
    "fcf-sma-v2-baseline", rd,
    paper="26-forced-exit-completeness",
    id="complete",
    screen={"breach_complete": True},
)
```

For a knob that is a pure function of that day's inputs, the layer file is enough. A sector floor belongs in `construction.py`, next to `apply_sector_cap`, and `build_weights` calls it when the new key is set. A hard FCF floor belongs in `brains.py` as a parameter of `fcf_quality` or as its own `@brain`. A second price series for the switch belongs in `regime()`.

After the key exists, confirm the hash moved and the other sections did not:

```python
trial.spec.hash()
trial.spec.summary()
```

Score it with `compare([base, trial], rd)` and `score_against_baseline(trial, base, rd)`. If the question is a count (name-days in breach, sessions in cash, sector weight), read `ledger.positions`, `ledger.nav`, or `ledger.events` directly. `compare` only sees the NAV path.

---

## Exemplars

Copy a whole cell. Change the placeholders. Leave the other six spec sections on v2.

Placeholders in this section:

| Token | Replace with |
| --- | --- |
| `paper-xx-slug` | `rd.manifest["paper"]`. Example: `"paper-20-concentration"`. |
| `xx-slug` | Folder under `ledgers/experiments/`. Example: `"20-concentration"`. |
| `trial-id` | Book `id`. Becomes the ledger folder and the `compare` row name. |
| `section={...}` | One of `universe`, `screen`, `signal`, `construction`, `overlay`, `execution`, `accounting`. Unknown keys raise before any session runs. |

These cells are situations, not papers. A construction lid, an overlay ticker, and a screen flag all use Exemplar B. They differ only in the `section={...}` dict. [Which argument a paper sets](#which-argument-a-paper-sets) says which dict that paper uses.

### A. First cell

Puts the repo on `sys.path`, loads facts from 2019-12-01, prints the snapshot hash, and simulates the unchanged v2 book.

```python
import subprocess
import sys
from pathlib import Path

def _repo_root() -> Path:
    start = Path.cwd().resolve()
    for candidate in (start, *start.parents):
        if (candidate / "monterey" / "__init__.py").exists():
            return candidate
    raise FileNotFoundError(f"Monterey repo root not found from {start}")

_ROOT = _repo_root()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
try:
    import monterey  # noqa: F401
except ModuleNotFoundError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-e", f"{_ROOT}[research]"])

from monterey.research import boot, compare, run_book
from monterey.sprints import score_against_baseline
from monterey.spec import BookSpec

rd = boot("paper-xx-slug", start="2019-12-01", end="2026-09-30")
print("snapshot", rd.manifest.get("hash"))
print("v2 hash", BookSpec.load("fcf-sma-v2-baseline").hash())

base = run_book(
    "fcf-sma-v2-baseline",
    rd,
    paper="xx-slug",
    id="v2",
)
```

`run_book` simulates **2020-01-02 → 2026-09-30** even when `boot` started in December 2019. First argument is the book name under `books/`. Second is `rd`. `paper` and `id` are not spec sections.

### B. One trial against v2

Same book, one section changed. Then the scorecard and the kill rules.

```python
trial = run_book(
    "fcf-sma-v2-baseline",
    rd,
    paper="xx-slug",
    id="trial-id",
    construction={"sector_cap": 0.40},
)
compare([base, trial], rd)
verdict = score_against_baseline(trial, base, rd)
print(trial.spec.id, "KILLED" if verdict["killed"] else "keep", "; ".join(verdict["reasons"]) or "pass")
print("hash", trial.spec.hash())
trial.spec.summary()
```

Swap only the section keyword. Examples of the last argument, each a different situation:

```python
universe={"pit": False}
screen={"breach_complete": True}
signal={"brain": "fcf_layers", "params": {"conversion_min": 0.5, "min_holdings": 20}}
construction={"sector_cap": 0.40, "name_cap": 0.08}
overlay={"ticker": "SPUS"}
overlay={"kind": "none"}
execution={"drift_band": 0.01, "min_trade": 2500}
accounting={"cost_bps": 20.0}
```

Passing two sections in one `run_book` is allowed. It is no longer a one-knob test.

### C. Several trials (a grid)

Keep the baseline. Loop `(id, changes)` pairs. Score each trial against `base`, not against each other.

```python
variants = [
    ("trial-a", {"construction": {"sector_cap": 0.40}}),
    ("trial-b", {"construction": {"sector_cap": 0.50}}),
    ("trial-c", {"construction": {"name_cap": 0.08}}),
]
trials = []
for name, changes in variants:
    trials.append(
        run_book("fcf-sma-v2-baseline", rd, paper="xx-slug", id=name, **changes)
    )

compare([base, *trials], rd)
for trial in trials:
    verdict = score_against_baseline(trial, base, rd)
    print(trial.spec.id, "KILLED" if verdict["killed"] else "keep", "; ".join(verdict["reasons"]) or "pass")
```

`**changes` is how `run_book` receives a section dict stored in a variable. Writing `construction=changes` is wrong when `changes` is already `{"construction": {...}}`.

### D. Prepared sprint (papers 16–20 only)

The grid is already coded in `monterey.sprints`. Papers 21–27 are not in this table. Call Exemplar B or C for those.

```python
from monterey.sprints import run_sprint, score_against_baseline

ledgers, table = run_sprint("20", rd)
table

baseline, *rest = ledgers
for book in rest:
    verdict = score_against_baseline(book, baseline, rd)
    print(book.spec.id, "KILLED" if verdict["killed"] else "keep", "; ".join(verdict["reasons"]) or "pass")
```

### E. Inspect a layer without a full run

Use this when the question is “did the lid / screen / switch bind on this date?” A full sim is not required.

```python
import pandas as pd
from monterey.layers import screen, build_weights, regime
from monterey.layers.signals import Context, run_brain
from monterey.spec import BookSpec

day = "2022-06-30"
spec = BookSpec.load("fcf-sma-v2-baseline").replace(
    id="trial-id",
    construction={"sector_cap": 0.40},
)

held = screen(rd, day, spec)
picked = run_brain(Context(data=rd, spec=spec, as_of=pd.Timestamp(day).date(), screen=held))
weights = build_weights(picked, spec, rd.sectors)

print("hash", spec.hash())
print("names", len(weights), "sum", float(weights.sum()))
print("max name", float(weights.max()) if len(weights) else None)
print(weights.groupby(weights.index.map(lambda s: rd.sectors.get(s, "unknown"))).sum().sort_values(ascending=False))

frame = regime(rd, spec, rd.sessions)
frame.loc[day, ["raw", "on", "exposure"]]
```

### F. Figures: NAV, drawdown, calendar years

The book has no revenue series. Plot NAV (growth of $1) and drawdown. `boot(..., figures=True)` creates `./figures` in the notebook directory.

```python
import matplotlib.pyplot as plt
import pandas as pd
from monterey.diagnostics import yearly

books = [base, *trials]
figures = Path("figures")
figures.mkdir(exist_ok=True)

spus = rd.total_return("SPUS").reindex(base.nav_series().index).ffill()

fig, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
for book in books:
    nav = book.nav_series()
    axes[0].plot(nav.index, nav / nav.iloc[0], label=book.spec.id)
    dd = nav / nav.cummax() - 1.0
    axes[1].plot(dd.index, dd, label=book.spec.id)
axes[0].plot(spus.index, spus / spus.iloc[0], label="SPUS", alpha=0.7)
axes[0].set_title("Growth of $1")
axes[0].legend()
axes[1].set_title("Drawdown from peak")
axes[1].legend()
fig.tight_layout()
fig.savefig(figures / "nav-and-drawdown.png", dpi=140)
plt.show()

calendar = pd.concat({book.spec.id: yearly(book.nav_series())["return"] for book in books}, axis=1)
calendar["SPUS"] = yearly(spus)["return"]
calendar
```

A topic is not finished at `compare`. Save the figure. If the trial is a cap or a screen, also plot the quantity the rule claims to change (Exemplar G).

### G. A count `compare` cannot see

`compare` only sees the NAV path. Sector mix, residual shares, cash days, and event types live on the ledger tables.

```python
import pandas as pd
from monterey.diagnostics import diagnose

diag = diagnose(trial, rd)
diag["sectors"]
diag["compliance"]["breaches"]

pos = trial.positions.copy()
pos["date"] = pd.to_datetime(pos["date"])
live = pos[pos["invested_weight"].astype(float) > 0]
by_sector = (
    live.groupby(["date", "sector"])["invested_weight"].sum()
    / live.groupby("date")["invested_weight"].sum()
)
by_sector.groupby("sector").mean().sort_values(ascending=False)

events = trial.events
events["type"].value_counts()
events[events["type"] == "breach_wait"].head()

cash_days = (trial.nav["invested"] / trial.nav["nav"] < 0.05).sum()
print("near-cash sessions", int(cash_days))
```

Change the filter. The pattern is: load a ledger table, group, count.

### H. Reopen a ledger already on disk

Skip the sim when `nav.parquet` is already written.

```python
from monterey.ledger import Ledger

base = Ledger.read("ledgers/fcf-sma-v2-baseline/6ca86844209e")
trial = Ledger.read("ledgers/experiments/xx-slug/trial-id/<spec hash>")
compare([base, trial], rd)
```

`v2_baseline_ledger()` in `monterey.sprints` reads that v2 folder when it exists. `v2_snapshot_hash()` is the snapshot stamped on it. Pass that to `boot(..., snapshot=)` when the notebook must use the same facts as the scored book.

### I. New key, then the same notebook

The notebook does not invent a parameter. Add the key to `DEFAULTS` in `monterey/spec.py`, read it in the one layer that owns the decision, then call Exemplar B with that key. Unknown keys raise.

```python
trial = run_book(
    "fcf-sma-v2-baseline",
    rd,
    paper="xx-slug",
    id="trial-id",
    screen={"breach_complete": True},
)
assert trial.spec.hash() != base.spec.hash()
compare([base, trial], rd)
score_against_baseline(trial, base, rd)
```

If the hash did not move, the key was dropped or never reached the spec. If it moved and `spec.summary()` shows a second section changed, the replace was too wide.
