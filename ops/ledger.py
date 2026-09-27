"""Official paper NAV. Dashboards should read this file, not a backtest chart."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from ops.account import PaperAccount
from ops.oms import equity
from ops.paths import STATE

LEDGER_COLUMNS = (
    "as_of",
    "nav",
    "cash",
    "invested",
    "daily_return",
    "n_positions",
    "sma_on",
    "halted",
    "purification_today",
    "purification_cumulative",
    "fill_basis",
)


def ledger_path(root: Path | None = None) -> Path:
    return (root or STATE) / "nav.csv"


def already_marked(as_of: date | str, root: Path | None = None) -> bool:
    path = ledger_path(root)
    if not path.exists():
        return False
    frame = pd.read_csv(path)
    if frame.empty or "as_of" not in frame.columns:
        return False
    day = pd.Timestamp(as_of).date().isoformat()
    return day in set(frame["as_of"].astype(str).str.slice(0, 10))


def mark_row(
    account: PaperAccount,
    closes: dict[str, float],
    *,
    as_of: date,
    sma_on: bool,
    purification_today: float,
    fill_basis: str,
) -> dict:
    nav = equity(account, closes)
    invested = nav - float(account.cash)
    return {
        "as_of": as_of.isoformat(),
        "nav": nav,
        "cash": float(account.cash),
        "invested": invested,
        "daily_return": 0.0,
        "n_positions": len(account.positions),
        "sma_on": bool(sma_on),
        "halted": bool(account.halted),
        "purification_today": purification_today,
        "purification_cumulative": float(account.purification_cumulative),
        "fill_basis": fill_basis,
    }


def append_nav(row: dict, root: Path | None = None) -> pd.DataFrame:
    path = ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    row_frame = pd.DataFrame([row])
    if path.exists():
        frame = pd.read_csv(path)
        if not frame.empty:
            frame = frame.loc[frame["as_of"].astype(str).str.slice(0, 10) != str(row["as_of"])[:10]]
        frame = pd.concat([frame, row_frame], ignore_index=True)
    else:
        frame = row_frame
    frame["as_of"] = pd.to_datetime(frame["as_of"])
    frame = frame.sort_values("as_of").reset_index(drop=True)
    frame["daily_return"] = pd.to_numeric(frame["nav"], errors="coerce").pct_change().fillna(0.0)
    frame["as_of"] = frame["as_of"].dt.strftime("%Y-%m-%d")
    frame.to_csv(path, index=False)
    return frame
