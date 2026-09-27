"""Quote fallback when the session close is blank."""

from datetime import date, timedelta

import pandas as pd

from ops.quotes import session_quotes


def test_blank_session_close_uses_the_prior_print():
    start = date(2026, 9, 16)
    rows = []
    for offset, close in enumerate([774.0, 789.0, None, None]):
        day = start + timedelta(days=offset)
        rows.append({"symbol": "REGN", "date": day, "close": close, "open": close})
    quotes = session_quotes(pd.DataFrame(rows), date(2026, 9, 19), "close", lookback_days=10)
    assert quotes["REGN"] == 789.0
