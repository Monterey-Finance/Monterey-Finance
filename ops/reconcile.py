"""Stop the paper book when holdings do not match the weights we just traded."""

from __future__ import annotations

from dataclasses import dataclass

from ops.account import PaperAccount
from ops.oms import equity

WEIGHT_BAND = 0.03


@dataclass
class ReconcileResult:
    halt: bool
    reason: str
    max_gap: float


def position_weights(account: PaperAccount, closes: dict[str, float]) -> dict[str, float]:
    nav = equity(account, closes)
    if nav <= 0:
        return {}
    weights: dict[str, float] = {}
    for symbol, shares in account.positions.items():
        price = closes.get(symbol)
        if price is None or price <= 0 or shares <= 0:
            continue
        weights[symbol] = (float(shares) * float(price)) / nav
    return weights


def reconcile(
    account: PaperAccount,
    closes: dict[str, float],
    targets: dict[str, float],
    *,
    band: float = WEIGHT_BAND,
) -> ReconcileResult:
    actual = position_weights(account, closes)
    names = set(actual) | set(targets)
    max_gap = 0.0
    missing_price = []
    for symbol in names:
        if targets.get(symbol, 0.0) > 0 and symbol not in closes:
            missing_price.append(symbol)
        gap = abs(actual.get(symbol, 0.0) - float(targets.get(symbol, 0.0)))
        if gap > max_gap:
            max_gap = gap
    if account.cash < -1.0:
        return ReconcileResult(True, "cash is negative", max_gap)
    if missing_price:
        return ReconcileResult(True, "no price for " + ", ".join(sorted(missing_price)), max_gap)
    if max_gap > band:
        return ReconcileResult(
            True,
            f"weight gap {max_gap:.4f} is above {band:.4f}",
            max_gap,
        )
    return ReconcileResult(False, "account matches the target book", max_gap)
