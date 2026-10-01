"""BookSpec: one declarative description of a fund book, layer by layer.

A spec names one implementation per layer (universe → screen → signal →
construction → overlay → execution → accounting). Its hash is stamped on
every ledger, so two runs with the same hash ran the same rules.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

from monterey.paths import BOOKS

SECTIONS = ("universe", "screen", "signal", "construction", "overlay", "execution", "accounting")

DEFAULTS: dict[str, dict[str, Any]] = {
    "universe": {
        "index": "sp500",
        # True: index members on each date. False: today's member list for every date.
        "pit": True,
    },
    "screen": {
        "sectors": True,
        "debt": 0.30,
        "cash": 0.30,
        "receivables": 0.70,
        # A failed 10-Q / 10-K between snapshots: next_open sells, report_only only flags.
        "breach_exit": "next_open",
        # Ratios inside this distance of a line go on the watch list.
        "watch_band": 0.02,
    },
    "signal": {
        "brain": "fcf_quality",
        "params": {},
    },
    "construction": {
        "weight": "cap",
        "name_cap": 0.10,
        "sector_cap": None,
        "collapse_share_classes": True,
    },
    "overlay": {
        "kind": "spy_sma",
        "ticker": "SPY",
        "window": 200,
        # Consecutive closes on the other side of the line before the switch flips.
        "confirm_days": 0,
        # Hysteresis: on above sma × (1 + band), off below sma × (1 − band).
        "band": 0.0,
        # Share of the book kept invested while the switch is off.
        "off_exposure": 0.0,
        # Annualised volatility target on the ticker; null turns it off.
        "vol_target": None,
        "vol_lookback": 20,
    },
    "execution": {
        # Signals from the close trade at the next open.
        "signal_lag": "next_open",
        # daily_to_target: trade every name back to target each session.
        # on_signal: trade on rebalance dates, switch changes, and breaches only.
        "rebalance": "daily_to_target",
        # Skip a name when |target − current| weight is below this.
        "drift_band": 0.0,
        "min_trade": 100.0,
        # First session fills at that day's close so a NAV exists.
        "first_fill": "close",
    },
    "accounting": {
        "capital": 1_000_000.0,
        "dividends": True,
        "cost_bps": 10.0,
        # ex_date: donate the impure slice when the dividend is credited. off: keep it.
        "purify": "ex_date",
        # v1 parity only: take purification even when dividends are not credited.
        "purify_uncredited": False,
    },
}

@dataclass(frozen=True)
class BookSpec:
    id: str
    label: str = ""
    description: str = ""
    universe: Mapping[str, Any] = field(default_factory=dict)
    screen: Mapping[str, Any] = field(default_factory=dict)
    signal: Mapping[str, Any] = field(default_factory=dict)
    construction: Mapping[str, Any] = field(default_factory=dict)
    overlay: Mapping[str, Any] = field(default_factory=dict)
    execution: Mapping[str, Any] = field(default_factory=dict)
    accounting: Mapping[str, Any] = field(default_factory=dict)
    benchmarks: tuple[str, ...] = ("SPUS", "SPY")

    def __post_init__(self) -> None:
        if not self.id or not str(self.id).strip():
            raise ValueError("a book spec needs an id")
        for section in SECTIONS:
            merged = _merge(DEFAULTS[section], getattr(self, section) or {}, section)
            object.__setattr__(self, section, merged)
        object.__setattr__(self, "benchmarks", tuple(self.benchmarks))

    def rules(self) -> dict[str, Any]:
        """The parts that change what the book trades. The hash covers only these."""
        return {section: copy.deepcopy(dict(getattr(self, section))) for section in SECTIONS}

    def hash(self) -> str:
        payload = json.dumps(self.rules(), sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id}
        if self.label:
            out["label"] = self.label
        if self.description:
            out["description"] = self.description
        out.update(self.rules())
        out["benchmarks"] = list(self.benchmarks)
        return out

    def replace(self, *, id: str | None = None, label: str | None = None, **sections: Mapping[str, Any]) -> "BookSpec":
        """New spec with some section keys changed: ``spec.replace(overlay={"confirm_days": 2})``."""
        data = self.to_dict()
        if id is not None:
            data["id"] = id
        if label is not None:
            data["label"] = label
        for section, changes in sections.items():
            if section not in SECTIONS:
                raise ValueError(f"unknown spec section {section!r}")
            current = dict(data[section])
            for key, value in dict(changes).items():
                if section == "signal" and key == "params":
                    current["params"] = {**dict(current.get("params") or {}), **dict(value or {})}
                else:
                    current[key] = value
            data[section] = current
        return BookSpec.from_dict(data)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BookSpec":
        unknown = set(data) - {"id", "label", "description", "benchmarks", *SECTIONS}
        if unknown:
            raise ValueError("unknown spec keys: " + ", ".join(sorted(unknown)))
        kwargs = {key: data[key] for key in data if key != "benchmarks"}
        if "benchmarks" in data:
            kwargs["benchmarks"] = tuple(data["benchmarks"])
        return cls(**kwargs)

    @classmethod
    def load(cls, path: str | Path) -> "BookSpec":
        target = resolve_book(path)
        return cls.from_dict(yaml.safe_load(target.read_text(encoding="utf-8")) or {})

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(yaml.safe_dump(self.to_dict(), sort_keys=False), encoding="utf-8")
        return target

    def summary(self) -> list[tuple[str, str]]:
        """Short label / value rows for terminals and reports."""
        s, c, o, e, a = self.screen, self.construction, self.overlay, self.execution, self.accounting
        params = ", ".join(f"{k}={v}" for k, v in sorted((self.signal.get("params") or {}).items()))
        throttle = o["kind"]
        if o["kind"] == "spy_sma":
            throttle = f"{o['ticker']} {o['window']}-day SMA"
            if o["confirm_days"]:
                throttle += f", confirm {o['confirm_days']}d"
            if o["band"]:
                throttle += f", band {o['band']:.1%}"
            if o["off_exposure"]:
                throttle += f", off {o['off_exposure']:.0%}"
        if o.get("vol_target"):
            throttle += f", vol target {o['vol_target']:.0%}"
        return [
            ("book", self.id),
            ("hash", self.hash()),
            ("universe", f"{self.universe['index']} {'point-in-time' if self.universe['pit'] else 'current list'}"),
            ("sector screen", "on" if s["sectors"] else "OFF"),
            ("AAOIFI lines", f"debt {s['debt']:.0%} / cash {s['cash']:.0%} / recv {s['receivables']:.0%}"),
            ("breach exit", str(s["breach_exit"])),
            ("brain", f"{self.signal['brain']}" + (f" ({params})" if params else "")),
            ("weights", str(c["weight"])),
            ("name cap", "none" if not c["name_cap"] else f"{c['name_cap']:.0%}"),
            ("sector cap", "none" if not c["sector_cap"] else f"{c['sector_cap']:.0%}"),
            ("throttle", throttle),
            ("rebalance", f"{e['rebalance']}, drift band {e['drift_band']:.1%}, min ${e['min_trade']:,.0f}"),
            ("dividends", "credited" if a["dividends"] else "NOT credited"),
            ("cost", f"{a['cost_bps']:.0f} bp charged"),
            ("purify", str(a["purify"])),
        ]


def resolve_book(path: str | Path) -> Path:
    """A path, or a name under ``books/`` (``fcf-sma-v2-baseline``)."""
    target = Path(path)
    if target.exists():
        return target
    for candidate in (BOOKS / f"{path}.yaml", BOOKS / str(path)):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"no book spec at {path}")


def _merge(defaults: Mapping[str, Any], given: Mapping[str, Any], section: str) -> dict[str, Any]:
    unknown = set(given) - set(defaults)
    if unknown:
        raise ValueError(f"unknown {section} keys: " + ", ".join(sorted(unknown)))
    out = copy.deepcopy(dict(defaults))
    for key, value in dict(given).items():
        out[key] = copy.deepcopy(value)
    if section == "signal":
        out["params"] = dict(out.get("params") or {})
    return out
