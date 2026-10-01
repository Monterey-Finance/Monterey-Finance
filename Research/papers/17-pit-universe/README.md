# Paper 17: Point-in-time universe effect

Scored against **v2 baseline**. Kill rules are frozen in `Research/book-construction-status.md`.

```python
from monterey.research import boot, compare
from monterey.sprints import run_sprint

rd = boot("paper-17-pit-universe", start="2019-12-01", end="2026-09-30")
ledgers, table = run_sprint("17", rd)
table
```
