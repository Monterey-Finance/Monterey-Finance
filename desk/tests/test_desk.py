"""The desk loads the paper book and fills every tab."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from desk.app import DeskApp
from desk.model import load_desk

ROOT = Path(__file__).resolve().parents[2]


def test_live_book_loads_the_september_session():
    desk = load_desk()
    assert desk.as_of == "2026-09-25"
    assert desk.nav == pytest.approx(1_000_000, abs=1)
    assert len(desk.holdings) >= 100
    apple = desk.holding("AAPL")
    assert apple is not None
    assert apple.target_weight == pytest.approx(0.10, abs=1e-6)
    assert apple.shares == 293
    assert apple.screen == "PASS"
    assert apple.name_capped is True
    assert desk.cash_path[-1]["cash"] == pytest.approx(desk.cash, abs=0.01)


def test_every_tab_is_filled():
    asyncio.run(_walk_tabs())


async def _walk_tabs():
    app = DeskApp()
    async with app.run_test(size=(160, 46)) as pilot:
        await pilot.pause()
        book = app.query_one("#book-table")
        assert book.row_count >= 100
        assert book.size.height > 12
        assert app.query_one("#facts").row_count >= 10
        assert app.query_one("#bars").row_count >= 100
        await pilot.press("2")
        await pilot.pause()
        assert app.query_one("#weights-table").row_count >= 100
        await pilot.press("3")
        await pilot.pause()
        assert app.query_one("#orders-table").row_count >= 100
        assert app.query_one("#fills-table").row_count >= 100
        await pilot.press("4")
        await pilot.pause()
        assert app.query_one("#activity-table").row_count >= 100
        assert app.query_one("#ratio-table").row_count >= 100
        assert app.query_one("#cash-table").row_count >= 100
        await pilot.press("5")
        await pilot.pause()
        assert app.query_one("#health-table").row_count >= 8
        assert app.query_one("#status-table").row_count >= 8
        assert app.query_one("#rules-table").row_count >= 8
        assert app.query_one("#limits-table").row_count >= 100
        await pilot.press("1")
        await pilot.pause()
        app.query_one("#find").value = "AAPL"
        await pilot.pause()
        assert app.query_one("#book-table").row_count == 1
        app.save_screenshot(str(ROOT / "desk" / "tests" / "desk-book.svg"))
