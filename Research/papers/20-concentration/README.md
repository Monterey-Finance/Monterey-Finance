# Paper 20: Concentration and sector lid

v2 has no sector cap and a 10% name cap. This paper puts a **sector ceiling** (40% / 50%) and a tighter **8% name lid** on that same FCF list. Excess IT weight is spread over other sectors already in the book. It is not paper 25 (sector floors). One `construction` change per trial. Scored against **v2 baseline**. Kill rules are frozen in `Research/book-construction-status.md`.

```python
from monterey.research import boot, compare, run_book
from monterey.sprints import score_against_baseline

rd = boot("paper-20-concentration", start="2019-12-01", end="2026-09-30")
base = run_book("fcf-sma-v2-baseline", rd, paper="20-concentration", id="v2")
trial = run_book(
    "fcf-sma-v2-baseline", rd,
    paper="20-concentration", id="sector-40",
    construction={"sector_cap": 0.40},
)
compare([base, trial], rd)
score_against_baseline(trial, base, rd)
```

`run_sprint("20", rd)` builds the same four variants (sector-40, sector-50, name-8, sector-40-name-8).
