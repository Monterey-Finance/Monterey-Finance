"""Names within 2 percentage points of an AAOIFI line. Informational. No order."""

from __future__ import annotations

import pandas as pd

LINES = {
    "debt_ratio": 0.30,
    "cash_ratio": 0.30,
    "receivables_ratio": 0.70,
}
NEAR = 0.02


def near_limit_flags(holdings: pd.DataFrame) -> pd.DataFrame:
    columns = ["symbol", "ratio", "value", "line", "gap"]
    if holdings is None or holdings.empty or "symbol" not in holdings.columns:
        return pd.DataFrame(columns=columns)
    rows = []
    for _, holding in holdings.iterrows():
        symbol = str(holding["symbol"])
        for ratio, line in LINES.items():
            if ratio not in holdings.columns:
                continue
            value = pd.to_numeric(holding.get(ratio), errors="coerce")
            if pd.isna(value):
                continue
            value = float(value)
            if line - NEAR <= value < line:
                rows.append(
                    {
                        "symbol": symbol,
                        "ratio": ratio,
                        "value": value,
                        "line": line,
                        "gap": line - value,
                    }
                )
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows)
