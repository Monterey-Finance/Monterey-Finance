"""Compatibility shim. The frozen Phase 1B sleeves live in ``monterey.legacy.sleeves``.

Old notebooks that do ``import sleeves`` or ``import sleeves.backtest`` keep
working and get the same module objects as ``monterey.legacy.sleeves``. New
work should use ``monterey`` (spec, layers, simulator) instead.
"""

from __future__ import annotations

import importlib
import sys

_IMPL = "monterey.legacy.sleeves"
_SUBMODULES = (
    "backtest",
    "book",
    "compliance",
    "costs",
    "diagnostics",
    "exits",
    "fundamentals",
    "lab",
    "prices",
    "purify",
    "rules",
    "select",
    "stats",
    "triggers",
    "universe",
    "weighting",
)

for _name in _SUBMODULES:
    _module = importlib.import_module(f"{_IMPL}.{_name}")
    sys.modules[f"{__name__}.{_name}"] = _module
    globals()[_name] = _module

from monterey.legacy.sleeves import *  # noqa: E402,F401,F403
from monterey.legacy.sleeves import __all__  # noqa: E402,F401
