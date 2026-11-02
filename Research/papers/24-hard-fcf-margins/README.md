# Paper 24: Hard FCF floor

v2 keeps the **top half** of Halal S&P 500 names by FCF / sales. That is a rank, not a quality line — the old diagnostics put the median around 4%. This paper replaces `keep_quantile=0.5` with a **fixed FCF-margin floor** (6%, 8%, 10%). If the floor leaves fewer than 20 names, the gap stays in cash. The floor is not relaxed. Conversion / stability / yield stay in paper 19.

```python
from monterey.research import boot, compare, run_book
from monterey.sprints import score_against_baseline

rd = boot("paper-24-hard-fcf-margins", start="2019-12-01", end="2026-09-30")
base = run_book("fcf-sma-v2-baseline", rd, paper="24-hard-fcf-margins", id="v2")
trial = run_book(
    "fcf-sma-v2-baseline", rd,
    paper="24-hard-fcf-margins", id="floor-8",
    signal={"params": {"margin_floor": 0.08}},
)
compare([base, trial], rd)
score_against_baseline(trial, base, rd)
```

Change only `signal.params`. Overlay, construction, execution, and screens stay on v2. Scored against **v2 baseline**.
