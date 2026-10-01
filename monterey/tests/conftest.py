"""A tiny synthetic market so the simulator can be tested offline."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from monterey.data import Panels, ResearchData


def make_data(seed: int = 7) -> ResearchData:
    days = pd.bdate_range("2019-01-01", "2021-06-30")
    rng = np.random.default_rng(seed)
    rows = []

    def path(start: float, drift: float, vol: float) -> np.ndarray:
        steps = rng.normal(drift, vol, len(days))
        return start * np.exp(np.cumsum(steps))

    spy = np.concatenate(
        [
            np.linspace(100, 160, 330),
            np.linspace(160, 110, 120),
            np.linspace(110, 170, len(days) - 450),
        ]
    )
    prices = {
        "SPY": spy,
        "SPUS": spy * 0.4,
        "AAA": path(50, 0.0006, 0.01),
        "BBB": path(80, 0.0004, 0.012),
        "CCC": path(30, 0.0008, 0.015),
        "BANK": path(40, 0.0003, 0.01),
    }
    for symbol, series in prices.items():
        for day, px in zip(days, series):
            rows.append({"symbol": symbol, "date": day, "open": px * 0.999, "close": px, "adj_close": px, "volume": 1e6})
    long = pd.DataFrame(rows)
    # CCC has no prints after 2021-05-14 (acquired).
    long = long[~((long["symbol"] == "CCC") & (long["date"] > "2021-05-14"))]

    stamps = pd.date_range("2019-01-31", "2021-06-30", freq="ME")
    metrics = []
    for stamp in stamps:
        for symbol, cap, fcf, revenue, debt in (
            ("AAA", 500.0, 40.0, 100.0, 10.0),
            ("BBB", 300.0, 20.0, 100.0, 10.0),
            ("CCC", 200.0, 30.0, 100.0, 10.0),
            ("BANK", 400.0, 50.0, 100.0, 10.0),
        ):
            metrics.append(
                {
                    "symbol": symbol,
                    "as_of": stamp,
                    "freq": "ME",
                    "report_date": stamp - pd.Timedelta(days=40),
                    "filed_date": stamp - pd.Timedelta(days=10),
                    "total_debt": debt,
                    "cash_and_equiv": 5.0,
                    "interest_bearing_securities": 0.0,
                    "receivables": 5.0,
                    "liquid_assets": 0.0,
                    "market_cap": cap,
                    "market_cap_24m": cap,
                    "total_revenue": revenue,
                    "free_cash_flow": fcf,
                    "fcf": fcf,
                    "ebitda": fcf * 1.5,
                    "impure_ratio": 0.10 if symbol == "AAA" else 0.0,
                }
            )
    stints = pd.DataFrame(
        [
            {"universe": "sp500", "symbol": "AAA", "start_date": "1990-01-01", "end_date": None},
            {"universe": "sp500", "symbol": "BBB", "start_date": "1990-01-01", "end_date": None},
            {"universe": "sp500", "symbol": "CCC", "start_date": "2020-06-01", "end_date": None},
            {"universe": "sp500", "symbol": "BANK", "start_date": "1990-01-01", "end_date": None},
        ]
    )
    dividends = pd.DataFrame([{"symbol": "AAA", "ex_date": pd.Timestamp("2020-03-02"), "dividend": 1.0}])
    events = pd.DataFrame(
        [
            {
                "symbol": "BBB",
                "filed_date": pd.Timestamp("2020-02-12"),
                "is_compliant": False,
                "reason": "debt ratio exceeds threshold",
            }
        ]
    )
    data = ResearchData(
        start=pd.Timestamp("2020-01-02").date(),
        end=pd.Timestamp("2021-06-30").date(),
        index="sp500",
        stints=stints,
        current=["AAA", "BBB", "CCC", "BANK"],
        sectors={"AAA": "information technology", "BBB": "industrials", "CCC": "health care", "BANK": "conventional banking"},
        metrics=pd.DataFrame(metrics),
        prices=Panels.from_long(long),
        dividends=dividends,
        filing_events=events,
        manifest={"hash": "synthetic"},
    )
    return data


@pytest.fixture(scope="session")
def data() -> ResearchData:
    return make_data()
