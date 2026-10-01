# Paper 18: Execution policy

Scored against **v2 baseline**. Kill rules are frozen in `Research/book-construction-status.md`.

```python
from monterey.research import boot, compare
from monterey.sprints import run_sprint

rd = boot("paper-18-execution", start="2019-12-01", end="2026-09-30")
ledgers, table = run_sprint("18", rd)
table
```
