"""Write one session's intended book to ops/runs/<as_of>/."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from ops.paths import RUNS
from ops.targets import IntendedBook


def run_dir(as_of, root: Path | None = None) -> Path:
    day = pd.Timestamp(as_of).date().isoformat()
    return (root or RUNS) / day


def persist_session(
    book: IntendedBook,
    *,
    breaches: pd.DataFrame | None = None,
    coverage: pd.DataFrame | None = None,
    refresh: pd.DataFrame | None = None,
    extra: dict[str, Any] | None = None,
    tables: dict[str, pd.DataFrame] | None = None,
    root: Path | None = None,
) -> Path:
    folder = run_dir(book.as_of, root)
    folder.mkdir(parents=True, exist_ok=True)
    _write_table(folder / "intended_book", book.holdings)
    _write_table(folder / "invested_book", book.invested)
    if breaches is not None:
        _write_table(folder / "filing_fails", breaches)
    if coverage is not None:
        _write_table(folder / "coverage_summary", coverage)
    if refresh is not None:
        _write_table(folder / "refresh_summary", refresh)
    for name, table in (tables or {}).items():
        _write_table(folder / name, table)

    payload = book.summary()
    payload["paths"] = {
        "intended_book": str(folder / "intended_book.csv"),
        "invested_book": str(folder / "invested_book.csv"),
    }
    if extra:
        payload.update(extra)
    (folder / "summary.json").write_text(json.dumps(payload, indent=2, default=str) + "\n")
    return folder


def _write_table(stem: Path, frame: pd.DataFrame) -> None:
    table = frame if frame is not None else pd.DataFrame()
    table.to_csv(stem.with_suffix(".csv"), index=False)
    try:
        table.to_parquet(stem.with_suffix(".parquet"), index=False)
    except (ImportError, ValueError, OSError):
        pass
