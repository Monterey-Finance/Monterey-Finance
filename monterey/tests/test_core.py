"""Offline tests for the spec, layers, simulator, ledger, and diagnostics."""

from __future__ import annotations

import pandas as pd
import pytest

from monterey import BookSpec
from monterey.diagnostics import diagnose
from monterey.layers.construction import apply_sector_cap
from monterey.ledger import Ledger, list_ledgers
from monterey.sim import SimState, Simulator, simulate
from monterey.tests.synthetic import make_data


def _spec(**sections) -> BookSpec:
    base = BookSpec.load("fcf-sma-v2-baseline").replace(id="test-book", signal={"params": {"min_holdings": 1, "keep_quantile": 1.0}})
    return base.replace(**sections) if sections else base


def test_spec_hash_tracks_rules_not_labels() -> None:
    a = _spec()
    assert a.replace(label="renamed").hash() == a.hash()
    assert a.replace(overlay={"confirm_days": 2}).hash() != a.hash()
    with pytest.raises(ValueError):
        a.replace(overlay={"confrim_days": 2})


def test_spec_round_trips_through_yaml(tmp_path) -> None:
    a = _spec(construction={"sector_cap": 0.4})
    path = a.save(tmp_path / "book.yaml")
    assert BookSpec.load(path).hash() == a.hash()


def test_halal_list_applies_sector_and_membership() -> None:
    data = make_data()
    early = data.halal("2020-03-31").set_index("symbol")
    assert "CCC" not in early.index  # joins the index on 2020-06-01
    assert not early.loc["BANK", "is_compliant"]
    assert early.loc["BANK", "reason"] == "excluded activity: conventional banking"
    late = data.halal("2020-07-31").set_index("symbol")
    assert late.loc["CCC", "is_compliant"]
    loose = data.halal("2020-03-31", pit=False, sectors=False).set_index("symbol")
    assert "CCC" in loose.index and loose.loc["BANK", "is_compliant"]


def test_first_session_fills_at_close_then_next_open() -> None:
    data = make_data(crash_on=None, breach=None)
    ledger = simulate(_spec(), data, "2020-01-02", "2020-01-10")
    fills = ledger.fills
    first = fills[fills["date"] == pd.Timestamp("2020-01-02")]
    assert set(first["price_field"]) == {"close"}
    later = fills[fills["date"] > pd.Timestamp("2020-01-02")]
    assert later.empty or set(later["price_field"]) == {"open"}
    assert ledger.nav["nav"].iloc[0] == pytest.approx(1_000_000, rel=0.002)


def test_switch_off_day_is_still_invested_and_cash_follows() -> None:
    data = make_data(breach=None)
    ledger = simulate(_spec(), data, "2020-01-02", "2020-04-30")
    nav = ledger.nav.set_index("date")
    crash = pd.Timestamp("2020-03-02")
    assert nav.loc[crash, "exposure"] == 0.0
    assert nav.loc[crash, "daily_return"] < -0.15  # the close that flips the switch is not avoided
    after = nav.loc[pd.Timestamp("2020-03-04")]
    assert after["cash"] / after["nav"] > 0.99


def test_dividends_are_credited_and_purified() -> None:
    data = make_data(crash_on=None, breach=None)
    ledger = simulate(_spec(), data, "2020-01-02", "2020-02-28")
    flows = ledger.cashflows
    div = flows[flows["type"] == "dividend"]
    pur = flows[flows["type"] == "purification"]
    assert len(div) == 1 and div["amount"].iloc[0] > 0
    assert pur["amount"].iloc[0] == pytest.approx(-0.02 * div["amount"].iloc[0])
    v1 = simulate(_spec(accounting={"dividends": False, "purify_uncredited": True}), data, "2020-01-02", "2020-02-28")
    assert (v1.cashflows["type"] == "dividend").sum() == 0
    assert (v1.cashflows["type"] == "purification").sum() == 1


def test_costs_are_charged_on_every_fill() -> None:
    data = make_data(crash_on=None, breach=None)
    paid = simulate(_spec(), data, "2020-01-02", "2020-03-31")
    free = simulate(_spec(accounting={"cost_bps": 0.0}), data, "2020-01-02", "2020-03-31")
    good = paid.fills[paid.fills["status"].isin(["filled", "partial"])]
    assert good["cost"].sum() == pytest.approx((good["notional"] * 10 / 10_000).sum())
    assert paid.nav["nav"].iloc[-1] < free.nav["nav"].iloc[-1]


def test_filing_breach_sells_at_the_next_open_until_the_next_snapshot() -> None:
    data = make_data(crash_on=None)
    ledger = simulate(_spec(), data, "2020-01-02", "2020-06-30")
    pos = ledger.positions
    held = lambda day: pos[(pos["date"] == pd.Timestamp(day)) & (pos["symbol"] == "BBB")]["shares"].sum()  # noqa: E731
    assert held("2020-04-14") > 0
    assert held("2020-04-16") == 0  # breach filed 04-15, sold at the 04-16 open
    assert held("2020-05-05") > 0  # the 04-30 snapshot passes again, so it is bought back
    report = simulate(_spec(screen={"breach_exit": "report_only"}), data, "2020-01-02", "2020-04-30")
    still = report.positions
    assert still[(still["date"] == pd.Timestamp("2020-04-20")) & (still["symbol"] == "BBB")]["shares"].sum() > 0


def test_point_in_time_name_is_not_held_before_it_joins() -> None:
    data = make_data(crash_on=None, breach=None)
    ledger = simulate(_spec(), data, "2020-01-02", "2020-07-31")
    ccc = ledger.positions[ledger.positions["symbol"] == "CCC"]
    first = ccc[ccc["shares"] > 0]["date"].min()
    assert first >= pd.Timestamp("2020-06-01")
    assert (ledger.positions[ledger.positions["symbol"] == "BANK"]["shares"] == 0).all()


def test_delisted_name_is_cashed_at_last_close() -> None:
    data = make_data(crash_on=None, breach=None, delist=("AAA", "2020-03-02"))
    ledger = simulate(_spec(), data, "2020-01-02", "2020-03-31")
    events = ledger.events
    assert ((events["type"] == "delisted") & (events["symbol"] == "AAA")).any()
    assert ledger.nav["nav"].min() > 900_000


def test_state_round_trip_continues_the_same_path() -> None:
    data = make_data(breach=None)
    spec = _spec()
    whole = simulate(spec, data, "2020-01-02", "2020-05-29")
    first = Simulator(spec, data)
    for day in data.sessions_between("2020-01-02", "2020-03-31"):
        first.step(day)
    resumed = Simulator(spec, data, state=SimState.from_dict(first.state.to_dict()))
    for day in data.sessions_between("2020-04-01", "2020-05-29"):
        resumed.step(day)
    assert resumed.state.last_nav == pytest.approx(whole.nav["nav"].iloc[-1], rel=1e-9)


def test_sector_cap_holds() -> None:
    w = pd.Series({"A": 0.4, "B": 0.3, "C": 0.2, "D": 0.1})
    sectors = {"A": "tech", "B": "tech", "C": "health", "D": "energy"}
    capped = apply_sector_cap(w, sectors, 0.5)
    assert capped[["A", "B"]].sum() == pytest.approx(0.5, abs=1e-6)
    assert capped.sum() == pytest.approx(1.0)


def test_snapshot_round_trip(tmp_path) -> None:
    from monterey.data import load_snapshot, save_snapshot

    data = make_data()
    folder = save_snapshot(data, tmp_path / "snap")
    loaded = load_snapshot(folder)
    assert not bool(loaded.halal("2020-03-31").set_index("symbol").loc["BANK", "is_compliant"])
    assert "CCC" not in loaded.members("2020-03-31")
    assert "CCC" in loaded.members("2020-07-01")
    assert not loaded.benchmarks().empty
    assert loaded.universe("2020-03-31")["sector_allowed"].notna().all()


def test_ledger_writes_reads_and_diagnoses(tmp_path) -> None:
    data = make_data()
    ledger = simulate(_spec(), data, "2020-01-02", "2020-12-31", root=tmp_path)
    loaded = Ledger.read(ledger.path)
    assert loaded.spec.hash() == ledger.spec.hash()
    assert len(loaded.nav) == len(ledger.nav)
    diag = diagnose(loaded, data)
    assert (ledger.path / "diagnostics.json").exists()
    assert diag["benchmarks"]["SPUS"]["switch"]["cuts"] >= 1
    assert diag["compliance"]["excluded_exposure"]["sessions"] == 0
    assert list_ledgers(tmp_path)[0]["book"] == "test-book"
