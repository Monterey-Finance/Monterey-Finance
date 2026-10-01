"""Parity against the frozen v1 paper NAV, and the v2 baseline run."""

from __future__ import annotations

import pandas as pd
import pytest

from monterey.data import cache_ready, load_research_data
from monterey.paths import ROOT
from monterey.sim import simulate
from monterey.spec import BookSpec

NAV_CSV = ROOT / "ops" / "state" / "nav.csv"
WINDOW = ("2020-01-02", "2026-09-30")


def _month_ends(nav: pd.Series) -> pd.Series:
    frame = nav.copy()
    frame.index = pd.to_datetime(frame.index)
    return frame.groupby(frame.index.to_period("M")).last()


@pytest.mark.skipif(not cache_ready() or not NAV_CSV.exists(), reason="needs the prepared cache and the v1 NAV ledger")
def test_v1_parity_month_end_nav():
    """
    The v1 spec must replay the paper path.

    Overlay timing is exact (SMA on/off matches every overlapping session).
    Month-end NAV is inside 1.5% — the frozen ops Lab had 91 names on day one
    against 87 here because some 2019 metric rows have since dropped out of
    the cache. Tighten the month-end band to 0.25% when that Lab snapshot is
    archived next to the v1 ledger.
    """
    spec = BookSpec.load("fcf-sma-v1")
    data = load_research_data(*WINDOW, progress=False)
    ledger = simulate(spec, data, *WINDOW, progress=False)
    live = pd.read_csv(NAV_CSV, parse_dates=["as_of"]).set_index("as_of")
    live.index = pd.to_datetime(live.index)
    sim_nav = ledger.nav_series()
    sim_on = ledger.nav.set_index("date")["regime_on"]
    sim_on.index = pd.to_datetime(sim_on.index)
    days = live.index.intersection(sim_nav.index)
    assert len(days) >= 1600
    assert (live.loc[days, "sma_on"].astype(bool).values == sim_on.loc[days].astype(bool).values).all()
    live_nav = live.loc[days, "nav"].astype(float)
    sim_nav = sim_nav.loc[days].astype(float)
    rel = (_month_ends(sim_nav) / _month_ends(live_nav) - 1.0).abs()
    worst = float(rel.max())
    assert worst <= 0.015, f"worst month-end gap {worst:.4%} on {rel.idxmax()}"
