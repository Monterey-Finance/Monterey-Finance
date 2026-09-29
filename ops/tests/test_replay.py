"""Replay walks sessions in order without reloading the market history."""

from __future__ import annotations

from datetime import date

import pandas as pd

from ops.replay import replay_range
from ops.targets import build_intended_book
from ops.tests.test_pipeline import _lab


def test_replay_skips_weekends_holidays_and_marked_days(monkeypatch):
    calls = []

    monkeypatch.setattr("ops.replay.load_lab", lambda *args, **kwargs: object())
    monkeypatch.setattr("ops.replay.already_marked", lambda day, root=None: day == date(2020, 1, 3))

    def _run(day, **kwargs):
        calls.append(day)
        assert kwargs["lab"] is not None
        assert kwargs["selection_cache"] is not None

    monkeypatch.setattr("ops.replay.run_session", _run)

    result = replay_range(date(2020, 1, 1), date(2020, 1, 6), breaches=False)

    assert calls == [date(2020, 1, 2), date(2020, 1, 6)]
    assert result.sessions == 2
    assert result.complete is True


def test_replay_stops_at_the_time_budget(monkeypatch):
    calls = []
    monkeypatch.setattr("ops.replay.load_lab", lambda *args, **kwargs: object())
    monkeypatch.setattr("ops.replay.already_marked", lambda day, root=None: False)
    monkeypatch.setattr("ops.replay.run_session", lambda day, **kwargs: calls.append(day))

    result = replay_range(date(2020, 1, 6), date(2020, 1, 8), budget_s=0, breaches=False)

    assert calls == [date(2020, 1, 6)]
    assert result.complete is False
    assert result.reached == date(2020, 1, 6)


def test_month_list_is_reused_and_matches_a_fresh_book():
    lab, as_of, _ = _lab(80, 120)
    later = pd.to_datetime(lab.prices["date"]).max().date()
    fresh = build_intended_book(lab, as_of)
    cache: dict = {}
    first = build_intended_book(lab, as_of, selection_cache=cache)
    second = build_intended_book(lab, later, selection_cache=cache)

    assert list(first.holdings["symbol"]) == list(fresh.holdings["symbol"])
    assert list(first.holdings["target_weight"]) == list(fresh.holdings["target_weight"])
    assert len(cache) == 1
    assert list(second.invested["symbol"]) == list(first.invested["symbol"])
