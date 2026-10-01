"""A small, fully known ResearchData for offline tests."""

from __future__ import annotations

import numpy as np
import pandas as pd

from monterey.data import Panels, ResearchData


def make_data(
    *,
    crash_on: str | None = "2020-03-02",
    breach: tuple[str, str] | None = ("BBB", "2020-04-15"),
    delist: tuple[str, str] | None = None,
) -> ResearchData:
    days = pd.bdate_range("2019-01-01", "2020-12-31")
    n = len(days)
    rng = np.arange(n)
    spy = 100 * (1.0006 ** rng)
    if crash_on:
        hit = days.get_indexer([pd.Timestamp(crash_on)], method="bfill")[0]
        spy[hit:] = spy[hit:] * 0.75  # one-day 25% gap down: switch turns off at that close
        recover = hit + 120
        spy[recover:] = spy[recover:] * 1.5
    closes = {
        "SPY": spy,
        "SPUS": spy * 1.1,
        "AAA": 50 * (1.0008 ** rng),
        "BBB": 40 * (1.0004 ** rng),
        "CCC": 30 * (1.0010 ** rng),
        "BANK": 20 * (1.0005 ** rng),
    }
    if crash_on:
        for symbol in ("AAA", "BBB", "CCC", "BANK"):
            closes[symbol][hit:] = closes[symbol][hit:] * 0.8
    rows = []
    for symbol, path in closes.items():
        for i, day in enumerate(days):
            px = float(path[i])
            if delist and symbol == delist[0] and day >= pd.Timestamp(delist[1]):
                continue
            rows.append({"symbol": symbol, "date": day, "open": px * 0.999, "close": px, "adj_close": px, "volume": 1e6})
    prices = pd.DataFrame(rows)

    stamps = pd.date_range("2019-01-31", "2020-12-31", freq="ME")
    metric_rows = []
    caps = {"AAA": 3e11, "BBB": 1e11, "CCC": 2e11, "BANK": 1.5e11}
    for stamp in stamps:
        for symbol, cap in caps.items():
            metric_rows.append(
                {
                    "symbol": symbol,
                    "as_of": stamp,
                    "freq": "ME",
                    "report_date": stamp - pd.Timedelta(days=30),
                    "filed_date": stamp - pd.Timedelta(days=5),
                    "total_debt": 0.05 * cap,
                    "cash_and_equiv": 0.05 * cap,
                    "interest_bearing_securities": 0.0,
                    "receivables": 0.05 * cap,
                    "liquid_assets": 0.0,
                    "market_cap": cap,
                    "market_cap_24m": cap,
                    "total_revenue": 1e10,
                    "free_cash_flow": 3e9 if symbol != "BBB" else 1e9,
                    "fcf": 3e9 if symbol != "BBB" else 1e9,
                    "ebitda": 4e9,
                    "impure_ratio": 0.02,
                }
            )
    metrics = pd.DataFrame(metric_rows)
    stints = pd.DataFrame(
        [
            {"universe": "sp500", "symbol": "AAA", "start_date": pd.Timestamp("2010-01-01"), "end_date": pd.NaT},
            {"universe": "sp500", "symbol": "BBB", "start_date": pd.Timestamp("2010-01-01"), "end_date": pd.NaT},
            {"universe": "sp500", "symbol": "BANK", "start_date": pd.Timestamp("2010-01-01"), "end_date": pd.NaT},
            {"universe": "sp500", "symbol": "CCC", "start_date": pd.Timestamp("2020-06-01"), "end_date": pd.NaT},
        ]
    )
    dividends = pd.DataFrame([{"symbol": "AAA", "ex_date": pd.Timestamp("2020-02-14"), "dividend": 1.0}])
    events = pd.DataFrame(columns=["symbol", "filed_date", "is_compliant", "reason"])
    if breach:
        events = pd.DataFrame([{"symbol": breach[0], "filed_date": pd.Timestamp(breach[1]), "is_compliant": False, "reason": "debt ratio exceeds threshold"}])
    data = ResearchData(
        start=pd.Timestamp("2020-01-02").date(),
        end=pd.Timestamp("2020-12-31").date(),
        index="sp500",
        stints=stints,
        current=["AAA", "BBB", "BANK", "CCC"],
        sectors={"AAA": "information technology", "BBB": "health care", "CCC": "information technology", "BANK": "conventional banking"},
        metrics=metrics,
        prices=Panels.from_long(prices),
        dividends=dividends,
        filing_events=events,
        manifest={"hash": "synthetic"},
    )
    return data
