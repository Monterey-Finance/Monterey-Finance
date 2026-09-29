"""One weekday pass: refresh, target weights, paper fills, NAV."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from ops.account import STARTING_CASH, load_account, save_account
from ops.activity import append_activity
from ops.audit import append_event
from ops.batches import batch_by_id, public_batch, save_batch, transition
from ops.breaches import breach_preview
from ops.cash import record_contribution, take_due_contribution
from ops.data import load_lab, refresh_facts, resolve_as_of
from ops.ledger import already_marked, append_nav, ledger_path, mark_row
from ops.limits import near_limit_flags
from ops.live_rules import BOOK_VERSION
from ops.oms import MIN_NOTIONAL
from ops.persist import persist_session
from ops.pipeline import TradeResult, run_paper_day
from ops.purify_ledger import upsert_entries
from ops.quotes import session_quotes
from ops.ruleset import rules_for_run
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
    venue: str = "local",
    commit: bool = True,
    broker=None,
    selection_cache: dict | None = None,
    cache_dividends: bool | None = None,
) -> SessionResult:
    want = resolve_as_of(as_of)
    refresh_frame = None
    if refresh:
        refresh_frame = refresh_facts(want)

    loaded_from_cache = lab is None
    overlay = None
    if lab is None:
        rules, overlay = rules_for_run(state_root)
        session_lab = load_lab(
            want,
            symbols=symbols,
            lookback_days=lookback_days,
            cache=True,
            rules=rules,
        )
    else:
        session_lab = lab
    book = build_intended_book(session_lab, want, selection_cache=selection_cache)
    if overlay:
        book.book_version = f"{BOOK_VERSION}+{str(overlay.get('id', ''))[:8]}"
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
    contribution = None
    previous_sma = _previous_sma(book.as_of, state_root) if trade else None
    if trade:
        account = load_account(state_root, capital=capital)
        # A halt that never bought anything is not a finished session.
        empty_halt = account.halted and not account.positions and not account.fills
        if already_marked(book.as_of, state_root) and not empty_halt:
            trade_result.fill_basis = "already_marked"
            trade_result.reconcile_reason = "NAV for this session is already on the ledger"
            nav_row = _nav_on(book.as_of, state_root)
            append_event(
                "run_skipped",
                actor="session",
                root=state_root,
                as_of=book.as_of.isoformat(),
                reason="already marked",
            )
        else:
            if empty_halt:
                account.halted = False
                account.halt_reason = ""
            if not account.halted:
                contribution = take_due_contribution(account, book.as_of, state_root)
            divs = dividends
            fetch_divs = loaded_from_cache if cache_dividends is None else cache_dividends
            if divs is None and fetch_divs:
                divs = _cached_dividends(account, book.as_of)
            fail_symbols = _fail_symbols(fails)
            schedule = str(getattr(session_lab.rules.book, "purify_schedule", "ex_date"))
            if venue == "alpaca":
                from ops.alpaca import from_env
                from ops.venues import run_alpaca_day

                trade_result = run_alpaca_day(
                    book,
                    account,
                    session_lab.prices,
                    broker or from_env(),
                    commit=commit,
                    min_notional=min_notional,
                    dividends=divs,
                    impure_ratios=_impure_ratios(session_lab, book.as_of),
                    fail_symbols=fail_symbols,
                    purify_schedule=schedule,
                )
            elif venue != "local":
                raise ValueError("venue must be local or alpaca")
            else:
                trade_result = run_paper_day(
                    book,
                    account,
                    session_lab.prices,
                    min_notional=min_notional,
                    dividends=divs,
                    impure_ratios=_impure_ratios(session_lab, book.as_of),
                    commit=commit,
                    fail_symbols=fail_symbols,
                    purify_schedule=schedule,
                )
            closes = session_quotes(session_lab.prices, book.as_of, "close")
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
            if contribution:
                record_contribution(contribution, state_root)
            _record_operations(
                account,
                book,
                trade_result,
                state_root,
                previous_sma=previous_sma,
            )

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
        **public_batch(trade_result.batch),
    }
    if nav_row:
        extra["nav"] = nav_row.get("nav")
        extra["cash"] = nav_row.get("cash")
        extra["daily_return"] = nav_row.get("daily_return")

    folder = Path()
    if persist:
        tables = _trade_tables(account, trade_result, nav_row)
        tables["near_limits"] = near_limit_flags(book.holdings)
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


def _fail_symbols(fails: pd.DataFrame) -> set[str]:
    if fails is None or fails.empty or "symbol" not in fails.columns:
        return set()
    return {str(symbol) for symbol in fails["symbol"].dropna().unique()}


def _previous_sma(as_of: date, root: Path | None) -> bool | None:
    path = ledger_path(root)
    if not path.exists():
        return None
    frame = pd.read_csv(path)
    if frame.empty or "sma_on" not in frame.columns:
        return None
    day = as_of.isoformat()
    prior = frame.loc[frame["as_of"].astype(str).str.slice(0, 10) < day]
    if prior.empty:
        return None
    return bool(prior.iloc[-1]["sma_on"])


def _record_operations(account, book, trade: TradeResult, root, *, previous_sma: bool | None) -> None:
    if trade.batch:
        save_batch(trade.batch, root)
    if trade.closed_batch_id:
        closed = batch_by_id(root, trade.closed_batch_id)
        if closed and closed.get("status") == "executing":
            save_batch(transition(closed, "completed", actor="session"), root)
    if trade.purification_entries:
        upsert_entries(trade.purification_entries, root)
    if trade.purification_today:
        append_event(
            "purification_posted",
            actor="session",
            root=root,
            as_of=book.as_of.isoformat(),
            amount=trade.purification_today,
        )
        append_activity(
            {
                "as_of": book.as_of.isoformat(),
                "type": "purification_post",
                "symbol": "",
                "amount": -float(trade.purification_today),
                "shares": None,
                "price": None,
                "detail": "ex-date impure dividend",
                "actor": "session",
                "ref": "",
            },
            root,
        )
    for fill in trade.fills:
        if fill.get("status") not in {"filled", "partial"}:
            continue
        price = float(fill.get("price") or 0.0)
        shares = float(fill.get("shares") or 0.0)
        amount = shares * price
        if fill.get("side") == "buy":
            amount = -amount
        append_activity(
            {
                "as_of": str(fill.get("as_of") or book.as_of.isoformat())[:10],
                "type": "fill",
                "symbol": fill.get("symbol"),
                "amount": amount,
                "shares": shares,
                "price": price,
                "detail": fill.get("side"),
                "actor": "session",
                "ref": trade.batch.get("id") if trade.batch else "",
            },
            root,
        )
    if previous_sma is not None and previous_sma != bool(book.sma_on):
        append_activity(
            {
                "as_of": book.as_of.isoformat(),
                "type": "cash_throttle",
                "symbol": "SPY",
                "amount": None,
                "shares": None,
                "price": None,
                "detail": book.sma_reason,
                "actor": "session",
                "ref": "",
            },
            root,
        )
    if account.halted or trade.fill_basis == "halted":
        event = "run_halted"
    else:
        event = "run_completed"
    append_event(
        event,
        actor="session",
        root=root,
        as_of=book.as_of.isoformat(),
        fill_basis=trade.fill_basis,
        halted=bool(account.halted),
        reason=account.halt_reason or trade.reconcile_reason,
    )
    approved = any(step.get("status") == "approved" for step in (trade.batch or {}).get("history") or [])
    if trade.batch and approved:
        append_event(
            "order_batch_approved",
            actor="session",
            root=root,
            as_of=book.as_of.isoformat(),
            batch_id=trade.batch.get("id"),
            n_orders=len(trade.batch.get("orders") or []),
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
