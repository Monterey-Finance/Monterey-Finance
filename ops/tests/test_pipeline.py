"""Paper account, fills, and NAV. No network."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ops.account import PaperAccount, load_account
from ops.ledger import ledger_path
from ops.purify_ops import accrue_purification
from ops.reconcile import reconcile
from ops.session import run_session
from sleeves.lab import Lab
from ops.live_rules import live_rules


def _symbols() -> list[tuple[str, float, float, float]]:
    return [
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


def _lab(spy_start: float, spy_end: float, impure: float | None = None):
    idx = pd.bdate_range("2023-01-02", periods=251)
    as_of = idx[-2].date()
    rows = []
    for sym, margin, cap, debt in _symbols():
        sales = 1e9
        row = {
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
        if impure is not None:
            row["impure_ratio"] = impure
        rows.append(row)
    spy = np.linspace(spy_start, spy_end, len(idx))
    prices = []
    names = [sym for sym, *_ in _symbols()]
    for i, day in enumerate(idx):
        prices.append(
            {
                "symbol": "SPY",
                "date": day.date(),
                "open": spy[i],
                "close": spy[i],
                "adj_close": spy[i],
                "volume": 1_000,
            }
        )
        for name in names:
            prices.append(
                {
                    "symbol": name,
                    "date": day.date(),
                    "open": 10.0,
                    "close": 10.0,
                    "adj_close": 10.0,
                    "volume": 1_000_000,
                }
            )
    lab = Lab.from_frames(
        pd.DataFrame(rows),
        pd.DataFrame(prices),
        rules=live_rules(),
        start=idx[0].date().isoformat(),
        end=idx[-1].date().isoformat(),
    )
    return lab, as_of, idx[-1].date()


def _run(lab, as_of, root, **kwargs):
    return run_session(
        as_of,
        lab=lab,
        refresh=False,
        coverage=False,
        breaches=False,
        trade=True,
        capital=1_000_000,
        runs_root=root / "runs",
        state_root=root / "state",
        **kwargs,
    )


def test_bootstrap_fills_at_close_and_marks_nav(tmp_path):
    lab, as_of, _ = _lab(80, 120)
    result = _run(lab, as_of, tmp_path)
    assert result.extra["fill_basis"] == "close_bootstrap"
    assert result.extra["halted"] is False
    assert result.extra["n_fills"] > 0
    assert result.nav["nav"] == result.nav["nav"]
    assert abs(float(result.nav["nav"]) - 1_000_000) < 5_000
    assert int(result.nav["n_positions"]) >= 5
    assert (tmp_path / "state" / "nav.csv").exists()
    assert (tmp_path / "runs" / as_of.isoformat() / "fills.csv").exists()


def test_same_session_does_not_trade_twice(tmp_path):
    lab, as_of, _ = _lab(80, 120)
    first = _run(lab, as_of, tmp_path)
    shares = dict(load_account(tmp_path / "state").positions)
    second = _run(lab, as_of, tmp_path)
    assert second.extra["fill_basis"] == "already_marked"
    assert load_account(tmp_path / "state").positions == shares
    ledger = pd.read_csv(ledger_path(tmp_path / "state"))
    assert len(ledger) == 1
    assert first.extra["n_fills"] > 0


def test_cash_throttle_holds_no_shares(tmp_path):
    lab, as_of, _ = _lab(120, 80)
    result = _run(lab, as_of, tmp_path)
    assert result.book.sma_on is False
    assert result.extra["halted"] is False
    assert int(result.nav["n_positions"]) == 0
    assert abs(float(result.nav["nav"]) - 1_000_000) < 1e-6


def test_pending_order_fills_at_the_next_open(tmp_path):
    lab, first_day, next_day = _lab(80, 120)
    _run(lab, first_day, tmp_path)
    account = load_account(tmp_path / "state")
    before = int(account.positions["AAA"])
    from ops.account import save_account
    from ops.reconcile import position_weights

    account.pending_targets = position_weights(account, {symbol: 10.0 for symbol in account.positions})
    account.pending = [
        {
            "symbol": "AAA",
            "side": "sell",
            "shares": 1,
            "target_weight": 0.10,
            "created_as_of": first_day.isoformat(),
            "status": "pending",
            "reason": "rebalance",
        }
    ]
    save_account(account, tmp_path / "state")
    result = _run(lab, next_day, tmp_path)
    after = load_account(tmp_path / "state")
    assert int(after.positions["AAA"]) == before - 1
    assert result.extra["fill_basis"] in {"next_open", "queued_next_open"}
    assert any(fill.get("price_field") == "open" for fill in after.fills)


def test_purification_cash_leaves_nav():
    account = PaperAccount(cash=1_000, positions={"AAA": 100})
    paid = accrue_purification(
        account,
        "2024-06-03",
        pd.DataFrame([{"symbol": "AAA", "ex_date": "2024-06-03", "dividend": 1.0}]),
        {"AAA": 0.10},
    )
    assert paid == 10
    assert account.cash == 990
    assert accrue_purification(
        account,
        "2024-06-03",
        pd.DataFrame([{"symbol": "AAA", "ex_date": "2024-06-03", "dividend": 1.0}]),
        {"AAA": 0.10},
    ) == 0


def test_reconcile_halts_when_a_weight_is_far_off():
    account = PaperAccount(cash=1_000_000, positions={})
    check = reconcile(account, {"AAA": 10.0}, {"AAA": 0.50})
    assert check.halt is True
