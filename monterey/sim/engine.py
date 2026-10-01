"""The one simulator. Research replays, the shadow fund, and experiments all step through here.

One session ``t``:

1. Holders at the prior close receive dividends with ex-date ``t``; purification leaves cash.
2. Orders created at close ``t−1`` fill at open ``t`` (sells first, whole shares, cash-limited, cost charged).
3. At close ``t``: overlay exposure, the monthly selection (rebuilt on a new metrics
   snapshot), breach exits from filings known by ``t``, then target weights.
4. Orders to reach the targets are created at close ``t`` and wait for open ``t+1``.
   The very first session fills at the close so a NAV exists.
5. A held name with no price for a week is cashed out at its last close (delisting).
6. NAV is marked at close ``t``.

Nothing decided at close ``t`` earns the return of day ``t``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from monterey.data import ResearchData
from monterey.layers.accounting import settle_dividends
from monterey.layers.construction import build_weights, drop_and_renormalise
from monterey.layers.execution import equity, fill_orders, plan_orders
from monterey.layers.overlay import regime
from monterey.layers.screen import screen
from monterey.layers.signals import Context, run_brain
from monterey.ledger import TABLES, Ledger
from monterey.spec import BookSpec

# A missing quote falls back to the last real print within this many rows (~10 calendar days).
STALE_ROWS = 7


@dataclass
class SimState:
    cash: float
    positions: dict[str, float] = field(default_factory=dict)
    pending: list[dict] = field(default_factory=list)
    traded: bool = False
    exposure: float | None = None
    snapshot: str | None = None
    breached: dict[str, str] = field(default_factory=dict)
    last_close: dict[str, float] = field(default_factory=dict)
    last_targets: dict[str, float] = field(default_factory=dict)
    last_day: str | None = None
    last_nav: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SimState":
        known = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        return cls(**known)


@dataclass
class Selection:
    stamp: date | None
    weights: pd.Series
    detail: pd.DataFrame
    screen: pd.DataFrame


class Simulator:
    def __init__(self, spec: BookSpec, data: ResearchData, state: SimState | None = None) -> None:
        self.spec = spec
        self.data = data
        self.state = state or SimState(cash=float(spec.accounting["capital"]))
        self.sessions = data.sessions
        self.regime = regime(data, spec, self.sessions)
        self.close = data.prices.close.ffill(limit=STALE_ROWS)
        self.open = data.prices.open.ffill(limit=STALE_ROWS)
        self.cost_bps = float(spec.accounting["cost_bps"])
        self._selections: dict[Any, Selection] = {}

    # ---------------- inputs ----------------
    @staticmethod
    def _quotes(panel: pd.DataFrame, day: pd.Timestamp) -> dict[str, float]:
        if panel.empty or day not in panel.index:
            prior = panel.loc[:day]
            if prior.empty:
                return {}
            row = prior.iloc[-1]
        else:
            row = panel.loc[day]
        row = row[row > 0]
        return {str(k): float(v) for k, v in row.items()}

    def selection(self, day: pd.Timestamp) -> Selection:
        stamp = self.data.snapshot_on_or_before(day)
        if stamp in self._selections:
            return self._selections[stamp]
        table = screen(self.data, day, self.spec)
        ctx = Context(data=self.data, spec=self.spec, as_of=day.date(), screen=table)
        detail = run_brain(ctx)
        weights = build_weights(detail, self.spec, self.data.sectors)
        chosen = Selection(stamp=stamp, weights=weights, detail=detail, screen=table)
        self._selections[stamp] = chosen
        return chosen

    # ---------------- one session ----------------
    def step(self, day) -> dict[str, list[dict]]:
        day = pd.Timestamp(day).normalize()
        s = self.state
        spec = self.spec
        label = day.date().isoformat()
        out: dict[str, list[dict]] = {name: [] for name in TABLES}
        closes = self._quotes(self.close, day)
        opens = self._quotes(self.open, day)
        for symbol, price in closes.items():
            opens.setdefault(symbol, price)

        # 1. Dividends to holders at the prior close.
        holders = dict(s.positions)
        paid = self.data.dividends_by_day.get(day, [])
        flows = settle_dividends(s, holders, paid, self.data.impure_ratios(day), spec, day=label) if paid else []
        out["cashflows"].extend(flows)

        # 2. Yesterday's orders fill at today's open.
        fills: list[dict] = []
        if s.pending:
            fills.extend(fill_orders(s, s.pending, opens, day=label, price_field="open", cost_bps=self.cost_bps))
            s.pending = []
        max_gap = _max_gap(s, closes, s.last_targets) if fills else None

        # 3. Targets at today's close.
        reg = self.regime.loc[day] if day in self.regime.index else None
        exposure = float(reg["exposure"]) if reg is not None else 0.0
        chosen = self.selection(day)
        stamp = None if chosen.stamp is None else chosen.stamp.isoformat()
        rebuilt = stamp != s.snapshot
        if rebuilt:
            s.snapshot = stamp
            if stamp is not None:
                s.breached = {k: v for k, v in s.breached.items() if v > stamp}
            out["events"].append({"date": label, "type": "rebuild", "symbol": "", "detail": f"snapshot {stamp}, {len(chosen.weights)} names"})
        if s.exposure is not None and exposure != s.exposure:
            out["events"].append({"date": label, "type": "switch", "symbol": spec.overlay.get("ticker", ""), "detail": f"exposure {s.exposure:.2f} -> {exposure:.2f}"})

        new_breach = False
        watch = set(chosen.weights.index) | set(s.positions)
        prior = s.last_day or (day - pd.Timedelta(days=1)).date().isoformat()
        breaches = self.data.breaches_between(prior, day, watch)
        sell_breaches = str(spec.screen["breach_exit"]) == "next_open"
        for row in breaches.drop_duplicates("symbol").itertuples(index=False):
            symbol = str(row.symbol)
            filed = pd.Timestamp(row.filed_date).date().isoformat()
            out["events"].append({"date": label, "type": "breach", "symbol": symbol, "detail": f"{row.reason} (filed {filed}); {'sell next open' if sell_breaches else 'reported only'}"})
            if sell_breaches:
                s.breached[symbol] = filed
                new_breach = True
        invested = chosen.weights
        blocked = [n for n in s.breached if n in invested.index] if sell_breaches else []
        if blocked:
            invested = drop_and_renormalise(invested, blocked, spec, self.data.sectors)
        targets = {str(k): float(v) * exposure for k, v in invested.items() if float(v) * exposure > 0}

        # 4. Orders for the next open (or a close fill on the very first session).
        trigger = rebuilt or new_breach or exposure != s.exposure or not s.traded
        exits_only = str(spec.execution["rebalance"]) == "on_signal" and not trigger
        if exposure <= 0:
            default_reason = "SMA cash"
        elif rebuilt:
            default_reason = "monthly rebuild"
        else:
            default_reason = "rebalance"
        reasons = {n: "filing breach" for n in blocked}
        orders = plan_orders(s, targets, closes, spec, as_of=label, reasons=reasons, default_reason=default_reason, exits_only=exits_only)
        actionable = [o for o in orders if o.get("status") != "rejected"]
        for order in orders:
            out["orders"].append({"date": label, **{k: order.get(k) for k in ("symbol", "side", "shares", "target_weight", "current_weight", "drift", "price_ref", "notional", "est_cost", "status", "reason")}})
        if not s.traded and actionable and str(spec.execution["first_fill"]) == "close":
            fills.extend(fill_orders(s, actionable, closes, day=label, price_field="close", cost_bps=self.cost_bps))
        else:
            s.pending = actionable
        if any(f.get("status") in {"filled", "partial"} for f in fills):
            s.traded = True
        s.exposure = exposure
        s.last_targets = targets

        # 5. Delisted names are cashed at their last real close.
        for symbol in list(s.positions):
            if symbol in closes:
                s.last_close[symbol] = closes[symbol]
                continue
            price = s.last_close.get(symbol)
            shares = float(s.positions.pop(symbol))
            if price:
                s.cash += shares * price
            out["events"].append({"date": label, "type": "delisted", "symbol": symbol, "detail": f"no price for {STALE_ROWS} sessions; cashed {shares:,.0f} at {price}"})
        for symbol in list(s.last_close):
            if symbol not in s.positions:
                s.last_close.pop(symbol, None)

        # 6. Mark.
        nav = equity(s, closes)
        good = [f for f in fills if f.get("status") in {"filled", "partial"}]
        notional = float(sum(float(f["shares"]) * float(f["price"]) for f in good))
        costs = float(sum(float(f.get("cost") or 0.0) for f in good))
        for f in fills:
            out["fills"].append(
                {
                    "date": label,
                    "symbol": f.get("symbol"),
                    "side": f.get("side"),
                    "shares": f.get("shares"),
                    "price": f.get("price"),
                    "notional": (float(f["shares"]) * float(f["price"])) if f.get("price") else None,
                    "cost": f.get("cost"),
                    "price_field": f.get("price_field"),
                    "status": f.get("status"),
                    "reason": f.get("reason"),
                    "detail": f.get("detail"),
                }
            )
        if costs:
            out["cashflows"].append({"date": label, "type": "cost", "symbol": "", "amount": -costs, "shares": None, "per_share": None, "ratio": None})
        detail = chosen.detail.set_index("symbol") if not chosen.detail.empty else pd.DataFrame()
        table = chosen.screen.set_index("symbol") if not chosen.screen.empty else pd.DataFrame()
        for symbol in sorted(set(targets) | set(s.positions)):
            shares = float(s.positions.get(symbol, 0.0))
            price = closes.get(symbol)
            value = shares * price if price else 0.0
            info = detail.loc[symbol] if symbol in detail.index else None
            verdict = table.loc[symbol] if symbol in table.index else None
            reason = None if verdict is None else verdict.get("reason")
            if symbol in s.breached:
                reason = "filing breach"
            out["positions"].append(
                {
                    "date": label,
                    "symbol": symbol,
                    "shares": shares,
                    "price": price,
                    "value": value,
                    "weight": value / nav if nav > 0 else 0.0,
                    "target_weight": targets.get(symbol, 0.0),
                    "invested_weight": float(invested.get(symbol, 0.0)) if symbol in invested.index else 0.0,
                    "sector": self.data.sectors.get(symbol),
                    "screen_reason": reason,
                    "score": None if info is None else _num(info.get("score")),
                    "market_cap": None if verdict is None else _num(verdict.get("market_cap")),
                    "debt_ratio": None if verdict is None else _num(verdict.get("debt_ratio")),
                    "cash_ratio": None if verdict is None else _num(verdict.get("cash_ratio")),
                    "receivables_ratio": None if verdict is None else _num(verdict.get("receivables_ratio")),
                }
            )
        divs = float(sum(r["amount"] for r in flows if r["type"] == "dividend"))
        purification = float(-sum(r["amount"] for r in flows if r["type"] == "purification"))
        out["nav"].append(
            {
                "date": label,
                "nav": nav,
                "cash": float(s.cash),
                "invested": nav - float(s.cash),
                "daily_return": (nav / s.last_nav - 1.0) if s.last_nav else 0.0,
                "exposure": exposure,
                "regime_on": None if reg is None else bool(reg["on"]),
                "regime_raw": None if reg is None else bool(reg["raw"]),
                "n_positions": len(s.positions),
                "n_targets": len(targets),
                "n_fills": len(good),
                "n_orders": len(actionable),
                "traded_notional": notional,
                "costs": costs,
                "dividends": divs,
                "purification": purification,
                "snapshot": stamp,
                "max_gap": max_gap,
            }
        )
        s.last_nav = nav
        s.last_day = label
        return out


def simulate(
    spec: BookSpec,
    data: ResearchData,
    start=None,
    end=None,
    *,
    root=None,
    mode: str = "replay",
    state: SimState | None = None,
    progress: bool = False,
) -> Ledger:
    """Run ``spec`` over every session in ``[start, end]`` and return its ledger (written when ``root`` is set)."""
    sim = Simulator(spec, data, state=state)
    days = data.sessions_between(start or data.start, end or data.end)
    rows: dict[str, list[dict]] = {name: [] for name in TABLES}
    for i, day in enumerate(days):
        out = sim.step(day)
        for name in TABLES:
            rows[name].extend(out[name])
        if progress and i % 250 == 0:
            print(f"[monterey.sim] {spec.id} {day.date()} nav {sim.state.last_nav:,.0f}", flush=True)
    ledger = Ledger(
        spec=spec,
        tables={name: pd.DataFrame(rows[name]) for name in TABLES},
        manifest={
            "mode": mode,
            "data_snapshot": data.manifest.get("hash"),
            "halalquant_version": data.manifest.get("halalquant_version"),
            "state": sim.state.to_dict(),
        },
    )
    if root is not None:
        ledger.write(root)
    return ledger


def _max_gap(state: SimState, closes: dict[str, float], targets: dict[str, float]) -> float | None:
    nav = equity(state, closes)
    if nav <= 0:
        return None
    names = set(targets) | set(state.positions)
    gaps = []
    for symbol in names:
        price = closes.get(symbol)
        held = float(state.positions.get(symbol, 0.0))
        actual = held * price / nav if price else 0.0
        gaps.append(abs(actual - float(targets.get(symbol, 0.0))))
    return max(gaps) if gaps else 0.0


def _num(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None
