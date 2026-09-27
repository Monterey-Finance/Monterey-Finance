"""One weekday pass: refresh, target weights, paper fills, NAV."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from ops.account import STARTING_CASH, load_account, save_account
from ops.breaches import breach_preview
from ops.data import load_lab, refresh_facts, resolve_as_of
from ops.ledger import already_marked, append_nav, mark_row
from ops.oms import MIN_NOTIONAL
from ops.persist import persist_session
from ops.pipeline import TradeResult, run_paper_day
from ops.quotes import prices_on
from ops.targets import IntendedBook, build_intended_book
from ops.paths import ensure_research_on_path

ensure_research_on_path()

from sleeves.compliance import last_snapshot_on_or_before  # noqa: E402
from sleeves.lab import Lab  # noqa: E402


@dataclass
class SessionResult:
    book: IntendedBook
    folder: Path
    breaches: pd.DataFrame
    coverage: pd.DataFrame | None = None
    refresh: pd.DataFrame | None = None
    nav: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def run_session(
    as_of: date | str | None = "today",
    *,
    lab: Lab | None = None,
    refresh: bool = False,
    coverage: bool = False,
    persist: bool = True,
    breaches: bool = True,
    trade: bool = True,
    capital: float = STARTING_CASH,
    min_notional: float = MIN_NOTIONAL,
    lookback_days: int = 550,
    symbols: Sequence[str] | None = None,
    breach_lookback_days: int = 10,
    dividends: pd.DataFrame | None = None,
    runs_root: Path | None = None,
    state_root: Path | None = None,
) -> SessionResult:
    want = resolve_as_of(as_of)
    refresh_frame = None
    if refresh:
        refresh_frame = refresh_facts(want)

    loaded_from_cache = lab is None
    session_lab = lab or load_lab(
        want,
        symbols=symbols,
        lookback_days=lookback_days,
        cache=True,
    )
    book = build_intended_book(session_lab, want)
    fails = (
        breach_preview(book, lookback_days=breach_lookback_days, cache=True)
        if breaches
        else pd.DataFrame()
    )

    coverage_frame = None
    if coverage:
        names = symbols or list(session_lab.metrics["symbol"].unique())
        coverage_frame = _coverage_sheet(names, book.as_of)

    nav_row = None
    trade_result = TradeResult()
    account = None
    if trade:
        account = load_account(state_root, capital=capital)
        if already_marked(book.as_of, state_root):
            trade_result.fill_basis = "already_marked"
            trade_result.reconcile_reason = "NAV for this session is already on the ledger"
            nav_row = _nav_on(book.as_of, state_root)
        else:
            divs = dividends
            if divs is None and loaded_from_cache:
                divs = _cached_dividends(account, book.as_of)
            trade_result = run_paper_day(
                book,
                account,
                session_lab.prices,
                min_notional=min_notional,
                dividends=divs,
                impure_ratios=_impure_ratios(session_lab, book.as_of),
            )
            closes = prices_on(session_lab.prices, book.as_of, "close")
            nav_row = mark_row(
                account,
                closes,
                as_of=book.as_of,
                sma_on=book.sma_on,
                purification_today=trade_result.purification_today,
                fill_basis=trade_result.fill_basis,
            )
            frame = append_nav(nav_row, state_root)
            day = book.as_of.isoformat()
            match = frame.loc[frame["as_of"].astype(str).str.slice(0, 10) == day]
            if not match.empty:
                nav_row = match.iloc[-1].to_dict()
            save_account(account, state_root)

    extra = {
        "n_filing_fails": 0 if fails.empty else int(len(fails)),
        "refreshed": refresh,
        "traded": trade,
        "fill_basis": trade_result.fill_basis,
        "reconcile_reason": trade_result.reconcile_reason,
        "max_weight_gap": trade_result.max_gap,
        "n_fills": len([f for f in trade_result.fills if f.get("status") in {"filled", "partial"}]),
        "n_pending": 0 if account is None else len(account.pending),
        "halted": False if account is None else account.halted,
        "halt_reason": "" if account is None else account.halt_reason,
        "purification_today": trade_result.purification_today,
    }
    if nav_row:
        extra["nav"] = nav_row.get("nav")
        extra["cash"] = nav_row.get("cash")
        extra["daily_return"] = nav_row.get("daily_return")

    folder = Path()
    if persist:
        tables = _trade_tables(account, trade_result, nav_row)
        folder = persist_session(
            book,
            breaches=fails,
            coverage=coverage_frame,
            refresh=refresh_frame,
            extra=extra,
            tables=tables,
            root=runs_root,
        )
    return SessionResult(
        book=book,
        folder=folder,
        breaches=fails,
        coverage=coverage_frame,
        refresh=refresh_frame,
        nav=nav_row,
        extra=extra,
    )


def _nav_on(as_of: date, root: Path | None) -> dict | None:
    from ops.ledger import ledger_path

    path = ledger_path(root)
    if not path.exists():
        return None
    frame = pd.read_csv(path)
    day = as_of.isoformat()
    match = frame.loc[frame["as_of"].astype(str).str.slice(0, 10) == day]
    if match.empty:
        return None
    return match.iloc[-1].to_dict()


def _coverage_sheet(symbols: Sequence[str], as_of: date) -> pd.DataFrame:
    import halalquant as hq

    detail = hq.coverage_report(tickers=list(symbols), as_of=as_of, cache=True)
    return hq.coverage_summary(detail)


def _impure_ratios(lab: Lab, as_of: date) -> dict[str, float]:
    metrics = lab.metrics
    if metrics is None or metrics.empty or "impure_ratio" not in metrics.columns:
        return {}
    snap = last_snapshot_on_or_before(metrics, as_of)
    if snap.empty:
        return {}
    ratios: dict[str, float] = {}
    for _, row in snap.iterrows():
        value = pd.to_numeric(row.get("impure_ratio"), errors="coerce")
        if pd.notna(value):
            ratios[str(row["symbol"])] = float(value)
    return ratios


def _cached_dividends(account, as_of: date) -> pd.DataFrame | None:
    symbols = list(account.positions) or None
    try:
        from halalquant.database import LocalCache

        store = LocalCache()
        return store.db.read_dividends(symbols, start=as_of.isoformat(), end=as_of.isoformat())
    except Exception:
        return None


def _trade_tables(account, trade: TradeResult, nav_row: dict | None) -> dict[str, pd.DataFrame]:
    tables: dict[str, pd.DataFrame] = {
        "orders": pd.DataFrame(trade.orders),
        "fills": pd.DataFrame(trade.fills),
    }
    if account is not None:
        tables["positions"] = pd.DataFrame(
            [{"symbol": symbol, "shares": shares} for symbol, shares in sorted(account.positions.items())]
        )
    if nav_row:
        tables["nav"] = pd.DataFrame([nav_row])
    return tables
