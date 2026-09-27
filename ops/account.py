"""Local paper account. Fake cash and shares. Real prices come from outside."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ops.paths import STATE

STARTING_CASH = 1_000_000.0


@dataclass
class PaperAccount:
    cash: float = STARTING_CASH
    positions: dict[str, float] = field(default_factory=dict)
    pending: list[dict] = field(default_factory=list)
    pending_targets: dict[str, float] = field(default_factory=dict)
    fills: list[dict] = field(default_factory=list)
    halted: bool = False
    halt_reason: str = ""
    purification_cumulative: float = 0.0
    purified_keys: list[str] = field(default_factory=list)
    starting_cash: float = STARTING_CASH

    def to_dict(self) -> dict:
        return {
            "cash": self.cash,
            "positions": self.positions,
            "pending": self.pending,
            "pending_targets": self.pending_targets,
            "fills": self.fills[-500:],
            "halted": self.halted,
            "halt_reason": self.halt_reason,
            "purification_cumulative": self.purification_cumulative,
            "purified_keys": self.purified_keys,
            "starting_cash": self.starting_cash,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "PaperAccount":
        return cls(
            cash=float(payload.get("cash", STARTING_CASH)),
            positions={str(k): float(v) for k, v in (payload.get("positions") or {}).items()},
            pending=list(payload.get("pending") or []),
            pending_targets={str(k): float(v) for k, v in (payload.get("pending_targets") or {}).items()},
            fills=list(payload.get("fills") or []),
            halted=bool(payload.get("halted", False)),
            halt_reason=str(payload.get("halt_reason") or ""),
            purification_cumulative=float(payload.get("purification_cumulative") or 0.0),
            purified_keys=[str(k) for k in (payload.get("purified_keys") or [])],
            starting_cash=float(payload.get("starting_cash", STARTING_CASH)),
        )


def account_path(root: Path | None = None) -> Path:
    return (root or STATE) / "account.json"


def load_account(root: Path | None = None, capital: float = STARTING_CASH) -> PaperAccount:
    path = account_path(root)
    if not path.exists():
        return PaperAccount(cash=float(capital), starting_cash=float(capital))
    payload = json.loads(path.read_text())
    return PaperAccount.from_dict(payload)


def save_account(account: PaperAccount, root: Path | None = None) -> Path:
    path = account_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(account.to_dict(), indent=2, default=str) + "\n")
    return path
