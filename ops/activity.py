"""Paper activity the investor ledger will read. Newest row is last in the file."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ops.paths import STATE

COLUMNS = (
    "as_of",
    "type",
    "symbol",
    "amount",
    "shares",
    "price",
    "detail",
    "actor",
    "ref",
)


def activity_path(root: Path | None = None) -> Path:
    return (root or STATE) / "activity.csv"


def append_activity(row: dict, root: Path | None = None) -> None:
    path = activity_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame([{key: row.get(key) for key in COLUMNS}])
    if path.exists():
        prior = pd.read_csv(path)
        frame = pd.concat([prior, frame], ignore_index=True)
    frame.to_csv(path, index=False)


def read_activity(root: Path | None = None) -> pd.DataFrame:
    path = activity_path(root)
    if not path.exists():
        return pd.DataFrame(columns=list(COLUMNS))
    return pd.read_csv(path)
