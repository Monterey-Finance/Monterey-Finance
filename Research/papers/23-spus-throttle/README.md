# Paper 23: Throttle on SPUS, not SPY

Same 200-day on/off rule on SPUS, plus either/both with SPY. One `overlay` change per trial. Scored against **v2 baseline**.

```python
from monterey.research import boot, compare, run_book
from monterey.sprints import score_against_baseline

rd = boot("paper-23-spus-throttle", start="2019-12-01", end="2026-09-30")
base = run_book("fcf-sma-v2-baseline", rd, paper="23-spus-throttle", id="v2")
trial = run_book(
    "fcf-sma-v2-baseline", rd,
    paper="23-spus-throttle", id="spus-sma",
    overlay={"ticker": "SPUS"},
)
compare([base, trial], rd)
score_against_baseline(trial, base, rd)
```
