"""Read the paper ledger into one snapshot. The terminal does not trade."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ops.paths import RUNS, STATE

AAOIFI = (("debt", 0.30), ("cash", 0.30), ("receivables", 0.70))
COST_BPS = 10.0


@dataclass
class Holding:
    symbol: str
    target_weight: float = 0.0
    invested_weight: float = 0.0
    shares: float = 0.0
    price: float | None = None
    market_value: float | None = None
    actual_weight: float | None = None
    drift: float | None = None
    fcf_margin: float | None = None
    market_cap: float | None = None
    debt_ratio: float | None = None
    cash_ratio: float | None = None
    receivables_ratio: float | None = None
    name_capped: bool = False
    screen: str = "—"
    nearest_gap: float | None = None
    nearest_name: str = ""


@dataclass
class Desk:
    as_of: str = ""
    nav: float | None = None
    cash: float = 0.0
    invested: float = 0.0
    daily_return: float | None = None
    n_positions: int = 0
    sma_on: bool | None = None
    sma_reason: str = ""
    halted: bool = False
    halt_reason: str = ""
    book_version: str = ""
    fill_basis: str = ""
    reconcile_reason: str = ""
    purification_today: float = 0.0
    purification_cumulative: float = 0.0
    purification_payable: float = 0.0
    name_cap: float = 0.10
    cash_weight: float | None = None
    starting_cash: float = 0.0
    venue: str = "local"
    holdings: list[Holding] = field(default_factory=list)
    nav_points: list[dict] = field(default_factory=list)
    fills: list[dict] = field(default_factory=list)
    pending: list[dict] = field(default_factory=list)
    activity: list[dict] = field(default_factory=list)
    audit: list[dict] = field(default_factory=list)
    purification_rows: list[dict] = field(default_factory=list)
    near: list[dict] = field(default_factory=list)
    fails: list[dict] = field(default_factory=list)
    health: dict = field(default_factory=dict)
    contribution: dict = field(default_factory=dict)
    rules: list[tuple[str, str]] = field(default_factory=list)
    cash_path: list[dict] = field(default_factory=list)
    sessions: list[dict] = field(default_factory=list)
    source: str = ""

    def holding(self, symbol: str) -> Holding | None:
        for row in self.holdings:
            if row.symbol == symbol:
                return row
        return None

    def matches(self, symbol: str, query: str) -> bool:
        if not query:
            return True
        return query.upper() in symbol.upper()


def load_desk(state: Path | None = None, runs: Path | None = None) -> Desk:
    state_root = state or STATE
    runs_root = runs or RUNS
    desk = Desk(source=str(state_root))
    account = _read_json(state_root / "account.json")
    nav = _read_table(state_root / "nav.csv")
    desk.nav_points = _records(nav)
    latest = desk.nav_points[-1] if desk.nav_points else {}
    desk.as_of = str(latest.get("as_of") or "")[:10]
    desk.nav = _float(latest.get("nav"))
    desk.cash = _float(account.get("cash"), latest.get("cash")) or 0.0
    desk.invested = _float(latest.get("invested")) or 0.0
    desk.daily_return = _float(latest.get("daily_return"))
    desk.n_positions = int(_float(latest.get("n_positions")) or len(account.get("positions") or {}))
    desk.sma_on = _bool(latest.get("sma_on"))
    desk.halted = bool(account.get("halted")) or _bool(latest.get("halted")) is True
    desk.halt_reason = str(account.get("halt_reason") or "")
    desk.fill_basis = str(latest.get("fill_basis") or "")
    desk.purification_today = _float(latest.get("purification_today")) or 0.0
    desk.purification_cumulative = _float(
        account.get("purification_cumulative"), latest.get("purification_cumulative")
    ) or 0.0
    desk.purification_payable = _float(account.get("purification_payable")) or 0.0
    desk.starting_cash = _float(account.get("starting_cash")) or 0.0
    desk.venue = str(account.get("venue") or "local")
    desk.fills = list(account.get("fills") or [])
    desk.pending = list(account.get("pending") or [])
    positions = {str(k): float(v) for k, v in (account.get("positions") or {}).items()}
    prices = _last_prices(desk.fills)

    run_dir = _latest_run(runs_root)
    summary: dict = {}
    intended = pd.DataFrame()
    if run_dir is not None:
        summary = _read_json(run_dir / "summary.json")
        intended = _read_table(run_dir / "intended_book.csv")
        desk.near = _records(_read_table(run_dir / "near_limits.csv"))
        desk.fails = _records(_read_table(run_dir / "filing_fails.csv"))
        if not desk.as_of:
            desk.as_of = str(summary.get("as_of") or run_dir.name)[:10]
    desk.book_version = str(summary.get("book_version") or "")
    desk.sma_reason = str(summary.get("sma_reason") or "")
    if summary.get("sma_on") is not None and desk.sma_on is None:
        desk.sma_on = bool(summary.get("sma_on"))
    desk.reconcile_reason = str(summary.get("reconcile_reason") or "")
    desk.name_cap = _float(summary.get("name_cap")) or 0.10
    desk.cash_weight = _float(summary.get("cash_weight"))
    if not desk.halt_reason:
        desk.halt_reason = str(summary.get("halt_reason") or "")

    desk.holdings = _holdings(intended, positions, prices, desk.nav, desk.name_cap)
    desk.activity = _records(_read_table(state_root / "activity.csv"))
    desk.audit = _read_jsonl(state_root / "audit.jsonl")
    desk.purification_rows = _records(_read_table(state_root / "purification.csv"))
    desk.contribution = _read_json(state_root / "contribution.json")
    desk.health = _health(state_root)
    desk.rules = _rules(desk.book_version)
    desk.cash_path = _cash_path(desk)
    desk.sessions = _sessions(runs_root, desk.nav_points, desk.fills)
    return desk


def _holdings(
    intended: pd.DataFrame,
    positions: dict[str, float],
    prices: dict[str, float],
    nav: float | None,
    name_cap: float,
) -> list[Holding]:
    rows: dict[str, Holding] = {}
    if intended is not None and not intended.empty and "symbol" in intended.columns:
        for record in intended.to_dict("records"):
            symbol = str(record.get("symbol") or "")
            if not symbol:
                continue
            weight = _float(record.get("target_weight")) or 0.0
            if weight <= 0 and symbol not in positions:
                continue
            holding = Holding(
                symbol=symbol,
                target_weight=weight,
                invested_weight=_float(record.get("invested_weight")) or weight,
                fcf_margin=_float(record.get("fcf_margin")),
                market_cap=_float(record.get("market_cap")),
                debt_ratio=_float(record.get("debt_ratio")),
                cash_ratio=_float(record.get("cash_ratio")),
                receivables_ratio=_float(record.get("receivables_ratio")),
                name_capped=bool(record.get("name_capped") in {True, "True", "true", 1}),
            )
            _screen(holding)
            rows[symbol] = holding
    for symbol, shares in positions.items():
        holding = rows.get(symbol) or Holding(symbol=symbol)
        holding.shares = float(shares)
        rows[symbol] = holding
    nav_value = nav or 0.0
    ranked: list[Holding] = []
    for holding in rows.values():
        if holding.shares <= 0 and holding.target_weight <= 0:
            continue
        if holding.shares <= 0:
            holding.shares = float(positions.get(holding.symbol, 0.0))
        price = prices.get(holding.symbol)
        holding.price = price
        if price is not None and holding.shares > 0:
            holding.market_value = holding.shares * price
            if nav_value > 0:
                holding.actual_weight = holding.market_value / nav_value
                holding.drift = holding.target_weight - holding.actual_weight
        elif nav_value > 0 and holding.target_weight > 0 and holding.shares <= 0:
            holding.drift = holding.target_weight
        if holding.name_capped is False and name_cap and holding.target_weight >= name_cap - 1e-9:
            holding.name_capped = True
        _nearest(holding)
        ranked.append(holding)
    ranked.sort(key=lambda row: (-(row.actual_weight or row.target_weight), row.symbol))
    return ranked


def _screen(holding: Holding) -> None:
    ratios = (holding.debt_ratio, holding.cash_ratio, holding.receivables_ratio)
    lines = (0.30, 0.30, 0.70)
    if any(value is None for value in ratios):
        holding.screen = "—"
        return
    holding.screen = "PASS" if all(value < line for value, line in zip(ratios, lines)) else "REVIEW"


def _nearest(holding: Holding) -> None:
    gaps = []
    for name, line, value in (
        ("debt", 0.30, holding.debt_ratio),
        ("cash", 0.30, holding.cash_ratio),
        ("recv", 0.70, holding.receivables_ratio),
    ):
        if value is None:
            continue
        gaps.append((line - value, name))
    if not gaps:
        return
    gap, name = min(gaps, key=lambda item: item[0])
    holding.nearest_gap = gap
    holding.nearest_name = name


def _last_prices(fills: list[dict]) -> dict[str, float]:
    prices: dict[str, float] = {}
    for fill in fills:
        price = _float(fill.get("price"))
        symbol = str(fill.get("symbol") or "")
        if symbol and price and price > 0 and fill.get("status") in {None, "filled", "partial"}:
            prices[symbol] = price
    return prices


def _cash_path(desk: Desk) -> list[dict]:
    cash = float(desk.starting_cash or 0.0)
    rows = [{"step": "start", "symbol": "", "side": "", "amount": 0.0, "cash": cash}]
    for fill in desk.fills:
        price = _float(fill.get("price")) or 0.0
        shares = _float(fill.get("shares")) or 0.0
        amount = shares * price
        side = str(fill.get("side") or "")
        if side == "buy":
            cash -= amount
            signed = -amount
        else:
            cash += amount
            signed = amount
        rows.append(
            {
                "step": str(fill.get("as_of") or "")[:10],
                "symbol": fill.get("symbol") or "",
                "side": side,
                "amount": signed,
                "cash": cash,
            }
        )
    rows.append(
        {
            "step": "book",
            "symbol": "",
            "side": "gap",
            "amount": desk.cash - cash,
            "cash": desk.cash,
        }
    )
    return rows


def _rules(version: str) -> list[tuple[str, str]]:
    rows = [("book", version or "1b-fcf-sma-v1")]
    try:
        from ops.live_rules import BOOK_VERSION, live_rules

        book = live_rules().book
        rows = [
            ("book", version or BOOK_VERSION),
            ("sleeve", "FCF quality 100%"),
            ("name cap", f"{float(book.name_cap or 0):.0%}"),
            ("throttle", str(book.throttle)),
            ("breach exit", str(book.breach_exit)),
            ("purify", str(book.purify_schedule)),
            ("rebalance", str(book.rebalance_freq)),
            ("cost", f"{float(book.cost_bps):.0f} bp"),
            ("debt line", "30%"),
            ("cash line", "30%"),
            ("receivables line", "70%"),
        ]
    except Exception as exc:
        rows.append(("rules", str(exc)))
    return rows


def _health(root: Path) -> dict:
    try:
        from ops.health import health_report

        return health_report(root=root)
    except Exception as exc:
        return {"reason": str(exc), "n_sessions": 0, "sessions_required": 20}


def _sessions(runs_root: Path, nav_points: list[dict], fills: list[dict] | None = None) -> list[dict]:
    """One record per day the fund was marked or a run folder was written. Newest first."""
    nav_by_day = {}
    for point in nav_points:
        day = str(point.get("as_of") or "")[:10]
        if day:
            nav_by_day[day] = point
    summaries: dict[str, dict] = {}
    if runs_root.exists():
        for path in runs_root.iterdir():
            if not path.is_dir() or not path.name[:4].isdigit():
                continue
            summary = _read_json(path / "summary.json")
            day = str(summary.get("as_of") or path.name)[:10]
            if day:
                summaries[day] = summary
    fill_counts: dict[str, int] = {}
    for fill in fills or []:
        if fill.get("status") not in {None, "filled", "partial"}:
            continue
        day = str(fill.get("as_of") or "")[:10]
        if day:
            fill_counts[day] = fill_counts.get(day, 0) + 1
    days = sorted(set(nav_by_day) | set(summaries) | set(fill_counts), reverse=True)
    rows = []
    for day in days:
        summary = summaries.get(day) or {}
        nav_row = nav_by_day.get(day) or {}
        ledger_basis = str(nav_row.get("fill_basis") or "")
        summary_basis = str(summary.get("fill_basis") or "")
        basis = ledger_basis or summary_basis
        if summary_basis == "already_marked" and ledger_basis:
            basis = ledger_basis
        sma = summary.get("sma_on")
        if sma is None:
            sma = nav_row.get("sma_on")
        rows.append(
            {
                "as_of": day,
                "nav": _float(nav_row.get("nav"), summary.get("nav")),
                "daily_return": _float(nav_row.get("daily_return"), summary.get("daily_return")),
                "cash": _float(nav_row.get("cash"), summary.get("cash")),
                "n_positions": int(_float(nav_row.get("n_positions"), summary.get("n_holdings")) or 0),
                "n_fills": max(int(_float(summary.get("n_fills")) or 0), fill_counts.get(day, 0)),
                "n_pending": int(_float(summary.get("n_pending")) or 0),
                "sma_on": _bool(sma),
                "sma_reason": str(summary.get("sma_reason") or ""),
                "halted": bool(summary.get("halted")) or _bool(nav_row.get("halted")) is True,
                "halt_reason": str(summary.get("halt_reason") or ""),
                "fill_basis": basis,
                "reconcile_reason": str(summary.get("reconcile_reason") or ""),
                "purification_today": _float(summary.get("purification_today"), nav_row.get("purification_today")) or 0.0,
                "n_filing_fails": int(_float(summary.get("n_filing_fails")) or 0),
            }
        )
    return rows


def _latest_run(root: Path) -> Path | None:
    if not root.exists():
        return None
    days = sorted(path for path in root.iterdir() if path.is_dir() and path.name[:4].isdigit())
    for path in reversed(days):
        if (path / "summary.json").exists() or (path / "intended_book.csv").exists():
            return path
    return None


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _read_table(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size < 2:
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except (OSError, pd.errors.ParserError, ValueError):
        return pd.DataFrame()


def _records(frame: pd.DataFrame) -> list[dict]:
    if frame is None or frame.empty:
        return []
    return frame.to_dict("records")


def _float(*values) -> float | None:
    for value in values:
        if value is None or value == "":
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number == number:
            return number
    return None


def _bool(value) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes"}:
        return True
    if text in {"0", "false", "no"}:
        return False
    return None
