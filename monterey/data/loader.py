"""Load ResearchData from the halalquant cache and freeze it as a parquet snapshot."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Sequence

import pandas as pd

from monterey.data.research_data import Panels, ResearchData
from monterey.paths import SNAPSHOTS

BENCHMARKS = ("SPY", "SPUS")
TABLES = ("stints", "metrics", "prices", "dividends", "filing_events")


def load_research_data(
    start: str | date,
    end: str | date,
    *,
    index: str = "sp500",
    lookback_days: int = 420,
    symbols: Sequence[str] | None = None,
    snapshot: bool = True,
    refresh: bool = False,
    root: Path | None = None,
    store=None,
    progress: bool | Callable[[str], None] = True,
) -> ResearchData:
    """
    Everything a book needs for ``[start, end]``, read from the halalquant cache.

    Symbols are every index member at any point in the window (leavers
    included) plus today's list and the benchmarks. Prices start
    ``lookback_days`` earlier so a 200-day SMA and 12–1 momentum exist on day
    one. With ``snapshot=True`` the frames are frozen under
    ``data/snapshots/<hash>/`` and reused until the cache changes.
    """
    log = _logger(progress)
    first = pd.Timestamp(start).date()
    last = pd.Timestamp(end).date()
    import halalquant as hq
    from halalquant.database import LocalCache

    if store is None:
        store = LocalCache()
    meta = store.read_meta()
    key = _key(first, last, index, lookback_days, symbols, meta, getattr(hq, "__version__", "?"))
    folder = (root or SNAPSHOTS) / key
    if snapshot and not refresh and (folder / "manifest.json").exists():
        log(f"Loading snapshot {key}")
        return load_snapshot(folder)

    stints = store.read_stints(index)
    universe = store.read_universe(index)
    current = [] if universe is None or universe.empty else sorted(universe["symbol"].astype(str).unique())
    if symbols:
        names = sorted(set(symbols))
    else:
        names = sorted(set(current) | set(_members_in_window(stints, first, last)))
        if stints is None or stints.empty:
            log("No membership stints in the cache: point-in-time universe unavailable, using today's list.")
    priced = sorted(set(names) | set(BENCHMARKS))
    log(f"{len(names)} symbols ({len(current)} current members)")

    price_start = (first - timedelta(days=int(lookback_days))).isoformat()
    prices = store.db.read_prices(priced, start=price_start, end=last.isoformat())
    log(f"{len(prices):,} price rows")
    metrics = store.db.read_metrics(names, start=(first - timedelta(days=62)).isoformat(), end=last.isoformat(), freq="ME")
    if metrics is not None and not metrics.empty:
        metrics = metrics.copy()
        metrics["as_of"] = pd.to_datetime(metrics["as_of"])
        if "fcf" not in metrics.columns and "free_cash_flow" in metrics.columns:
            metrics["fcf"] = pd.to_numeric(metrics["free_cash_flow"], errors="coerce")
    dividends = store.db.read_dividends(names, start=first.isoformat(), end=last.isoformat())
    log("Scanning filings for AAOIFI breaches…")
    events = hq.filing_events(
        as_of=last,
        since=(first - timedelta(days=40)).isoformat(),
        tickers=names,
        cache=store,
    )
    sectors = store.db.read_sector_map(names)

    data = ResearchData(
        start=first,
        end=last,
        index=index,
        stints=stints if stints is not None else pd.DataFrame(),
        current=current,
        sectors=sectors,
        metrics=metrics if metrics is not None else pd.DataFrame(),
        prices=Panels.from_long(prices),
        dividends=dividends if dividends is not None else pd.DataFrame(),
        filing_events=events if events is not None else pd.DataFrame(),
    )
    data.manifest = {
        "hash": key,
        "start": first.isoformat(),
        "end": last.isoformat(),
        "index": index,
        "pit": data.pit_available,
        "lookback_days": int(lookback_days),
        "n_symbols": len(names),
        "n_current": len(current),
        "n_price_rows": int(len(prices)),
        "n_dividends": int(len(data.dividends)),
        "n_filing_events": int(len(data.filing_events)),
        "n_snapshots": len(data.snapshot_dates),
        "halalquant_version": getattr(hq, "__version__", "?"),
        "cache_prepared_at": meta.get("prepared_at"),
        "cache_refreshed_at": meta.get("refreshed_at"),
        "stints_at": meta.get(f"stints_at:{index}"),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    data._long_prices = prices  # kept for the snapshot writer
    if snapshot:
        save_snapshot(data, folder)
        log(f"Froze snapshot {key} → {folder}")
    return data


def save_snapshot(data: ResearchData, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    long_prices = getattr(data, "_long_prices", None)
    if long_prices is None:
        long_prices = _panels_to_long(data.prices)
    frames = {
        "stints": data.stints,
        "metrics": data.metrics,
        "prices": long_prices,
        "dividends": data.dividends,
        "filing_events": data.filing_events,
        "sectors": pd.DataFrame({"symbol": list(data.sectors), "sector": list(data.sectors.values())}),
        "current": pd.DataFrame({"symbol": data.current}),
    }
    for name, frame in frames.items():
        _clean(frame).to_parquet(folder / f"{name}.parquet", index=False)
    (folder / "manifest.json").write_text(
        json.dumps(
            {
                **(data.manifest or {}),
                "start": data.start.isoformat() if hasattr(data.start, "isoformat") else str(data.start),
                "end": data.end.isoformat() if hasattr(data.end, "isoformat") else str(data.end),
                "index": data.index,
            },
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )
    return folder


def load_snapshot(folder: str | Path) -> ResearchData:
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))

    def read(name: str) -> pd.DataFrame:
        path = folder / f"{name}.parquet"
        return pd.read_parquet(path) if path.exists() else pd.DataFrame()

    sectors = read("sectors")
    metrics = read("metrics")
    if not metrics.empty:
        metrics["as_of"] = pd.to_datetime(metrics["as_of"])
    data = ResearchData(
        start=pd.Timestamp(manifest.get("start", "2020-01-02")).date(),
        end=pd.Timestamp(manifest.get("end", manifest.get("start", "2020-01-02"))).date(),
        index=manifest.get("index", "sp500"),
        stints=read("stints"),
        current=list(read("current").get("symbol", pd.Series(dtype=str)).astype(str)),
        sectors=dict(zip(sectors.get("symbol", []), sectors.get("sector", []))),
        metrics=metrics,
        prices=Panels.from_long(read("prices")),
        dividends=read("dividends"),
        filing_events=read("filing_events"),
        manifest=manifest,
    )
    return data


def _key(first, last, index, lookback, symbols, meta, version) -> str:
    payload = {
        "start": first.isoformat(),
        "end": last.isoformat(),
        "index": index,
        "lookback": int(lookback),
        "symbols": sorted(symbols) if symbols else None,
        "prepared_at": meta.get("prepared_at"),
        "refreshed_at": meta.get("refreshed_at"),
        "stints_at": meta.get(f"stints_at:{index}"),
        "end_meta": meta.get("end"),
        "halalquant": version,
        "layout": 1,
    }
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _clean(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None:
        return pd.DataFrame()
    out = frame.copy()
    for column in out.columns:
        if out[column].dtype == object:
            sample = out[column].dropna()
            if not sample.empty and not isinstance(sample.iloc[0], str):
                try:
                    out[column] = pd.to_datetime(out[column])
                except (TypeError, ValueError):
                    out[column] = out[column].astype(str)
    return out


def _panels_to_long(panels: Panels) -> pd.DataFrame:
    parts = []
    for name in ("open", "close", "adj_close", "volume"):
        frame = getattr(panels, name)
        if frame is None or frame.empty:
            continue
        parts.append(frame.stack().rename(name))
    if not parts:
        return pd.DataFrame(columns=["symbol", "date"])
    out = pd.concat(parts, axis=1).reset_index()
    return out.rename(columns={"level_0": "date", "level_1": "symbol"})


def from_frames(
    metrics: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    start=None,
    end=None,
    stints: pd.DataFrame | None = None,
    sectors: dict[str, str] | None = None,
    dividends: pd.DataFrame | None = None,
    filing_events: pd.DataFrame | None = None,
    extras: dict | None = None,
) -> ResearchData:
    """Build ResearchData from in-memory frames (ops tests, notebooks with a Lab)."""
    prices = prices.copy()
    prices["date"] = pd.to_datetime(prices["date"])
    metrics = metrics.copy()
    if not metrics.empty and "as_of" in metrics.columns:
        metrics["as_of"] = pd.to_datetime(metrics["as_of"])
        if "fcf" not in metrics.columns and "free_cash_flow" in metrics.columns:
            metrics["fcf"] = pd.to_numeric(metrics["free_cash_flow"], errors="coerce")
    symbols = sorted(set(metrics["symbol"].astype(str)) if not metrics.empty else [])
    first = pd.Timestamp(start or prices["date"].min()).date() if not prices.empty else pd.Timestamp("2020-01-02").date()
    last = pd.Timestamp(end or prices["date"].max()).date() if not prices.empty else first
    labels = dict(sectors or {})
    for symbol in symbols:
        labels.setdefault(symbol, "unknown")
    return ResearchData(
        start=first,
        end=last,
        index="sp500",
        stints=stints if stints is not None else pd.DataFrame(),
        current=symbols,
        sectors=labels,
        metrics=metrics if metrics is not None else pd.DataFrame(),
        prices=Panels.from_long(prices),
        dividends=dividends if dividends is not None else pd.DataFrame(),
        filing_events=filing_events if filing_events is not None else pd.DataFrame(),
        extras=extras or {},
        manifest={"hash": "frames", "source": "frames"},
    )


def cache_ready() -> bool:
    try:
        from halalquant.database import LocalCache

        store = LocalCache()
        prices = store.db.read_prices(["SPY"], start="2020-01-02", end="2020-01-10")
        return prices is not None and not prices.empty
    except Exception:
        return False


def _members_in_window(stints: pd.DataFrame, start, end) -> list[str]:
    if stints is None or stints.empty or "symbol" not in stints.columns:
        return []
    first = pd.Timestamp(start).normalize()
    last = pd.Timestamp(end).normalize()
    begins = pd.to_datetime(stints["start_date"])
    stops = pd.to_datetime(stints["end_date"], errors="coerce")
    covered = (begins <= last) & (stops.isna() | (stops >= first))
    return list(stints.loc[covered, "symbol"].astype(str).unique())


def _logger(progress):
    if callable(progress):
        return progress
    if progress:
        return lambda message: print(f"[monterey.data] {message}", flush=True)
    return lambda message: None
