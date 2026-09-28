"""Load a Lab from the local halalquant cache."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Sequence

import pandas as pd

from ops.live_rules import live_rules
from ops.paths import ensure_research_on_path

ensure_research_on_path()

from sleeves.lab import Lab  # noqa: E402


def resolve_as_of(as_of: str | date | None) -> date:
    if as_of is None or str(as_of).strip().lower() in {"", "today"}:
        return date.today()
    return pd.Timestamp(as_of).date()


def lookback_start(as_of: date, lookback_days: int = 550) -> date:
    return as_of - timedelta(days=int(lookback_days))


def cache_symbols() -> list[str]:
    """Sector-kept names already in the DuckDB universe table."""
    from halalquant.database import LocalCache, list_universe

    store = LocalCache(provider=None, filings=None)
    members = store.read_universe()
    if members is not None and not members.empty and "symbol" in members.columns:
        return sorted({str(s) for s in members["symbol"].dropna().unique()})
    try:
        frame = list_universe("sp500")
        if frame is not None and not frame.empty:
            return sorted({str(s) for s in frame["symbol"].dropna().unique()})
    except (OSError, ValueError):
        pass
    # Last resort: whatever the public screen accepts as a tiny smoke list.
    return ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"]


def load_lab(
    as_of: date | str,
    *,
    symbols: Sequence[str] | None = None,
    lookback_days: int = 550,
    cache: bool = True,
    rules=None,
) -> Lab:
    """Metrics + prices for the live FCF book. Needs a prepared cache."""
    session = resolve_as_of(as_of)
    start = lookback_start(session, lookback_days)
    names = list(symbols) if symbols else cache_symbols()
    if not names:
        raise ValueError("No universe symbols in the cache. Run prepare_dataset first.")
    return Lab.from_halalquant(
        names,
        start=start.isoformat(),
        end=session.isoformat(),
        rules=rules or live_rules(),
        freq="ME",
        cache=cache,
    )


def refresh_facts(as_of: date | str | None = None) -> pd.DataFrame:
    import halalquant as hq

    return hq.refresh_dataset(as_of=resolve_as_of(as_of), cache=True, progress=True)
