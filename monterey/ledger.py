"""Ledger: the one table layout every run writes (live, replay, experiment).

    ledgers/<book_id>/<spec_hash>/
        spec.yaml        the exact rules
        manifest.json    mode, window, data snapshot, created
        nav.parquet      one row per session
        positions.parquet  held and targeted names per session
        orders.parquet   orders created at each close
        fills.parquet    executions with cost
        cashflows.parquet  dividends, purification, costs, deposits
        events.parquet   switch flips, breaches, rebuilds, delistings, halts
        diagnostics.json written by monterey.diagnostics

Git keeps ``spec.yaml``, ``manifest.json``, ``nav.parquet``, ``diagnostics.json``.
The other tables sync to R2.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from monterey.paths import LEDGERS
from monterey.spec import BookSpec

TABLES = ("nav", "positions", "orders", "fills", "cashflows", "events")
SCHEMAS: dict[str, list[str]] = {
    "nav": [
        "date", "nav", "cash", "invested", "daily_return", "exposure", "regime_on", "regime_raw",
        "n_positions", "n_targets", "n_fills", "n_orders", "traded_notional", "costs", "dividends",
        "purification", "snapshot", "max_gap",
    ],
    "positions": [
        "date", "symbol", "shares", "price", "value", "weight", "target_weight", "invested_weight",
        "sector", "screen_reason", "score", "market_cap", "debt_ratio", "cash_ratio", "receivables_ratio",
    ],
    "orders": [
        "date", "symbol", "side", "shares", "target_weight", "current_weight", "drift", "price_ref",
        "notional", "est_cost", "status", "reason",
    ],
    "fills": ["date", "symbol", "side", "shares", "price", "notional", "cost", "price_field", "status", "reason", "detail"],
    "cashflows": ["date", "type", "symbol", "amount", "shares", "per_share", "ratio"],
    "events": ["date", "type", "symbol", "detail"],
}
GIT_FILES = ("spec.yaml", "manifest.json", "nav.parquet", "diagnostics.json")


@dataclass
class Ledger:
    spec: BookSpec
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)
    path: Path | None = None

    def __post_init__(self) -> None:
        for name in TABLES:
            frame = self.tables.get(name)
            self.tables[name] = _conform(name, frame)

    # Shorthand accessors.
    @property
    def nav(self) -> pd.DataFrame:
        return self.tables["nav"]

    @property
    def positions(self) -> pd.DataFrame:
        return self.tables["positions"]

    @property
    def fills(self) -> pd.DataFrame:
        return self.tables["fills"]

    @property
    def orders(self) -> pd.DataFrame:
        return self.tables["orders"]

    @property
    def cashflows(self) -> pd.DataFrame:
        return self.tables["cashflows"]

    @property
    def events(self) -> pd.DataFrame:
        return self.tables["events"]

    @property
    def label(self) -> str:
        return self.spec.id

    def nav_series(self) -> pd.Series:
        frame = self.nav
        if frame.empty:
            return pd.Series(dtype=float)
        return pd.Series(frame["nav"].astype(float).values, index=pd.to_datetime(frame["date"]), name=self.spec.id)

    def diagnostics(self) -> dict:
        if self.path is not None and (self.path / "diagnostics.json").exists():
            return json.loads((self.path / "diagnostics.json").read_text(encoding="utf-8"))
        return {}

    def folder(self, root: Path | None = None) -> Path:
        return (root or LEDGERS) / self.spec.id / self.spec.hash()

    def write(self, root: Path | None = None, path: Path | None = None) -> Path:
        target = path or self.folder(root)
        target.mkdir(parents=True, exist_ok=True)
        self.spec.save(target / "spec.yaml")
        manifest = {
            "book": self.spec.id,
            "spec_hash": self.spec.hash(),
            "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **self.manifest,
        }
        nav = self.nav
        if not nav.empty:
            manifest["start"] = str(pd.Timestamp(nav["date"].iloc[0]).date())
            manifest["end"] = str(pd.Timestamp(nav["date"].iloc[-1]).date())
            manifest["sessions"] = int(len(nav))
            manifest["last_nav"] = float(nav["nav"].iloc[-1])
        (target / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")
        for name in TABLES:
            self.tables[name].to_parquet(target / f"{name}.parquet", index=False)
        self.manifest = manifest
        self.path = target
        return target

    def append(self, day_tables: dict[str, pd.DataFrame]) -> None:
        """Add one session's rows (replacing rows already written for that date)."""
        for name, frame in day_tables.items():
            if frame is None or frame.empty:
                continue
            frame = _conform(name, frame)
            days = set(pd.to_datetime(frame["date"]).dt.normalize())
            current = self.tables[name]
            if not current.empty:
                current = current[~pd.to_datetime(current["date"]).dt.normalize().isin(days)]
            self.tables[name] = pd.concat([current, frame], ignore_index=True) if not current.empty else frame

    @classmethod
    def read(cls, path: str | Path, tables: tuple[str, ...] = TABLES) -> "Ledger":
        folder = Path(path)
        spec = BookSpec.load(folder / "spec.yaml")
        manifest = {}
        if (folder / "manifest.json").exists():
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        loaded = {}
        for name in tables:
            file = folder / f"{name}.parquet"
            loaded[name] = pd.read_parquet(file) if file.exists() else None
        return cls(spec=spec, tables=loaded, manifest=manifest, path=folder)


def list_ledgers(root: Path | None = None) -> list[dict]:
    """Every ledger folder under ``root`` (live books and experiments), newest first."""
    base = root or LEDGERS
    rows = []
    if not base.exists():
        return rows
    for manifest in base.rglob("manifest.json"):
        folder = manifest.parent
        if not (folder / "spec.yaml").exists():
            continue
        try:
            info = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            info = {}
        rows.append(
            {
                "path": folder,
                "name": str(folder.relative_to(base)),
                "book": info.get("book", folder.parent.name),
                "hash": info.get("spec_hash", folder.name),
                "mode": info.get("mode", ""),
                "end": info.get("end", ""),
                "last_nav": info.get("last_nav"),
                "written_at": info.get("written_at", ""),
            }
        )
    rows.sort(key=lambda r: (r["mode"] != "live", str(r["written_at"])), reverse=False)
    live = [r for r in rows if r["mode"] == "live"]
    rest = sorted((r for r in rows if r["mode"] != "live"), key=lambda r: str(r["written_at"]), reverse=True)
    return live + rest


def _conform(name: str, frame: pd.DataFrame | None) -> pd.DataFrame:
    columns = SCHEMAS[name]
    if frame is None or len(frame) == 0:
        return pd.DataFrame({c: pd.Series(dtype="object") for c in columns})
    out = frame.copy()
    for column in columns:
        if column not in out.columns:
            out[column] = None
    out = out[columns + [c for c in out.columns if c not in columns]]
    out["date"] = pd.to_datetime(out["date"])
    return out.reset_index(drop=True)
