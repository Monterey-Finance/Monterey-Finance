"""October sprint notebooks: one spec family each, scored against v2 baseline."""

from __future__ import annotations

from ops.fund import archive_v1_ledger
from ops.live_rules import live_spec
import pandas as pd


def test_archive_v1_writes_a_monterey_ledger(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    pd.DataFrame(
        {
            "as_of": ["2020-01-02", "2020-01-03"],
            "nav": [1_000_000.0, 1_001_000.0],
            "cash": [50_000.0, 49_000.0],
            "invested": [950_000.0, 952_000.0],
            "daily_return": [0.0, 0.001],
            "n_positions": [20, 20],
            "sma_on": [True, True],
            "purification_today": [0.0, 12.0],
        }
    ).to_csv(state / "nav.csv", index=False)
    dest = tmp_path / "ledgers" / "fcf-sma-v1" / "archive"
    path = archive_v1_ledger(state_root=state, dest=dest)
    assert (path / "spec.yaml").exists()
    assert (path / "nav.parquet").exists()
    nav = pd.read_parquet(path / "nav.parquet")
    assert len(nav) == 2
    assert float(nav["nav"].iloc[-1]) == 1_001_000.0


def test_live_spec_is_the_v2_baseline():
    spec = live_spec()
    assert spec.id == "fcf-sma-v2-baseline"
    assert spec.universe["pit"] is True
    assert spec.screen["sectors"] is True
    assert spec.accounting["dividends"] is True
    assert spec.accounting["cost_bps"] == 10.0
    assert spec.hash()
