"""Repo paths. Keep run files next to this package, not in the research lab."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESEARCH = ROOT / "Research"
RUNS = Path(__file__).resolve().parent / "runs"
STATE = Path(__file__).resolve().parent / "state"


def ensure_research_on_path() -> Path:
    path = str(RESEARCH)
    if path not in sys.path:
        sys.path.insert(0, path)
    return RESEARCH
