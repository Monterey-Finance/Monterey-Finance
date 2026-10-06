# Paper 17: Point-in-time universe effect

v2 already uses **point-in-time** S&P 500 membership. This sprint measures the leak if we freeze **today’s list** on every date instead — the survivorship book v1 ran.

Current-list is **not** a live candidate. Keep `universe.pit: true` even when the leaked path looks better.

```python
from monterey.research import boot
from monterey.sprints import run_sprint, v2_snapshot_hash

rd = boot("paper-17-pit-universe", snapshot=v2_snapshot_hash())
ledgers, table = run_sprint("17", rd)
table
```

Snapshot `bfb52f463228`. Window 2020-01-02 → 2026-09-30. Same engine as v2; only `universe.pit` flips.

## What changed

| Layer | v2 baseline | This sprint |
| --- | --- | --- |
| Universe | S&P 500 members **on that date** | The **2026-09-30** member list on every date |
| Everything else | FCF top half, 10% name cap, SPY 200-day cash, next-open fills | Unchanged |

## Universe census (month-end)

Mean PIT list **504** names vs today’s **503**. About **56 joiners** and **56 leavers** per month in 2020, shrinking to zero by August 2026.

Joiners are names on today’s list that were **not** in the index that month. Leavers were in the index then and are **gone** now.

## Book effect

The current-list book held **39 joiner names** before they joined the index (Airbnb, Marvell, Coinbase, DoorDash, Datadog, Palantir, …). The PIT book held **16 leaver names** that today’s list no longer includes (Enphase, Paycom, Etsy, …). Those weights are small (max ~1% Airbnb), but they compound.

| Book | Total | CAGR | Max DD | Calmar |
| --- | --- | --- | --- | --- |
| v2 PIT (`6ca86844209e`) | +104.6% | 11.2% | −24.8% | 0.45 |
| current-list (`c7cda04e91e6`) | +111.6% | 11.8% | −24.6% | 0.48 |
| SPUS | +211.7% | 18.4% | −30.8% | 0.60 |

Yearly, PIT and current-list are close through 2022. The leak shows up in the bull years: 2023 +16.0% vs +15.3%, 2024 +28.7% vs +27.4%, 2026 +17.0% vs +15.8%. Kill bars vs v2 **pass** — that is the point. Survivorship looks like a better book.

## Architecture takeaway

Keep **`universe.pit: true`**. Do not promote `pit: false`. The extra ~0.6pp CAGR is names we would not have been allowed to own on that date. Figure: [`figures/pit-vs-current.png`](figures/pit-vs-current.png).
