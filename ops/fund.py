"""Shadow-fund loop on the monterey simulator.

Live sessions and history replays share ``monterey.sim``. The paper account,
halt flag, cash moves, and audit log stay in ``ops/state``. NAV and holdings
are the ledger under ``ledgers/<book>/<hash>/``.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from monterey.data import from_frames, load_research_data
from monterey.diagnostics import diagnose
from monterey.ledger import Ledger
from monterey.paths import LEDGERS
from monterey.sim import SimState, Simulator, simulate
from monterey.spec import BookSpec
from ops.account import STARTING_CASH, load_account, save_account
from ops.audit import append_event
from ops.live_rules import live_spec
from ops.paths import STATE


def live_ledger_path(spec: BookSpec | None = None, root: Path | None = None) -> Path:
    book = spec or live_spec()
    return (root or LEDGERS) / book.id / book.hash()


def load_live_ledger(spec: BookSpec | None = None, root: Path | None = None) -> Ledger | None:
    folder = live_ledger_path(spec, root)
    if not (folder / "spec.yaml").exists():
        return None
    return Ledger.read(folder)


def replay_book(
    start: date | str,
    end: date | str,
    *,
    spec: BookSpec | None = None,
    refresh: bool = False,
    root: Path | None = None,
    mode: str = "live",
    progress: bool = True,
) -> Ledger:
    """Walk ``[start, end]`` once, write the ledger, and compute diagnostics."""
    book = spec or live_spec()
    first = pd.Timestamp(start).date()
    last = pd.Timestamp(end).date()
    data = load_research_data(first, last, refresh=refresh, progress=progress)
    existing = load_live_ledger(book, root)
    state = None
    resume = first
    if existing is not None and not existing.nav.empty:
        state = SimState.from_dict(existing.manifest.get("state") or {})
        last_marked = pd.Timestamp(existing.nav["date"].iloc[-1]).date()
        after = [d.date() for d in data.sessions_between(first, last) if d.date() > last_marked]
        if not after:
            diagnose(existing, data)
            return existing
        resume = after[0]
    ledger = simulate(book, data, start=resume, end=last, state=state, root=None, mode=mode, progress=progress)
    if existing is not None and resume != first:
        for name, frame in ledger.tables.items():
            existing.append({name: frame})
        existing.manifest["state"] = ledger.manifest.get("state")
        existing.manifest["mode"] = mode
        existing.write(path=live_ledger_path(book, root))
        diagnose(existing, data)
        _sync_account(existing, state_root=None)
        return existing
    ledger.manifest["mode"] = mode
    ledger.write(root or LEDGERS)
    diagnose(ledger, data)
    _sync_account(ledger, state_root=None)
    return ledger


def _sync_account(ledger: Ledger, state_root: Path | None = None) -> None:
    """Keep the paper account and ops/state/nav.csv aligned with the ledger."""
    try:
        account = load_account(state_root)
        state = SimState.from_dict(ledger.manifest.get("state") or {})
        if state.cash is not None:
            account.cash = float(state.cash)
        if state.positions:
            account.positions = dict(state.positions)
        account.pending = list(state.pending or [])
        save_account(account, state_root)
    except Exception:
        pass
    _mirror_nav_csv(ledger, state_root)


def run_live_session(
    as_of: date | str | None = "today",
    *,
    refresh: bool = False,
    capital: float = STARTING_CASH,
    state_root: Path | None = None,
    ledger_root: Path | None = None,
    persist: bool = True,
    venue: str = "local",
) -> dict[str, Any]:
    """One market session: refresh facts, step the simulator, mark the ledger."""
    from ops.data import resolve_as_of, refresh_facts

    want = resolve_as_of(as_of)
    if refresh:
        refresh_facts(want)
    spec = live_spec(state_root)
    account = load_account(state_root, capital=capital)
    if account.halted:
        append_event("run_skipped", actor="session", root=state_root, as_of=want.isoformat(), reason=account.halt_reason)
        return {"as_of": want.isoformat(), "halted": True, "halt_reason": account.halt_reason, "fill_basis": "halted"}

    data = load_research_data(want, want, refresh=False, progress=False)
    if want not in set(d.date() for d in data.sessions_between(want, want)):
        return {"as_of": want.isoformat(), "status": "skipped", "reason": "not a market session"}

    ledger = load_live_ledger(spec, ledger_root)
    if ledger is not None and not ledger.nav.empty:
        marked = set(pd.to_datetime(ledger.nav["date"]).dt.date)
        if want in marked:
            append_event("run_skipped", actor="session", root=state_root, as_of=want.isoformat(), reason="already marked")
            row = ledger.nav[pd.to_datetime(ledger.nav["date"]).dt.date == want].iloc[-1]
            return {"as_of": want.isoformat(), "fill_basis": "already_marked", "nav": float(row["nav"]), "halted": False}

    state = None
    if ledger is not None:
        state = SimState.from_dict(ledger.manifest.get("state") or {})
    else:
        state = SimState(cash=float(account.cash or capital))
        state.positions = dict(account.positions)
        state.pending = list(account.pending)
        state.traded = bool(account.positions or account.fills)

    sim = Simulator(spec, data, state=state)
    out = sim.step(want)
    tables = {name: pd.DataFrame(rows) for name, rows in out.items()}
    if ledger is None:
        ledger = Ledger(spec=spec, tables=tables, manifest={"mode": "live", "state": sim.state.to_dict()})
    else:
        ledger.append(tables)
        ledger.manifest["state"] = sim.state.to_dict()
        ledger.manifest["mode"] = "live"
    if persist:
        ledger.write(ledger_root or LEDGERS)
        try:
            diagnose(ledger, data)
        except Exception:
            pass

    account.cash = float(sim.state.cash)
    account.positions = dict(sim.state.positions)
    account.pending = list(sim.state.pending)
    account.venue = venue
    nav_row = tables["nav"].iloc[-1].to_dict() if not tables["nav"].empty else {}
    account.purification_cumulative += float(nav_row.get("purification") or 0.0)
    save_account(account, state_root)
    _mirror_nav_csv(ledger, state_root)
    append_event("run_completed", actor="session", root=state_root, as_of=want.isoformat(), nav=nav_row.get("nav"))
    return {
        "as_of": want.isoformat(),
        "book": spec.id,
        "hash": spec.hash(),
        "nav": nav_row.get("nav"),
        "cash": nav_row.get("cash"),
        "n_positions": nav_row.get("n_positions"),
        "exposure": nav_row.get("exposure"),
        "n_fills": nav_row.get("n_fills"),
        "halted": False,
        "fill_basis": "close_bootstrap" if not sim.state.pending and int(nav_row.get("n_fills") or 0) else ("queued_next_open" if sim.state.pending else "next_open"),
        "ledger": str(ledger.path) if ledger.path else "",
    }


def archive_v1_ledger(state_root: Path | None = None, dest: Path | None = None) -> Path:
    """Copy the CSV paper NAV into a monterey ledger folder for the frozen v1 spec."""
    from ops.ledger import ledger_path

    spec = BookSpec.load("fcf-sma-v1")
    nav = pd.read_csv(ledger_path(state_root))
    nav = nav.rename(columns={"as_of": "date"})
    nav["date"] = pd.to_datetime(nav["date"])
    for column, default in (("exposure", None), ("regime_on", None), ("regime_raw", None), ("n_targets", None), ("n_fills", None), ("n_orders", None), ("traded_notional", None), ("costs", 0.0), ("dividends", 0.0), ("purification", None), ("snapshot", None), ("max_gap", None)):
        if column not in nav.columns:
            if column == "regime_on" and "sma_on" in nav.columns:
                nav[column] = nav["sma_on"]
            elif column == "exposure" and "sma_on" in nav.columns:
                nav[column] = nav["sma_on"].astype(float)
            elif column == "purification" and "purification_today" in nav.columns:
                nav[column] = nav["purification_today"]
            else:
                nav[column] = default
    ledger = Ledger(spec=spec, tables={"nav": nav}, manifest={"mode": "archive", "source": "ops/state/nav.csv", "note": "v1 paper path; positions live in ops/runs"})
    folder = dest or (LEDGERS / spec.id / spec.hash())
    return ledger.write(path=folder)


def _mirror_nav_csv(ledger: Ledger, state_root: Path | None) -> None:
    """Keep ops/state/nav.csv in sync so older readers still work during the cutover."""
    path = (state_root or STATE) / "nav.csv"
    frame = ledger.nav.copy()
    if frame.empty:
        return
    out = pd.DataFrame(
        {
            "as_of": pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d"),
            "nav": frame["nav"],
            "cash": frame["cash"],
            "invested": frame["invested"],
            "daily_return": frame["daily_return"],
            "n_positions": frame["n_positions"],
            "sma_on": frame["regime_on"],
            "halted": False,
            "purification_today": frame["purification"],
            "purification_cumulative": frame["purification"].cumsum(),
            "fill_basis": "",
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False)


def data_from_lab(lab):
    return from_frames(
        lab.metrics,
        lab.prices,
        start=lab.start,
        end=lab.end,
        extras={"roic_history": lab.roic_history, "sue_events": lab.sue_events},
    )
