# Paper 16: Honest regime throttle

v2 turns the whole book off the first session SPY is below its 200-day average. This paper tries confirmation, a 2% band, 50% residual exposure, a 12% vol target, and always invested. One `overlay` change per trial. Scored against **v2 baseline**. Kill rules are frozen in `Research/book-construction-status.md`.

```python
from monterey.research import boot, compare, run_book
from monterey.sprints import score_against_baseline

rd = boot("paper-16-honest-throttle", start="2019-12-01", end="2026-09-30")
base = run_book("fcf-sma-v2-baseline", rd, paper="16-honest-throttle", id="v2")
trial = run_book(
    "fcf-sma-v2-baseline", rd,
    paper="16-honest-throttle", id="confirm-2",
    overlay={"confirm_days": 2},
)
compare([base, trial], rd)
score_against_baseline(trial, base, rd)
```

`run_sprint("16", rd)` builds the same six variants (always-on, confirm-2, confirm-5, band-2pct, partial-50, vol-12).
