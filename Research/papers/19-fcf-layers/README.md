# Paper 19: FCF layers

v2 keeps the top half of Halal S&P 500 names by FCF / sales. This paper stacks conversion (FCF / EBITDA), stability (positive-FCF share), then FCF yield on that margin cut. One `signal` change per trial. Scored against **v2 baseline**. Kill rules are frozen in `Research/book-construction-status.md`.

```python
from monterey.research import boot, compare, run_book
from monterey.sprints import score_against_baseline

rd = boot("paper-19-fcf-layers", start="2019-12-01", end="2026-09-30")
base = run_book("fcf-sma-v2-baseline", rd, paper="19-fcf-layers", id="v2")
trial = run_book(
    "fcf-sma-v2-baseline", rd,
    paper="19-fcf-layers", id="conversion",
    signal={"brain": "fcf_layers", "params": {"conversion_min": 0.5, "min_holdings": 20}},
)
compare([base, trial], rd)
score_against_baseline(trial, base, rd)
```

`run_sprint("19", rd)` builds the same four variants (conversion, stability, yield-drop, all-layers).
