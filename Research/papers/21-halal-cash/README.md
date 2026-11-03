# Paper 21: Halal cash while the switch is off

Idle NAV earns a constant Halal cash yield while the SPY switch is off. Equity list unchanged. One `accounting.cash_yield` per trial. Scored against **v2 baseline**.

```python
from monterey.research import boot, compare, run_book
from monterey.sprints import score_against_baseline

rd = boot("paper-21-halal-cash", start="2019-12-01", end="2026-09-30")
base = run_book("fcf-sma-v2-baseline", rd, paper="21-halal-cash", id="v2")
trial = run_book(
    "fcf-sma-v2-baseline", rd,
    paper="21-halal-cash", id="cash-4",
    accounting={"cash_yield": 0.04},
)
compare([base, trial], rd)
score_against_baseline(trial, base, rd)
```
