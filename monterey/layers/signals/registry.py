"""Brain registry. A brain turns screened names into a ranked selection.

A brain is ``fn(ctx, **params) -> DataFrame`` with at least ``symbol``,
``score``, and ``market_cap``. Extra columns are the "why" shown in the desk.
Register with ``@brain("name")``; a spec picks it with ``signal.brain``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable

import pandas as pd

from monterey.data import ResearchData
from monterey.spec import BookSpec

BrainFn = Callable[..., pd.DataFrame]
BRAINS: dict[str, BrainFn] = {}
SELECTION_COLUMNS = ("symbol", "score", "market_cap")


@dataclass
class Context:
    data: ResearchData
    spec: BookSpec
    as_of: date
    screen: pd.DataFrame
    extras: dict = field(default_factory=dict)

    @property
    def compliant(self) -> list[str]:
        return list(self.screen.loc[self.screen["is_compliant"], "symbol"])

    def snapshot(self, compliant_only: bool = True) -> pd.DataFrame:
        """Metrics snapshot in force, limited to compliant names, with sector labels."""
        snap = self.data.metrics_on(self.as_of)
        if snap.empty:
            return snap
        if compliant_only:
            snap = snap[snap["symbol"].isin(self.compliant)]
        snap = snap.copy()
        snap["sector"] = snap["symbol"].map(self.data.sectors)
        return snap


def brain(name: str):
    def wrap(fn: BrainFn) -> BrainFn:
        BRAINS[name] = fn
        fn.brain_name = name
        return fn

    return wrap


def run_brain(ctx: Context) -> pd.DataFrame:
    name = str(ctx.spec.signal["brain"])
    if name not in BRAINS:
        raise KeyError(f"unknown brain {name!r}. Registered: {', '.join(sorted(BRAINS))}")
    out = BRAINS[name](ctx, **dict(ctx.spec.signal.get("params") or {}))
    if out is None or out.empty:
        return pd.DataFrame(columns=list(SELECTION_COLUMNS))
    missing = [c for c in SELECTION_COLUMNS if c not in out.columns]
    if missing:
        raise ValueError(f"brain {name} returned no {', '.join(missing)}")
    return out.reset_index(drop=True)
