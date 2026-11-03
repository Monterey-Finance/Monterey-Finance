# Paper 18: Execution policy

v2 re-targets every name every session. This paper tries on-signal rebalance, a 1% drift band, a $2,500 minimum ticket, and both together. One `execution` change per trial. Scored against **v2 baseline**. Kill rules are frozen in `Research/book-construction-status.md`.

```python
from monterey.research import boot, compare, run_book
from monterey.sprints import score_against_baseline

rd = boot("paper-18-execution", start="2019-12-01", end="2026-09-30")
base = run_book("fcf-sma-v2-baseline", rd, paper="18-execution", id="v2")
trial = run_book(
    "fcf-sma-v2-baseline", rd,
    paper="18-execution", id="drift-1pct",
    execution={"drift_band": 0.01},
)
compare([base, trial], rd)
score_against_baseline(trial, base, rd)
```

`run_sprint("18", rd)` builds the same four variants (on-signal, drift-1pct, min-2500, drift-1pct-min-2500).
