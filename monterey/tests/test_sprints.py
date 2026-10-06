"""October sprints run against a synthetic book without the market cache."""

from __future__ import annotations

import pandas as pd

from monterey.research import compare, run_book
from monterey.sprints import survivorship_in_book, universe_survivorship, write_notebooks
from monterey.tests.synthetic import make_data


def test_write_notebooks(tmp_path):
    paths = write_notebooks(tmp_path)
    assert len(paths) == 5
    for path in paths:
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        assert "from monterey.research import boot" in text
        assert "run_sprint" in text


def test_paper_17_survivorship_variant(tmp_path, monkeypatch):
    monkeypatch.setattr("monterey.research.LEDGERS", tmp_path)
    data = make_data(crash_on=None, breach=None)
    baseline = run_book(
        "fcf-sma-v2-baseline",
        data,
        paper="17-pit-universe",
        id="v2-baseline",
        start="2020-01-02",
        end="2020-07-31",
        signal={"params": {"min_holdings": 1, "keep_quantile": 1.0}},
    )
    current = run_book(
        "fcf-sma-v2-baseline",
        data,
        paper="17-pit-universe",
        id="current-list",
        start="2020-01-02",
        end="2020-07-31",
        universe={"pit": False},
        signal={"params": {"min_holdings": 1, "keep_quantile": 1.0}},
    )
    table = compare([baseline, current], data=data)
    assert "v2-baseline" in table.index
    assert "current-list" in table.index
    ccc_pit = baseline.positions[(baseline.positions["symbol"] == "CCC") & (baseline.positions["shares"] > 0)]
    ccc_now = current.positions[(current.positions["symbol"] == "CCC") & (current.positions["shares"] > 0)]
    assert ccc_pit["date"].min() >= pd.Timestamp("2020-06-01")
    assert not ccc_now.empty
    census = universe_survivorship(data, "2020-01-02", "2020-07-31")
    before = census[census["date"] < pd.Timestamp("2020-06-01")]
    after = census[census["date"] >= pd.Timestamp("2020-06-01")]
    assert not before.empty and (before["joiners"] >= 1).all()
    assert not after.empty and (after["joiners"] == 0).all()
    ghosts = survivorship_in_book(current, data)
    joiners = ghosts[ghosts["kind"] == "joiner"] if not ghosts.empty else ghosts
    assert not joiners.empty
    assert "CCC" in set(joiners["symbol"])
