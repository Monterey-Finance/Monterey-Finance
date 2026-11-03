# Paper 22: Book drawdown brake

Turn the SPY SMA off and cut equity when this book's NAV falls `X%` from its own peak. One `overlay.nav_brake` per trial. Scored against **v2 baseline**.

```python
from monterey.research import boot, compare, run_book
from monterey.sprints import score_against_baseline

rd = boot("paper-22-nav-brake", start="2019-12-01", end="2026-09-30")
base = run_book("fcf-sma-v2-baseline", rd, paper="22-nav-brake", id="v2")
trial = run_book(
    "fcf-sma-v2-baseline", rd,
    paper="22-nav-brake", id="nav-12",
    overlay={"kind": "none", "nav_brake": 0.12},
)
compare([base, trial], rd)
score_against_baseline(trial, base, rd)
```
