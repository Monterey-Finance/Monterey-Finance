"""Cash, audit, order drafts, the paper broker, and the session calendar."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from ops.account import PaperAccount, load_account
from ops.alpaca import AlpacaClient, AlpacaError, submit_orders
from ops.audit import read_events
from ops.batches import load_batches
from ops.cash import set_contribution, take_due_contribution
from ops.calendar import is_market_session
from ops.commit import approve_draft, cancel_draft
from ops.halt import clear_halt
from ops.health import health_report
from ops.limits import near_limit_flags
from ops.live_rules import live_rules
from ops.purify_ledger import export_purification, post_ledger, upsert_entries
from ops.ruleset import confirm, propose, rules_for_run
from ops.schedule import run_schedule
from ops.session import run_session
from ops.tests.test_pipeline import _lab, _run
from ops.venues import run_alpaca_day


def test_deposit_needs_confirm_above_ten_percent_and_halt_blocks_it(tmp_path):
    from ops.cash import move_cash

    root = tmp_path / "state"
    account = PaperAccount(cash=1_000_000)
    with pytest.raises(ValueError, match="10%"):
        move_cash(account, 200_000, "deposit", actor="ada", reason="top up", root=root, nav=1_000_000)
    record = move_cash(
        account,
        200_000,
        "deposit",
        actor="ada",
        reason="top up",
        root=root,
        nav=1_000_000,
        confirm=True,
    )
    assert record["cash_after"] == 1_200_000
    assert read_events(root, event_type="cash_deposit")
    account.halted = True
    with pytest.raises(ValueError, match="halted"):
        move_cash(account, 10, "deposit", actor="ada", reason="no", root=root, nav=1_000_000)


def test_contribution_applies_once_per_month(tmp_path):
    root = tmp_path / "state"
    set_contribution(enabled=True, amount=500, next_date=date(2026, 9, 1), actor="ada", root=root)
    account = PaperAccount(cash=1_000)
    first = take_due_contribution(account, date(2026, 9, 28), root)
    assert first["amount"] == 500
    assert account.cash == 1_500
    assert take_due_contribution(account, date(2026, 9, 29), root) is None
    assert account.cash == 1_500


def test_halt_clear_requires_a_reason_and_is_audited(tmp_path):
    root = tmp_path / "state"
    account = PaperAccount(halted=True, halt_reason="weight gap")
    with pytest.raises(ValueError, match="reason"):
        clear_halt(account, actor="ada", reason="  ", root=root)
    cleared = clear_halt(account, actor="ada", reason="prices backfilled", root=root)
    assert cleared.halted is False
    assert read_events(root, event_type="halt_cleared")[0]["prior_reason"] == "weight gap"


def test_purification_post_is_once(tmp_path):
    root = tmp_path / "state"
    account = PaperAccount(cash=1_000, purification_payable=10, staged_purify_keys=["AAA|2024-06-03"])
    upsert_entries(
        [
            {
                "key": "AAA|2024-06-03",
                "symbol": "AAA",
                "ex_date": "2024-06-03",
                "shares": 100,
                "gross_dividend": 1.0,
                "impure_ratio": 0.1,
                "amount": 10,
                "status": "accrued",
                "actor": "",
            }
        ],
        root,
    )
    assert post_ledger(account, actor="ada", root=root) == 10
    assert account.cash == 990
    with pytest.raises(ValueError, match="already posted"):
        post_ledger(account, actor="ada", root=root, keys=["AAA|2024-06-03"])
    exported = export_purification(root, tmp_path / "out.csv")
    text = exported.read_text(encoding="utf-8")
    assert text.startswith("# paper ledger amounts, not a charity wire")


def test_rules_bump_waits_for_confirm_and_rejects_other_sleeves(tmp_path):
    root = tmp_path / "state"
    with pytest.raises(ValueError, match="roic"):
        propose({"roic": 1}, actor="ada", reason="no", root=root)
    proposal = propose({"name_cap": 0.08}, actor="ada", reason="tighter cap", root=root)
    assert live_rules().book.name_cap == 0.10
    assert rules_for_run(root)[0].book.name_cap == 0.10
    confirm(proposal["id"], actor="ada", root=root)
    assert live_rules().book.name_cap == 0.10
    assert rules_for_run(root)[0].book.name_cap == 0.08
    events = read_events(root, event_type="rules_version_bumped")
    assert events[0]["recorded_not_legal_signoff"] is True


def test_near_limit_does_not_flag_a_name_on_the_line():
    flags = near_limit_flags(
        pd.DataFrame(
            [
                {"symbol": "AAA", "debt_ratio": 0.29, "cash_ratio": 0.10, "receivables_ratio": 0.20},
                {"symbol": "BBB", "debt_ratio": 0.30, "cash_ratio": 0.10, "receivables_ratio": 0.20},
            ]
        )
    )
    assert list(flags["symbol"]) == ["AAA"]


def test_health_stays_blank_until_the_series_is_long_enough():
    nav = pd.DataFrame({"as_of": pd.bdate_range("2026-01-01", periods=5), "nav": [100, 101, 99, 102, 100]})
    report = health_report(nav)
    assert report["n_sessions"] == 5
    assert report["sharpe"] is None
    assert report["max_drawdown"] is not None
    assert report["sessions_required"] == 20


def test_schedule_skips_the_weekend_and_a_holiday(tmp_path):
    calls = []
    weekend = run_schedule(date(2026, 9, 26), root=tmp_path, runner=lambda day: calls.append(day))
    holiday = run_schedule(date(2026, 9, 7), root=tmp_path, runner=lambda day: calls.append(day))
    assert weekend["reason"] == "weekend"
    assert holiday["reason"] == "market holiday"
    assert calls == []
    assert is_market_session(date(2026, 9, 28)) is True
    dry = run_schedule(date(2026, 9, 28), root=tmp_path, dry_run=True, runner=lambda day: calls.append(day))
    assert dry["status"] == "dry_run"
    assert calls == []


def test_alpaca_refuses_the_live_host_and_does_not_resubmit():
    with pytest.raises(AlpacaError, match="paper-api"):
        AlpacaClient("key", "secret", "https://api.alpaca.markets")
    store = {}

    def transport(method, url, headers, body):
        if "by_client_order_id" in url:
            cid = url.split("client_order_id=")[-1]
            if cid in store:
                return 200, store[cid]
            return 404, None
        store[body["client_order_id"]] = {**body, "id": "broker-1", "status": "accepted"}
        return 200, store[body["client_order_id"]]

    client = AlpacaClient("key", "secret", transport=transport)
    orders = [{"symbol": "AAA", "side": "buy", "shares": 3, "status": "pending"}]
    day = date(2026, 9, 28)
    first = submit_orders(client, orders, as_of=day)
    second = submit_orders(client, orders, as_of=day)
    assert first[0]["duplicate"] is False
    assert second[0]["duplicate"] is True
    assert store[first[0]["client_order_id"]]["time_in_force"] == "opg"


def test_draft_is_not_a_fill_until_approved(tmp_path):
    lab, as_of, _ = _lab(80, 120)
    root = tmp_path
    result = run_session(
        as_of,
        lab=lab,
        refresh=False,
        breaches=False,
        trade=True,
        commit=False,
        runs_root=root / "runs",
        state_root=root / "state",
    )
    assert result.extra["fill_basis"] == "draft"
    assert result.extra["n_fills"] == 0
    assert load_account(root / "state").positions == {}
    cancel_draft(as_of, actor="ada", root=root / "state")
    assert load_account(root / "state").pending == []
    with pytest.raises(ValueError, match="no draft"):
        approve_draft(as_of, actor="ada", root=root / "state")


def test_bootstrap_batch_completes(tmp_path):
    lab, as_of, _ = _lab(80, 120)
    result = _run(lab, as_of, tmp_path)
    assert result.extra["batch_status"] == "completed"
    batches = load_batches(tmp_path / "state")
    assert batches[-1]["status"] == "completed"
    assert read_events(tmp_path / "state", event_type="order_batch_approved")


class _FakeAlpaca:
    def __init__(self):
        self.cash = 1_000_000.0
        self.positions = {}
        self.orders = {}
        self.open = []

    def get_account(self):
        return {"cash": self.cash}

    def get_positions(self):
        return [{"symbol": symbol, "qty": qty} for symbol, qty in self.positions.items()]

    def list_open_orders(self):
        return list(self.open)

    def get_by_client_id(self, client_id):
        return self.orders.get(client_id)

    def submit_order(self, payload):
        row = {**payload, "id": payload["client_order_id"], "status": "accepted", "qty": payload["qty"]}
        self.orders[payload["client_order_id"]] = row
        self.open.append(row)
        return row


def test_alpaca_submits_then_syncs_fills(tmp_path):
    lab, first_day, next_day = _lab(80, 120)
    broker = _FakeAlpaca()
    root = tmp_path
    kwargs = dict(
        lab=lab,
        refresh=False,
        breaches=False,
        venue="alpaca",
        broker=broker,
        runs_root=root / "runs",
        state_root=root / "state",
    )
    first = run_session(first_day, **kwargs)
    assert first.extra["fill_basis"] == "submitted_opg"
    assert load_account(root / "state").venue == "alpaca"
    assert broker.open
    for order in list(broker.open):
        qty = int(order["qty"])
        broker.positions[order["symbol"]] = qty
        broker.cash -= qty * 10
    broker.open.clear()
    second = run_session(next_day, **kwargs)
    assert second.extra["halted"] is False
    assert load_account(root / "state").positions
    held = PaperAccount(positions={"AAA": 1}, fills=[{"status": "filled"}])
    with pytest.raises(ValueError, match="local venue"):
        run_alpaca_day(first.book, held, lab.prices, broker)
