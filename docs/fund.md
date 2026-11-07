# Fund codebase

This file is the working reference for the paper Halal equity fund: how the book is specified, how each layer decides, how one session is stepped, and how ops and the desk sit on top of that. It is written for people who are changing those layers. Research notebooks, paper write-ups, and the October sprint helpers are out of scope here. The research function list for those notebooks is [`Research/pipeline.md`](../Research/pipeline.md).

The live book is `books/fcf-sma-v2-baseline.yaml`. Its spec hash is `6ca86844209e`. Package `monterey` is 0.2.0. Market facts come from `halalquant` 0.4.0. Live sessions, history replays, and any other run that marks NAV all go through `monterey.sim`. There is not a second production engine.

Do not score new work against the archived v1 ledger under `ledgers/fcf-sma-v1/`. That book used today’s S&P 500 list, did not apply the sector screen, did not credit dividends, and did not charge costs.

## On this page

- [What the fund is](#what-the-fund-is)
- [Folders](#folders)
- [How a session runs](#how-a-session-runs)
- [Commands](#commands)
- [BookSpec](#bookspec)
- [Market facts](#market-facts)
- [Universe](#universe)
- [Screen](#screen)
- [Brains](#brains)
- [Construction](#construction)
- [Overlay](#overlay)
- [Execution](#execution)
- [Accounting](#accounting)
- [Simulator](#simulator)
- [Ledger](#ledger)
- [Diagnostics](#diagnostics)
- [Ops](#ops)
- [Desk](#desk)
- [Changing a layer](#changing-a-layer)
- [Inspecting a layer without a full run](#inspecting-a-layer-without-a-full-run)
- [Tests](#tests)

---

## What the fund is

Monterey Finance runs a paper Halal equity book. Starting cash is $1,000,000. NAV is the cash on the paper account plus shares marked at that session’s close. A decision taken at the close of session `t` fills at the open of session `t+1`. The first session of a new ledger fills at that day’s close so a NAV exists.

The live rule set is:

| Layer | Live rule |
| --- | --- |
| Universe | S&P 500 members on that date (`pit: true`) |
| Screen | Banned activities plus AAOIFI debt / cash / receivables at 30 / 30 / 70. A failed 10-Q or 10-K sells at the next open |
| Brain | `fcf_quality`: top half of compliant names by FCF / sales, at least 20 names |
| Construction | Cap-weighted, 10% single-name cap, dual share classes collapsed. No sector cap |
| Overlay | Whole NAV in cash when SPY is below its 200-day simple moving average |
| Execution | Re-target every name every session. Skip a non-exit under $100. Whole shares. Sells before buys |
| Accounting | Dividends credited on the ex-date. 10 bp charged on every fill. Impure dividend slice leaves cash on the ex-date |

The engine calls the layers. The layers do not call each other in a long chain of their own. Universe returns membership. Screen adds a Halal verdict. The brain ranks the passing names and returns `symbol`, `score`, and `market_cap`. Construction turns that table into weights that sum to 1. Overlay returns one exposure number in `[0, 1]`. The engine multiplies: `target weight = invested weight × exposure`. Execution turns those targets into whole-share orders and fills. Accounting credits dividends and takes purification. Cash is leftover NAV, not a second stock list.

---

## Folders

```text
books/                         YAML BookSpec files. One file per book id.
monterey/
    spec.py                    BookSpec load, merge, hash, replace
    paths.py                   ROOT, BOOKS, LEDGERS, SNAPSHOTS
    data/                      ResearchData: membership, prices, filings, snapshots
    layers/                    universe, screen, brains, construction, overlay, execution, accounting
    sim/engine.py              Simulator, SimState, simulate()
    ledger.py                  parquet tables every run writes
    diagnostics/               stats, diagnose, diagnostics.json
ops/
    fund.py                    live session and catch-up replay on monterey.sim
    live_rules.py              LIVE_BOOK and live_spec()
    ruleset.py                 propose / confirm overlays on the live spec
    cli.py                     python -m ops
    session.py, pipeline.py    older SleeveBook path, used by --targets-only
desk/                          TUI. Reads ledgers. Does not trade.
ledgers/<book id>/<spec hash>/ official NAV and holdings for that hash
data/snapshots/<hash>/         frozen market facts (gitignored)
ops/state/                     paper account, halt, audit, rules overlay, nav.csv mirror
```

`monterey.legacy.sleeves` is the frozen selector and weighting code that some brains still call. Do not add new live behaviour there. Put new live behaviour in `monterey/layers/` and, if the decision needs cash, shares, or NAV mid-session, in `monterey/sim/engine.py`.

`ops/session.py` still builds an `IntendedBook` through `ops/targets.py` and trades it through `ops/pipeline.py`. That path is what `--targets-only` uses. Weekday production is `ops.fund.run_live_session`. If you change a live layer, change `monterey/layers/` and confirm `ops.fund` still steps the same spec. Do not assume a change in `ops/pipeline.py` is what the live session runs.

---

## How a session runs

`Simulator.step` does this order for session `t`. Nothing decided at close `t` earns the return of day `t`.

1. **Dividends.** Holders at the prior close receive dividends whose ex-date is `t`. If purification is on, the impure slice leaves cash. If `accounting.cash_yield` is set, idle cash is credited for this session.
2. **Fills.** Orders written at close `t−1` fill at open `t`. Sells first. Buys stop when cash, including cost, runs out. Cost leaves cash.
3. **Targets.** Overlay exposure for this close (capped by the NAV brake if that key is set). Monthly selection, reused until the fundamentals snapshot stamp changes. Filing breaches known by `t`. Then `target weight = invested weight × exposure`.
4. **Orders.** Written at close `t`, held for open `t+1`. The first session fills at the close.
5. **Delistings.** A held name with no price for 7 sessions is cashed at its last close.
6. **Mark.** NAV, positions, orders, fills, cashflows, and events for this close.

The stock list is cached on the fundamentals stamp. Daily work is the overlay, breaches, and share counts drifting as prices move.

---

## Commands

```bash
pip install -e ".[dev]"

python -m monterey run fcf-sma-v2-baseline --start 2020-01-02 --end 2026-09-30
python -m ops run --as-of today
python -m ops run --as-of today --skip-refresh
python -m ops replay --start 2020-01-02 --end 2026-09-30
python -m ops health
python -m ops rules propose --actor ada --reason "tighter name cap" --name-cap 0.08
python -m ops rules confirm --id <proposal> --actor ada
python -m desk
```

`python -m monterey run` loads the YAML, loads market facts, steps every session, writes `ledgers/<id>/<hash>/`, and writes `diagnostics.json`.

`python -m ops run` loads the live spec (plus any confirmed overlay in `ops/state/rules_overlay.json`), steps that one date, writes the same ledger layout, mirrors `ops/state/nav.csv` and `ops/state/account.json`, and skips the day if it is already marked or the account is halted.

`python -m ops replay` walks a date range on `monterey.sim`, resuming from the last marked session when a ledger already exists.

The weekday GitHub Action at 22:30 UTC installs the package, pulls the cache and ledgers from R2, catch-up replays the live book, commits `spec.yaml`, `nav.parquet`, `diagnostics.json`, and the nav CSV, and uploads the rest of the ledger and cache back to R2.

---

## BookSpec

One declarative description of a book. Seven sections. Defaults fill any key the YAML omits. The hash covers the rules only, so two runs with the same hash traded the same way.

```python
from monterey.spec import BookSpec

spec = BookSpec.load("fcf-sma-v2-baseline")
spec.hash()          # "6ca86844209e"
spec.summary()       # list of (label, value) for a terminal or a caption
spec.replace(id="trial", overlay={"confirm_days": 2})
```

### `BookSpec.load`

```python
BookSpec.load(path) -> BookSpec
```

`path` is a filesystem path or a name under `books/` (`"fcf-sma-v2-baseline"`). Unknown YAML keys raise `ValueError`.

### `BookSpec.replace`

```python
spec.replace(*, id=None, label=None, **sections) -> BookSpec
```

Return a new spec. Section dicts are merged, key by key. `signal.params` is merged one level deeper, so you can change `keep_quantile` without restating `min_holdings`.

```python
spec.replace(signal={"params": {"keep_quantile": 0.4}})
spec.replace(construction={"sector_cap": 0.40, "name_cap": 0.08})
```

An unknown section or an unknown key inside a section raises `ValueError` before any session runs.

### `BookSpec.hash`

```python
spec.hash() -> str   # 12 hex characters
```

SHA-256 of the seven sections, keys sorted. `id`, `label`, `description`, and `benchmarks` are not in the hash.

These keys are dropped from the hash when they are off, so turning them on is what moves the v2 hash: `screen.breach_complete` when false, `construction.sector_floors` when empty, `accounting.cash_yield` when empty, and `overlay.nav_brake` (with `nav_brake_off` and `nav_brake_recover`) when empty.

### `BookSpec.save`

```python
spec.save(path) -> Path
```

Write YAML. The simulator writes `spec.yaml` next to every ledger this way.

### Section arguments

These are the keys `replace` accepts. Defaults are the v2 book unless a row says otherwise.

#### `universe`

| Key | Default | Meaning |
| --- | --- | --- |
| `index` | `"sp500"` | Index name passed to the data layer. |
| `pit` | `True` | `True`: members on that date. `False`: the snapshot’s end-date list, pasted onto every past date. |

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
| `weight` | `"cap"` | `"cap"` uses market cap. `"equal"` uses 1/N. `"score"` uses the brain’s score, floored at 0. |
| `name_cap` | `0.10` | Max weight of one name. `None` leaves weights uncapped. |
| `sector_cap` | `None` | Max weight of one sector. `None` leaves sectors uncapped. |
| `sector_floors` | `None` | Min weight per sector already on the selected list. A dict of GICS label → floor. Labels match case-insensitively. A floor with no names in the selection is skipped. |
| `collapse_share_classes` | `True` | Keep the larger listing of a dual class, then renormalise. |

Weights from this section sum to 1. The overlay has not been applied yet.

#### `overlay`

| Key | Default | Meaning |
| --- | --- | --- |
| `kind` | `"spy_sma"` | `"spy_sma"` is the moving-average switch on `ticker`. `"none"` (or `"off"` or `""`) is always invested, exposure 1, before any vol target. `"both_sma"` is on only when SPY and `ticker` are on. `"either_sma"` is on when either is on. |
| `ticker` | `"SPY"` | Price series the switch reads. `"SPUS"` is a valid ticker. For `both_sma` / `either_sma`, this is the second series. |
| `window` | `200` | Sessions in the simple moving average. |
| `confirm_days` | `0` | The switch flips after more than this many consecutive closes on the other side of the line. `0` flips on the first close. `2` flips on the third. |
| `band` | `0.0` | Hysteresis. On above `sma * (1 + band)`, off below `sma * (1 - band)`. |
| `off_exposure` | `0.0` | Fraction of the stock book kept when the switch is off. `0.5` still owns those stocks, at half size. |
| `vol_target` | `None` | Annualised volatility target on `ticker`. Exposure is scaled down to it, in steps of 5%. `None` turns it off. |
| `vol_lookback` | `20` | Sessions of daily returns used for that realised vol. |
| `nav_brake` | `None` | Cut when this book’s prior NAV is this far below its own peak. `0.12` is a 12% trailing stop. Applied in `step`, not in `regime()`. |
| `nav_brake_off` | `0.0` | Exposure while the NAV brake is on. |
| `nav_brake_recover` | `0.5` | Stay braked until NAV has recovered this share of the loss from the peak that triggered. `0` waits for a new high. |

`regime()` builds the SMA series once, before the first session, from prices. It does not see the book’s own NAV.

#### `execution`

| Key | Default | Meaning |
| --- | --- | --- |
| `signal_lag` | `"next_open"` | Orders written at the close fill at the next open. |
| `rebalance` | `"daily_to_target"` | `"daily_to_target"` trades every name back to target each session. `"on_signal"` trades on a new snapshot, a switch flip, a breach, and the first session. |
| `drift_band` | `0.0` | Skip a name already held when `abs(target weight − current weight)` is below this. Exits are still sold. |
| `min_trade` | `100.0` | Skip a non-exit whose notional is below this many dollars. |
| `first_fill` | `"close"` | The first session fills at that day’s close, so a NAV exists. Later sessions fill at the next open. |

#### `accounting`

| Key | Default | Meaning |
| --- | --- | --- |
| `capital` | `1_000_000.0` | Starting cash. |
| `dividends` | `True` | Credit the dividend to holders of the prior close. |
| `cost_bps` | `10.0` | Commission on each fill, in basis points of notional. Charged inside the fill, taken out of cash. |
| `purify` | `"ex_date"` | `"ex_date"` donates `impure ratio × gross dividend` on the ex-date. `"off"` keeps it. |
| `purify_uncredited` | `False` | Donate even when `dividends` is false. v1 parity only. |
| `cash_yield` | `None` | Annual yield on idle cash, credited each session as `(1 + y)**(1/252) − 1`. |

Idle cash earns zero unless `cash_yield` is set. `off_exposure` still holds stocks; it is not this yield.

#### `benchmarks`

Default `("SPUS", "SPY")`. Reported beside the book. Not part of the hash.

---

## Market facts

Every fact a book needs is loaded once into `ResearchData`. Live and replay call `load_research_data`. The object is the same one notebooks use.

```python
from monterey.data import load_research_data

rd = load_research_data("2020-01-02", "2026-09-30")
rd.members("2022-06-30", pit=True)
rd.halal("2022-06-30", pit=True, sectors=True, debt=0.30, cash=0.30, receivables=0.70)
rd.describe()
```

### `load_research_data`

```python
load_research_data(start, end, *, index="sp500", lookback_days=420, symbols=None, snapshot=True, refresh=False, root=None, store=None, progress=True) -> ResearchData
```

Read the local `halalquant` cache. Symbols are every index member at any point in the window (leavers included) plus today’s list and `SPY` / `SPUS`. Prices start `lookback_days` earlier than `start` so a 200-day average exists on day one. With `snapshot=True` the frames are frozen under `data/snapshots/<hash>/` and reused until the cache changes. Pass `refresh=True` to rebuild that freeze.

### `ResearchData` methods the engine uses

**`members(as_of, pit=True)`** → `list[str]`
Index members on `as_of`. `pit=False` uses the snapshot end date for every call. If membership stints are empty, this returns today’s list.

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

**`sessions` / `sessions_between(start, end)`**
Trading days, defined as dates with a SPY close.

**`prices`**
Wide date × symbol frames: `open`, `close`, `adj_close`, `volume`. Signals use `adj_close`. Fills use `open` and `close`.

**`dividends_by_day`**
`dict[Timestamp, list[(symbol, dividend per share)]]`.

**`sectors`**
`dict[symbol, sector]`. A sector is allowed when its lowercased label is absent from this set: alcohol, tobacco, gambling, pork, weapons, defense, adult entertainment, conventional banking, conventional insurance, interest-based finance. A label such as `"Financials"` is allowed.

**`manifest["hash"]`**
Snapshot id. Same hash means the same facts.

AAOIFI ratios use 24-month market cap as the denominator when that column exists. Debt is `total_debt`. Cash is `cash_and_equiv` plus `interest_bearing_securities`. Receivables are `receivables` plus `liquid_assets`.

---

## Universe

File: `monterey/layers/universe.py`. Spec section: `universe`.

### `members`

```python
members(data, as_of, spec) -> DataFrame
```

Index members on `as_of`, using `spec.universe["pit"]`. This is membership only. No Halal test.

```python
from monterey.layers import members
members(rd, "2022-06-30", spec)   # symbol, sector, sector_allowed, in_index
```

To change who can enter the book before the Halal test, change `ResearchData.members` / `universe`, or add a key under `universe` in `DEFAULTS` and read it here. The engine does not call `members` itself. It calls `screen`, and `screen` asks `data.halal`, which starts from `data.universe`.

---

## Screen

File: `monterey/layers/screen.py`. Spec section: `screen`. Ratio math lives on `ResearchData.halal`. Filing exits live in `Simulator.step`, because they have to remember a residual across sessions.

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

The engine calls this inside `selection()`, then hands the table to the brain. Calling it yourself is how you audit the screen without a full run.

### `watch_list`

```python
watch_list(table, spec) -> DataFrame
```

Compliant names whose nearest ratio sits inside `spec.screen["watch_band"]` of its line. Columns: `symbol`, `ratio`, `value`, `line`, `gap`. An empty band returns an empty frame. This is an ops list. The simulator does not sell from it.

```python
from monterey.layers import screen, watch_list
watch_list(screen(rd, "2024-12-31", spec), spec)
```

### Filing breaches

`breach_exit` and `breach_complete` are screen keys. The sell is not in `screen.py`.

When `breach_exit` is `"next_open"`, `step` looks at `data.breaches_between` for names that are held or targeted, records an event of type `"breach"`, drops the name from invested weights through `drop_and_renormalise`, and plans a sell. The sale fills at the next open.

When `breach_complete` is true, a name in `state.breached` stays there until the share count is about zero, including across a new month-end snapshot. The residual is sold with `fill_flatten` at the next real open, or the real close if the open did not print. A forward-filled price is not used. Each session the name is still held writes an event `type: "breach_wait"`.

`report_only` writes the event and does not sell.

To tighten the activity list, change `EXCLUDED_ACTIVITIES` in `monterey/data/research_data.py` and confirm `sector_allowed` still matches what the board wants. `"Financials"` currently passes.

---

## Brains

Files: `monterey/layers/signals/registry.py`, `monterey/layers/signals/brains.py`. Spec section: `signal`.

A brain turns the screened names into a ranked table. It does not set weights, cash, or the SMA.

```python
@brain("name")
def name(ctx, **params) -> DataFrame:
    ...
```

The spec picks it with `signal.brain` and passes `signal.params` as keywords. The frame must contain `symbol`, `score`, and `market_cap`. Extra columns are stored on the position row when the ledger knows the column, and shown on the desk.

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

`run_brain` raises `KeyError` on an unknown name and `ValueError` if `symbol`, `score`, or `market_cap` is missing. An empty table means the whole book is cash after construction.

Importing `monterey.layers.signals` registers the built-in brains. A new brain is a function with `@brain("its_name")` in `brains.py` (or another module imported from `__init__.py`). Then set `signal.brain` to that name.

### `fcf_quality`

The live brain. Top slice of compliant names by FCF / sales.

```python
spec.replace(signal={"brain": "fcf_quality", "params": {"keep_quantile": 0.5, "min_holdings": 20}})
```

**keep_quantile** : float, default `0.5`
Keep names at or above the `(1 - keep_quantile)` quantile of FCF margin. `0.5` is the top half. This is a rank cutoff, not a margin of 50% or of 6%. Ignored when `margin_floor` is set.

**min_holdings** : int, default `20`
If the quantile cut leaves fewer names, fill back with the next-highest FCF margins until this count. If the whole positive-FCF pool is smaller than this, the brain returns an empty table. The floor path does not backfill.

**margin_floor** : float or None, default `None`
Absolute FCF / sales line (for example `0.06`, `0.08`, `0.10`). Names below it are out.

**drop_high_vol_quantile** : float or None, default `None`
Drop the highest-volatility slice of the selection. `None` keeps them. Not used on the floor path.

Positive FCF and a positive market cap are required before the cut. The score column is `fcf_margin`.

### `fcf_layers`

Starts from the same margin cut, then applies later layers whose parameters are not `None`. A layer that would leave fewer than `min_holdings` names is skipped for that date, and the previous stage is kept.

```python
spec.replace(signal={
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

These call the frozen paper-01–06 selectors. They are available. They are not the live book. `ops/ruleset.py` lists `roic`, `sue`, `dual_momentum`, and `high_beta` as forbidden sleeves for a live rules overlay.

| Brain | Params | Needs |
| --- | --- | --- |
| `roic` | `roic_min=0.15`, `keep_quantile=0.5`, `min_holdings=20` | `rd.extras["roic_history"]` |
| `dual_momentum` | `keep_quantile=0.2`, `min_holdings=15` | Prices through `as_of`. The SMA is the overlay, not this brain. |
| `high_beta` | `keep_quantile=0.2`, `min_holdings=8` | Prices. Halal tech and clean energy, top beta slice. |
| `sue` | `sue_threshold=2.0`, `hold_trading_days=21` | `rd.extras["sue_events"]` |

`load_research_data` does not load `roic_history` or `sue_events`. Calling those brains without placing the extra frames on `rd.extras` raises `ValueError`.

---

## Construction

File: `monterey/layers/construction.py`. Spec section: `construction`. Name-cap clipping is `apply_name_cap` in `monterey/legacy/sleeves/weighting.py`.

### `build_weights`

```python
build_weights(selected, spec, sectors=None) -> Series
```

The brain’s table becomes weights that **sum to 1**. This is the fully invested book, before exposure.

```python
from monterey.layers import build_weights
weights = build_weights(detail, spec, rd.sectors)   # index: symbol, values sum to 1
```

`spec.construction["weight"]` chooses cap, equal, or score. Dual classes collapse when `collapse_share_classes` is true. `apply_name_cap` then clips `name_cap`. A set `sector_cap` calls `apply_sector_cap`. A set `sector_floors` calls `apply_sector_floors`. An empty selection returns an empty series, and the book holds cash.

### `apply_name_cap`

```python
apply_name_cap(weights, cap) -> Series
```

Clip every name to `cap` and spread the leftover across names still under the cap, for up to 20 passes. `cap is None` returns the positive weights unchanged.

### `apply_sector_cap`

```python
apply_sector_cap(weights, sectors, cap, name_cap=None, iterations=50) -> Series
```

Scale any sector above `cap` down to it. Spread the excess over the other sectors in proportion to their current weight. Re-apply `name_cap` each pass. If every sector is over the lid, the last pass is kept and the lid is not met.

```python
from monterey.layers import apply_sector_cap
apply_sector_cap(weights, rd.sectors, cap=0.40, name_cap=0.10)
```

### `apply_sector_floors`

```python
apply_sector_floors(weights, sectors, floors, name_cap=None, iterations=50) -> Series
```

Scale any named sector below its floor **up** to that floor, taking the extra from other names already in the book, in proportion to the donor room above *their* floors. Re-apply `name_cap` each pass. A floor whose sector has no holdings is skipped. If donors have no room, the last pass is kept and the floor is not fully met.

```python
from monterey.layers import apply_sector_floors
apply_sector_floors(
    weights,
    rd.sectors,
    {"Health Care": 0.10, "Industrials": 0.10, "Consumer Staples": 0.05},
    name_cap=0.10,
)
```

### `drop_and_renormalise`

```python
drop_and_renormalise(weights, names, spec, sectors=None) -> Series
```

Remove `names` (filing breaches), renormalise to 1, and re-apply the name cap, the sector cap, and the sector floors. The engine calls this after the monthly selection, before multiplying by exposure.

A new size rule that is a function of that day’s selection belongs in this file. `build_weights` should call it when the new spec key is set. You do not change the engine for a lid or a floor.

---

## Overlay

File: `monterey/layers/overlay.py`. Spec section: `overlay`. The NAV brake is applied in `Simulator.step` because `regime()` runs before any NAV exists.

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

`kind: "none"` sets `on` and `raw` true and `exposure` to 1, then still applies `vol_target` if you set one. `both_sma` / `either_sma` combine SPY with `ticker`. Any other `kind` raises `ValueError`.

The series is indexed by the close that decided it. The engine reads `exposure` at close `t` and the resulting orders fill at open `t+1`.

`off_exposure` is a fraction of the **stock** book. It is not a yield on cash. Cash is whatever NAV is left after `target weight × NAV` is spent on shares.

### NAV brake

```python
# applied inside Simulator.step, not inside regime()
exposure = min(regime_exposure, _nav_brake_exposure(state, spec))
```

When `overlay.nav_brake` is set, `step` looks at `state.last_nav` versus `state.peak_nav`. If NAV is at least that far below the peak, exposure is cut to `nav_brake_off` until NAV has recovered `nav_brake_recover` of the loss from the peak that triggered. A switch event is written when exposure changes. If the brake is what changed, the event symbol is `"NAV brake"`.

A new overlay that is a function of a price series belongs in `regime()`. A new overlay that is a function of this book’s NAV belongs in `step`, next to `_nav_brake_exposure`.

---

## Execution

File: `monterey/layers/execution.py`. Spec section: `execution`. Cost rate also reads `accounting.cost_bps`.

Both functions work on any object with `.cash` (float) and `.positions` (`dict[symbol, shares]`). The simulator and the ops paper account share them.

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

Sell the residual in full, including a fraction `int(round(...))` would have dropped. A missing quote rejects with detail `"no print"` and the shares stay. The engine then tries the next session, using that session’s real open, or its real close if the open did not print.

A new skip rule (minimum ticket, drift band, lot size) belongs in `plan_orders`. A new fill constraint (cash, cost, partials) belongs in `fill_orders`. Timing (close versus next open) belongs in `step`, not in these two functions.

---

## Accounting

File: `monterey/layers/accounting.py`. Spec section: `accounting`.

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

The engine calls this only on sessions that have a dividend.

### `settle_cash_yield`

```python
settle_cash_yield(account, spec, *, day) -> list[dict]
```

Credit idle cash at `accounting.cash_yield` (annual) for one session. The cashflow type is `"cash_yield"`. The engine calls this every session when the key is set.

A new cash policy that is a function of holdings and the ex-date belongs in this file. A policy that needs NAV path or pending orders belongs in `step`.

---

## Simulator

File: `monterey/sim/engine.py`.

### `simulate`

```python
simulate(spec, data, start=None, end=None, *, root=None, mode="replay", state=None, progress=False) -> Ledger
```

Step every session in `[start, end]` and return the ledger.

```python
from monterey import BookSpec
from monterey.sim.engine import simulate

spec = BookSpec.load("fcf-sma-v2-baseline")
ledger = simulate(spec, rd, "2020-01-02", "2026-09-30", root=None, progress=True)
```

**start, end**
Default to `data.start` and `data.end`. Sessions are SPY trading days inside the range.

**root**
Passed to `ledger.write`. `None` keeps the result in memory. Ops and `python -m monterey run` pass `ledgers/`.

**mode**
Stored on the manifest (`"replay"`, `"experiment"`, `"live"`). It does not change the trades.

**state**
A `SimState` to resume from. Default is cash equal to `accounting.capital` and no positions.

**progress**
Print NAV every 250 sessions.

### `Simulator`

```python
sim = Simulator(spec, data, state=None)
out = sim.step("2024-01-03")   # dict of table name → list of row dicts
```

`__init__` precomputes `regime(data, spec, sessions)` and forward-fills prices by `STALE_ROWS` (7) for ordinary marks and fills. Completeness sells use the raw print, not that fill.

`selection(day)` screens, runs the brain, and builds weights, cached on the fundamentals stamp.

### `SimState`

Fields a layer change might read or set:

| Field | Meaning |
| --- | --- |
| `cash` | Paper cash |
| `positions` | symbol → shares |
| `pending` | orders waiting for the next open |
| `traded` | True after the first successful fill |
| `exposure` | Last overlay number applied |
| `snapshot` | Fundamentals stamp in force |
| `breached` | symbol → filed date |
| `last_close` | last real close used for delistings |
| `last_targets` | last target weights |
| `last_day` | last session label |
| `last_nav` | last marked NAV |
| `peak_nav` | peak NAV for the brake |
| `nav_braked` | whether the NAV brake is on |
| `brake_peak` | peak that triggered the brake |

The live loop stores this dict on `manifest["state"]` so the next weekday can resume.

Change the engine when the decision depends on cash, shares, pending orders, or NAV partway through the day. Do not put a pure ranking rule here.

---

## Ledger

File: `monterey/ledger.py`.

```text
ledgers/<book id>/<spec hash>/
    spec.yaml  manifest.json  diagnostics.json
    nav.parquet  positions.parquet  orders.parquet
    fills.parquet  cashflows.parquet  events.parquet
```

Experiment runs from notebooks nest one level deeper: `ledgers/experiments/<paper>/<book id>/<spec hash>/`. Git keeps `spec.yaml`, `manifest.json`, `nav.parquet`, and `diagnostics.json`. The other tables sync to R2.

```python
from monterey.ledger import Ledger, list_ledgers

ledger = Ledger.read("ledgers/fcf-sma-v2-baseline/6ca86844209e")
ledger.nav_series()                 # NAV indexed by date, name = spec.id
list_ledgers()                      # live folders first, then the rest by written_at
```

### `nav` columns

`date`, `nav`, `cash`, `invested`, `daily_return`, `exposure`, `regime_on`, `regime_raw`, `n_positions`, `n_targets`, `n_fills`, `n_orders`, `traded_notional`, `costs`, `dividends`, `purification`, `snapshot`, `max_gap`.

`max_gap` is the largest absolute weight gap between holdings and targets after that session’s fills. `exposure` is the overlay number, not the fraction of NAV that prices say is invested (that fraction is `invested / nav`). The engine also writes `cash_yield` on the nav row when a yield was credited. Extra columns are kept when present.

### `positions` columns

`date`, `symbol`, `shares`, `price`, `value`, `weight`, `target_weight`, `invested_weight`, `sector`, `screen_reason`, `score`, `market_cap`, `debt_ratio`, `cash_ratio`, `receivables_ratio`.

`weight` is mark-to-market. `invested_weight` is the construction weight before exposure. `target_weight` is `invested_weight × exposure`. A row is written for every targeted name and every name still held, including a breach residual.

### Other tables

**orders** — created at the close. `side`, `shares`, `target_weight`, `current_weight`, `drift`, `notional`, `est_cost`, `status`, `reason`.

**fills** — executions. `price`, `notional`, `cost`, `price_field` (`open` or `close`), `status`, `reason`, `detail`.

**cashflows** — `type` is `dividend` (positive), `purification` (negative), `cost` (negative, one row per session that traded), or `cash_yield` (positive).

**events** — `type` is `rebuild`, `switch`, `breach`, `breach_wait`, or `delisted`. `detail` is a short sentence.

```python
waits = ledger.events[ledger.events["type"] == "breach_wait"]
still = ledger.positions[ledger.positions["shares"] > 0]
```

### `Ledger.write` and `Ledger.append`

`write` dumps every table and the spec. `append` adds one session’s rows and replaces any rows already written for that date. The live session uses `append` so a weekday does not rewrite history.

If you add a column the desk or diagnostics should show, add it to `SCHEMAS` in `ledger.py` as well as to the row the engine writes. `_conform` will invent a missing schema column as null, and will keep extra columns that are not in the schema.

---

## Diagnostics

Package: `monterey/diagnostics/`. `diagnose` writes `diagnostics.json` next to the ledger. The desk Diagnostics tab reads that file. Ops calls `diagnose` after a live session and after a replay.

```python
from monterey.diagnostics import diagnose, stats, yearly, relative, scorecard

diag = diagnose(ledger, rd)
stats(ledger.nav_series())
yearly(ledger.nav_series())
```

### `stats`

```python
stats(nav: Series) -> dict
```

`total_return`, `cagr`, `volatility`, `max_drawdown`, `calmar` (CAGR / |max drawdown|), `sharpe`, `sortino`, `var_95`, `cvar_95`, plus the peak and trough dates. Sharpe and Sortino use a 2% annual risk-free rate and 252 sessions. Volatility is the annualised standard deviation of daily returns.

### `relative`

```python
relative(fund: Series, bench: Series) -> dict
```

`beta`, `tracking_error`, `alpha`, `correlation`, `up_capture`, `down_capture` versus one benchmark, on daily returns aligned to `fund`.

### `diagnose`

```python
diagnose(ledger, data=None, benchmarks=("SPUS", "SPY"), write=True) -> dict
```

Performance, yearly returns, trading, concentration, sector mix, breach handling, purification, and (when `data` is passed) benchmark-relative figures including switch cost. `write=True` saves `diagnostics.json` when `ledger.path` is set.

Keys you will read when checking a layer change:

| Key | What it answers |
| --- | --- |
| `diag["performance"]` | Path of this NAV |
| `diag["trading"]` | Turnover, fill counts, costs |
| `diag["concentration"]` | Top-name weights by year |
| `diag["sectors"]` | Last-session sector mix of invested weight |
| `diag["compliance"]["breaches"]` | Filing fails and time in breach |
| `diag["compliance"]["watch_list"]` | Names near the AAOIFI lines |
| `diag["benchmarks"]["SPUS"]["switch"]` | Cost of the on/off overlay versus the benchmark |

A new diagnostic belongs in `monterey/diagnostics/` and should read the ledger, not re-simulate. Do not make the engine write figures that can be derived from the tables.

---

## Ops

Ops is the weekday loop around the simulator. Strategy still lives in the YAML. Official NAV still lives in the ledger.

### Live spec

```python
from ops.live_rules import LIVE_BOOK, live_spec

LIVE_BOOK   # "fcf-sma-v2-baseline"
spec = live_spec()   # YAML plus ops/state/rules_overlay.json if present
```

### `run_live_session`

```python
from ops.fund import run_live_session

run_live_session(as_of="today", refresh=False, persist=True, venue="local") -> dict
```

Resolve the date. Optionally refresh the `halalquant` cache. Skip if the paper account is halted, if the date is not a market session, or if that date is already on the ledger. Load or create `SimState` from the live ledger’s manifest. Call `Simulator.step`. Append and write the ledger. Mirror `ops/state/account.json` and `ops/state/nav.csv`. Append an audit event.

### `replay_book`

```python
from ops.fund import replay_book, load_live_ledger

ledger = replay_book("2020-01-02", "2026-09-30", spec=None, refresh=False, mode="live")
```

Load facts once. If a live ledger already exists, resume from the session after the last marked date using `SimState.from_dict(manifest["state"])`. Write diagnostics and sync the paper account.

### Rules overlay

Live fields change only through `ops rules propose` / `confirm`. That writes `ops/state/rules_proposals.json`, then `ops/state/rules_overlay.json`, and an audit event `rules_version_bumped`. The overlay is merged in `live_spec()`. The spec hash changes, so the next session starts a new folder under `ledgers/<id>/<new hash>/` unless you copy state yourself. Catch-up replay on a new hash is a new book.

Allowed overlay keys in `ops/ruleset.py`:

| CLI / proposal key | Spec section | Spec field |
| --- | --- | --- |
| `name_cap` | `construction` | `name_cap` (must stay at or under 10%) |
| `sector_cap` | `construction` | `sector_cap` |
| `throttle` | `overlay` | `kind` (`spy_sma` or `none`) |
| `confirm_days`, `band`, `off_exposure`, `vol_target` | `overlay` | same names |
| `breach_exit` | `screen` | `breach_exit` |
| `sectors` | `screen` | `sectors` |
| `pit` | `universe` | `pit` |
| `cost_bps`, `dividends`, `purify_schedule` | `accounting` | `cost_bps`, `dividends`, `purify` |
| `rebalance_freq`, `drift_band`, `min_trade` | `execution` | `rebalance`, `drift_band`, `min_trade` |

ROIC, SUE, dual-momentum, and high-beta cannot be turned on through this overlay.

A new live knob that operators should be able to confirm needs three edits: the key in `monterey/spec.py` `DEFAULTS`, the layer that reads it, and a row in `ALLOWED` in `ops/ruleset.py`. Then wire the CLI flag in `ops/cli.py` if the operator should pass it on the command line.

### Paper account and halt

`ops/account.py` stores cash, shares, pending orders, and `halted` in `ops/state/account.json`. `run_live_session` will not step while halted. Clear with `python -m ops halt clear --actor … --reason …`.

Cash deposits and withdrawals (`ops cash`) and the monthly contribution plan change the paper account. They are not BookSpec layers. After a cash move you still need a session to mark NAV.

### What is official

| Path | Role |
| --- | --- |
| `ledgers/<book>/<hash>/nav.parquet` | Official NAV |
| `ledgers/.../diagnostics.json` | Attribution, switch cost, concentration, compliance |
| `ledgers/.../spec.yaml` | Exact rules for that run |
| `ops/state/account.json` | Paper cash, shares, pending, halt |
| `ops/state/nav.csv` | Cutover mirror for older readers |
| `ops/state/rules_overlay.json` | Confirmed spec edits |

### Older session path

`python -m ops run --targets-only` still calls `ops.session.run_session`, which builds targets through `ops/targets.py` and can trade through `ops/pipeline.py`. Use that when you need the intended-book tables without going through `monterey.sim`. Do not implement a new live rule only there.

---

## Desk

Package: `desk/`. Command: `python -m desk`. The terminal does not trade.

```python
from desk.model import load_desk, load_desk_from_ledger

desk = load_desk()                          # live ledger if present, else ops/state
desk = load_desk_from_ledger("ledgers/fcf-sma-v2-baseline/6ca86844209e")
```

`load_desk` prefers a ledger with `manifest["mode"] == "live"`. `[` / `]` in the TUI cycle `ledgers/` (live v2, archived v1, experiments).

Holdings are marked at the **session close**, from `positions.parquet`. The screen column is `PASS` when `screen_reason` is empty or `"passes"`, and `REVIEW` otherwise, including excluded-activity reasons and filing breaches.

The rules panel comes from **that ledger’s spec** (`spec.summary()`), not from today’s Python defaults.

Tab 6 renders `diagnostics.json`. Tab 7 overlays two NAV paths.

If you add a column the operator should see, add it to the position or nav row in `step`, include it in `ledger.SCHEMAS` if it is a first-class column, then map it in `desk/model.py` (`Holding` or `Desk`) and in `desk/app.py`. The desk must not call the brain or the overlay itself.

---

## Changing a layer

A new rule needs a key in `DEFAULTS` (`monterey/spec.py`) before `BookSpec.replace` or YAML will accept it. Unknown keys raise. Then the one layer that owns the decision reads `spec.<section>["<key>"]`. The engine already calls that layer. You only change the engine when the decision depends on cash, shares, or NAV partway through the day.

Work in this order:

1. Add the key to `DEFAULTS` for the correct section.
2. Read it in the layer file that owns the decision. For a NAV-path or residual-across-days rule, read it in `step`.
3. Confirm the hash moved and the other sections did not:

```python
from monterey.spec import BookSpec

base = BookSpec.load("fcf-sma-v2-baseline")
trial = base.replace(execution={"drift_band": 0.01})
assert trial.hash() != base.hash()
trial.summary()
```

4. Inspect the layer on one date without a full run. See the next section.
5. Simulate a short window, then the scored window, and write a ledger:

```python
from monterey.data import load_research_data
from monterey.sim.engine import simulate

rd = load_research_data("2019-12-01", "2026-09-30")
ledger = simulate(trial, rd, "2020-01-02", "2026-09-30", root=None, progress=True)
```

6. If operators should be able to confirm the knob, add it to `ALLOWED` in `ops/ruleset.py`.
7. If the desk should show it, map the ledger column in `desk/model.py`.
8. Add a test in `monterey/tests/` that the layer function, not the full 2020–2026 path, does what you claim. Use `monterey/tests/synthetic.py` when you need a tiny `ResearchData`.

Where to put the code:

| Kind of change | File | Engine change? |
| --- | --- | --- |
| Membership / PIT | `layers/universe.py`, `data/research_data.py` | No |
| Sector ban or AAOIFI lines | `layers/screen.py`, `data/research_data.py` | No |
| Filing exit lag or residual | `sim/engine.py` (`step`) | Yes |
| Stock list / ranking | `layers/signals/brains.py` | No |
| Caps, floors, weighting | `layers/construction.py` | No |
| Price-series switch | `layers/overlay.py` | No |
| NAV trailing stop | `sim/engine.py` (`_nav_brake_exposure`) | Yes |
| Drift band, min ticket | `layers/execution.py` `plan_orders` | No |
| Fill cash / cost / partials | `layers/execution.py` `fill_orders` | No |
| Next-open vs close timing | `sim/engine.py` (`step`) | Yes |
| Dividends / purification / cash yield | `layers/accounting.py` | No |
| New official column | `sim/engine.py` plus `ledger.py` `SCHEMAS` | Yes, the row |
| Live operator knob | `ops/ruleset.py`, maybe `ops/cli.py` | No |
| Desk display | `desk/model.py`, `desk/app.py` | No |

Do not edit `books/fcf-sma-v2-baseline.yaml` as a trial. That file is the scored live book. Copy it or call `replace` with a new `id`. Promoting a winner is `ops rules propose` / `confirm`, or a reviewed YAML change that starts a new hash.

---

## Inspecting a layer without a full run

Use this when the question is whether the lid, screen, or switch bound on a date. A full sim is not required.

```python
import pandas as pd
from monterey.layers import screen, build_weights, regime
from monterey.layers.signals import Context, run_brain
from monterey.spec import BookSpec
from monterey.data import load_research_data

rd = load_research_data("2019-12-01", "2026-09-30")
day = "2022-06-30"
spec = BookSpec.load("fcf-sma-v2-baseline").replace(
    id="trial",
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

Counts that NAV alone cannot show live on the ledger tables after a run:

```python
from monterey.diagnostics import diagnose
from monterey.ledger import Ledger

trial = Ledger.read("ledgers/<id>/<hash>")
diag = diagnose(trial, rd)
diag["sectors"]
diag["compliance"]["breaches"]

events = trial.events
events["type"].value_counts()
events[events["type"] == "breach_wait"].head()

cash_days = (trial.nav["invested"] / trial.nav["nav"] < 0.05).sum()
print("near-cash sessions", int(cash_days))
```

---

## Tests

```bash
pytest monterey/tests ops/tests desk/tests
```

`monterey/tests/test_core.py` covers spec hashing, layer functions, and `Simulator.step` on synthetic data. `monterey/tests/synthetic.py` builds a tiny `ResearchData`. `ops/tests/test_fund.py` covers the live session wrapper. `desk/tests/test_desk.py` covers ledger → `Desk` mapping.

When you add a knob, add a unit test that:

1. The unknown key still raises.
2. The hash changes when the key is on, and does not change when it is at the omitted default.
3. The layer function returns the numbers you expect on a three-name fixture.
4. If the engine is involved, one `step` on synthetic data writes the event, order, or cashflow you expect.

A full 2020–2026 replay is not a unit test. Run that after the unit tests pass, with `python -m monterey run` or `python -m ops replay`.
