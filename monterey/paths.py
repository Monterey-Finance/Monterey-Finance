"""Repo locations shared by ops, desk, and notebooks."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOKS = ROOT / "books"
LEDGERS = Path(os.environ.get("MONTEREY_LEDGERS", ROOT / "ledgers"))
SNAPSHOTS = Path(os.environ.get("MONTEREY_SNAPSHOTS", ROOT / "data" / "snapshots"))
RESEARCH = ROOT / "Research"
