"""The desk loads a monterey ledger and fills every tab."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from desk.app import DeskApp
from desk.model import load_desk
from monterey.diagnostics import diagnose
from monterey.sim import simulate
from monterey.spec import BookSpec
from monterey.tests.synthetic import make_data

ROOT = Path(__file__).resolve().parents[2]


def _ledger(tmp_path):
    data = make_data(crash_on=None, breach=None)
    spec = BookSpec.load("fcf-sma-v2-baseline").replace(
        id="desk-test",
        signal={"params": {"min_holdings": 1, "keep_quantile": 1.0}},
    )
    ledger = simulate(spec, data, "2020-01-02", "2020-03-31", root=tmp_path)
    diagnose(ledger, data)
    return ledger, data


def test_desk_loads_a_simulated_ledger(tmp_path):
    ledger, _ = _ledger(tmp_path)
    desk = load_desk(ledger=ledger.path)
    assert desk.nav is not None
    assert desk.nav > 0
    assert desk.holdings
    assert desk.health.get("max_drawdown") is not None
    assert desk.rules
    assert any(label == "brain" for label, _ in desk.rules)
    assert desk.sessions
    apple = desk.holding(desk.holdings[0].symbol)
    assert apple is not None
    assert apple.price is not None


def test_every_tab_is_filled(tmp_path):
    ledger, _ = _ledger(tmp_path)
    desk = load_desk(ledger=ledger.path)
    asyncio.run(_walk_tabs(desk))


async def _walk_tabs(desk):
    app = DeskApp(desk=desk)
    async with app.run_test(size=(160, 46)) as pilot:
        await pilot.pause()
        book = app.query_one("#book-table")
        assert book.row_count >= 1
        await pilot.press("2")
        await pilot.pause()
        assert app.query_one("#weights-table").row_count >= 1
        await pilot.press("3")
        await pilot.pause()
        await pilot.press("4")
        await pilot.pause()
        await pilot.press("5")
        await pilot.pause()
        assert app.query_one("#health-table").row_count >= 8
        assert app.query_one("#rules-table").row_count >= 8
        await pilot.press("6")
        await pilot.pause()
        await pilot.press("7")
        await pilot.pause()
        await pilot.press("1")
        await pilot.pause()
        app.query_one("#find").value = desk.holdings[0].symbol
        await pilot.pause()
        assert app.query_one("#book-table").row_count >= 1
        app.save_screenshot(str(ROOT / "desk" / "tests" / "desk-book.svg"))
