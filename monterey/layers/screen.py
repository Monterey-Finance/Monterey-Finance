"""Universe and screen layers: who is in the index, and who passes the Halal tests."""

from __future__ import annotations

import pandas as pd

from monterey.data import ResearchData
from monterey.spec import BookSpec


def screen(data: ResearchData, as_of, spec: BookSpec) -> pd.DataFrame:
    """Members on ``as_of`` with sector + AAOIFI verdicts and a reason per name."""
    s = spec.screen
    return data.halal(
        as_of,
        pit=bool(spec.universe["pit"]),
        sectors=bool(s["sectors"]),
        debt=float(s["debt"]),
        cash=float(s["cash"]),
        receivables=float(s["receivables"]),
    )


def watch_list(table: pd.DataFrame, spec: BookSpec) -> pd.DataFrame:
    """Compliant names whose closest ratio sits inside ``watch_band`` of its line."""
    band = float(spec.screen.get("watch_band") or 0.0)
    if table is None or table.empty or band <= 0:
        return pd.DataFrame(columns=["symbol", "ratio", "value", "line", "gap"])
    s = spec.screen
    rows = []
    for row in table.loc[table["is_compliant"]].itertuples(index=False):
        for ratio, line in (("debt_ratio", s["debt"]), ("cash_ratio", s["cash"]), ("receivables_ratio", s["receivables"])):
            value = getattr(row, ratio)
            if pd.notna(value) and 0 <= line - value <= band:
                rows.append({"symbol": row.symbol, "ratio": ratio, "value": float(value), "line": float(line), "gap": float(line - value)})
    return pd.DataFrame(rows, columns=["symbol", "ratio", "value", "line", "gap"])
