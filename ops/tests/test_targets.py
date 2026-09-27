"""Offline tests for the intended book. No broker. No network."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from ops.live_rules import BOOK_VERSION, live_rules
from ops.persist import persist_session
from ops.session import run_session
from ops.targets import build_intended_book
from sleeves.lab import Lab


def _metrics(as_of: date) -> pd.DataFrame:
    names = [
        ("AAA", 0.40, 1e11, 0.05),
        ("BBB", 0.20, 8e10, 0.08),
        ("CCC", 0.10, 5e10, 0.12),
        ("DDD", 0.02, 4e10, 0.10),
        ("EEE", -0.05, 3e10, 0.09),
        ("FFF", 0.30, 2e10, 0.07),
        ("GGG", 0.25, 1.5e10, 0.06),
        ("HHH", 0.18, 1.2e10, 0.11),
        ("III", 0.15, 1.1e10, 0.04),
        ("JJJ", 0.12, 1.0e10, 0.03),
        ("KKK", 0.08, 9e9, 0.02),
        ("LLL", 0.06, 8e9, 0.15),
        ("MMM", 0.05, 7e9, 0.20),
        ("NNN", 0.04, 6e9, 0.18),
        ("OOO", 0.03, 5e9, 0.16),
        ("PPP", 0.35, 4e9, 0.01),
        ("QQQ", 0.28, 3e9, 0.02),
        ("RRR", 0.22, 2e9, 0.03),
        ("SSS", 0.16, 1.5e9, 0.04),
        ("TTT", 0.14, 1.2e9, 0.05),
        ("UUU", 0.11, 1.0e9, 0.06),
    ]
    rows = []
    for sym, margin, cap, debt in names:
        sales = 1e9
        rows.append(
            {
                "symbol": sym,
                "as_of": as_of,
                "market_cap": cap,
                "market_cap_24m": cap,
                "total_debt": debt * cap,
                "cash_and_equiv": 0.02 * cap,
                "interest_bearing_securities": 0.0,
                "receivables": 0.05 * cap,
                "liquid_assets": 0.0,
                "total_revenue": sales,
                "fcf": margin * sales,
                "free_cash_flow": margin * sales,
            }
        )
    return pd.DataFrame(rows)


def _prices(idx: pd.DatetimeIndex, spy_start: float, spy_end: float) -> pd.DataFrame:
    spy = np.linspace(spy_start, spy_end, len(idx))
    rows = []
    for i, day in enumerate(idx):
        rows.append(
            {
                "symbol": "SPY",
                "date": day.date(),
                "open": spy[i],
                "high": spy[i],
                "low": spy[i],
                "close": spy[i],
                "volume": 1_000,
                "adj_close": spy[i],
            }
        )
    return pd.DataFrame(rows)


def _lab(spy_start: float, spy_end: float) -> tuple[Lab, date]:
    idx = pd.bdate_range("2023-01-02", periods=250)
    as_of = idx[-1].date()
    rules = live_rules()
    lab = Lab.from_frames(
        _metrics(as_of),
        _prices(idx, spy_start, spy_end),
        rules=rules,
        start=idx[0].date().isoformat(),
        end=as_of.isoformat(),
    )
    return lab, as_of


def test_live_rules_are_the_phase_1b_book():
    book = live_rules().book
    assert book.sleeve_weights["fcf_quality"] == 1.0
    assert book.name_cap == 0.10
    assert book.throttle == "spy_sma"
    assert book.breach_exit == "next_open"
    assert book.purify_schedule == "ex_date"


def test_intended_book_holds_stocks_when_spy_is_above_sma(tmp_path):
    lab, as_of = _lab(80.0, 120.0)
    book = build_intended_book(lab, as_of)
    assert book.sma_on is True
    assert book.cash_weight < 1e-9
    assert len(book.holdings) >= 20
    assert abs(float(book.holdings["target_weight"].sum()) - 1.0) < 1e-8
    assert book.holdings["target_weight"].max() <= 0.10 + 1e-9
    assert book.book_version == BOOK_VERSION
    folder = persist_session(book, root=tmp_path)
    written = pd.read_csv(folder / "intended_book.csv")
    assert "AAA" in set(written["symbol"])
    assert (folder / "summary.json").exists()


def test_intended_book_is_cash_when_spy_is_below_sma():
    lab, as_of = _lab(120.0, 80.0)
    book = build_intended_book(lab, as_of)
    assert book.sma_on is False
    assert book.cash_weight == 1.0
    assert book.holdings.empty
    assert len(book.invested) >= 20


def test_run_session_writes_files_without_refresh(tmp_path):
    lab, as_of = _lab(80.0, 120.0)
    result = run_session(
        as_of,
        lab=lab,
        refresh=False,
        coverage=False,
        persist=True,
        breaches=False,
        trade=False,
        runs_root=tmp_path,
    )
    assert result.book.sma_on is True
    assert (result.folder / "intended_book.csv").exists()
    assert result.extra["n_filing_fails"] == 0
