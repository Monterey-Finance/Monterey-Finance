"""ResearchData: every fact a book or a notebook needs, loaded once."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from functools import cached_property
from typing import Any

import numpy as np
import pandas as pd

EXCLUDED_ACTIVITIES = frozenset(
    {
        "alcohol",
        "tobacco",
        "gambling",
        "pork",
        "weapons",
        "defense",
        "adult entertainment",
        "conventional banking",
        "conventional insurance",
        "interest-based finance",
    }
)

HALAL_COLUMNS = [
    "symbol",
    "sector",
    "sector_allowed",
    "in_index",
    "market_cap",
    "debt_ratio",
    "cash_ratio",
    "receivables_ratio",
    "financial_pass",
    "is_compliant",
    "reason",
    "metrics_as_of",
]


def sector_allowed(sector: object) -> bool:
    return isinstance(sector, str) and bool(sector.strip()) and sector.strip().lower() not in EXCLUDED_ACTIVITIES


@dataclass
class Panels:
    """Wide date × symbol frames. ``open`` / ``close`` are traded prices; ``adj_close`` is for signals."""

    open: pd.DataFrame
    close: pd.DataFrame
    adj_close: pd.DataFrame
    volume: pd.DataFrame

    @classmethod
    def from_long(cls, prices: pd.DataFrame) -> "Panels":
        if prices is None or prices.empty:
            empty = pd.DataFrame()
            return cls(empty, empty, empty, empty)
        frame = prices.copy()
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.drop_duplicates(["symbol", "date"], keep="last")

        def wide(column: str) -> pd.DataFrame:
            if column not in frame.columns:
                return pd.DataFrame()
            values = pd.to_numeric(frame[column], errors="coerce")
            if column != "volume":
                values = values.where(values > 0)
            out = frame.assign(_v=values).pivot(index="date", columns="symbol", values="_v").sort_index()
            out.columns.name = None
            return out

        adj = wide("adj_close")
        close = wide("close")
        if adj.empty:
            adj = close
        return cls(open=wide("open"), close=close, adj_close=adj, volume=wide("volume"))


@dataclass
class ResearchData:
    start: date
    end: date
    index: str
    stints: pd.DataFrame
    current: list[str]
    sectors: dict[str, str]
    metrics: pd.DataFrame
    prices: Panels
    dividends: pd.DataFrame
    filing_events: pd.DataFrame
    manifest: dict[str, Any] = field(default_factory=dict)
    extras: dict[str, pd.DataFrame] = field(default_factory=dict)

    # -------- calendar --------
    @cached_property
    def sessions(self) -> pd.DatetimeIndex:
        """Trading days: dates with a SPY close."""
        spy = self.prices.close.get("SPY")
        if spy is None:
            return pd.DatetimeIndex(self.prices.close.index)
        return pd.DatetimeIndex(spy.dropna().index)

    def sessions_between(self, start, end) -> pd.DatetimeIndex:
        days = self.sessions
        return days[(days >= pd.Timestamp(start)) & (days <= pd.Timestamp(end))]

    # -------- universe --------
    @property
    def pit_available(self) -> bool:
        return self.stints is not None and not self.stints.empty

    def members(self, as_of, pit: bool = True) -> list[str]:
        """Index members on ``as_of``. ``pit=False`` freezes the list at the snapshot end date."""
        if not self.pit_available:
            return list(self.current)
        day = pd.Timestamp(as_of if pit else self.end).normalize()
        start = pd.to_datetime(self.stints["start_date"])
        stop = pd.to_datetime(self.stints["end_date"], errors="coerce")
        covered = (start <= day) & (stop.isna() | (stop > day))
        return sorted(set(self.stints.loc[covered, "symbol"].astype(str)))

    def universe(self, as_of, pit: bool = True) -> pd.DataFrame:
        names = self.members(as_of, pit=pit)
        frame = pd.DataFrame({"symbol": names})
        frame["sector"] = frame["symbol"].map(self.sectors)
        frame["sector_allowed"] = frame["sector"].map(sector_allowed).astype(bool)
        frame["in_index"] = True
        return frame

    # -------- fundamentals --------
    @cached_property
    def snapshot_dates(self) -> list[date]:
        if self.metrics is None or self.metrics.empty:
            return []
        return sorted(pd.to_datetime(self.metrics["as_of"]).dt.date.unique())

    def snapshot_on_or_before(self, as_of) -> date | None:
        day = pd.Timestamp(as_of).date()
        prior = [d for d in self.snapshot_dates if d <= day]
        return prior[-1] if prior else None

    @cached_property
    def _metrics_by_stamp(self) -> dict[date, pd.DataFrame]:
        if self.metrics is None or self.metrics.empty:
            return {}
        stamps = pd.to_datetime(self.metrics["as_of"]).dt.date
        return {stamp: frame.drop_duplicates("symbol", keep="last") for stamp, frame in self.metrics.groupby(stamps)}

    def metrics_on(self, as_of) -> pd.DataFrame:
        """The month-end AAOIFI snapshot in force on ``as_of`` (last stamp on or before it)."""
        stamp = self.snapshot_on_or_before(as_of)
        if stamp is None:
            return pd.DataFrame(columns=self.metrics.columns if self.metrics is not None else [])
        return self._metrics_by_stamp[stamp].copy()

    def halal(
        self,
        as_of,
        *,
        pit: bool = True,
        sectors: bool = True,
        debt: float = 0.30,
        cash: float = 0.30,
        receivables: float = 0.70,
    ) -> pd.DataFrame:
        """
        Members on ``as_of`` with the activity and AAOIFI ratio screens together.

        ``is_compliant`` needs a known allowed sector (when ``sectors``) and a
        passing ratio snapshot. ``reason`` names the first failed test.
        """
        base = self.universe(as_of, pit=pit)
        snap = self.metrics_on(as_of)
        stamp = self.snapshot_on_or_before(as_of)
        ratios = _ratios(snap)
        out = base.merge(ratios, on="symbol", how="left")
        has = out["market_cap_24m"].notna() & (out["market_cap_24m"] > 0)
        debt_ok = out["debt_ratio"] < debt
        cash_ok = out["cash_ratio"] < cash
        recv_ok = out["receivables_ratio"] < receivables
        out["financial_pass"] = (has & debt_ok & cash_ok & recv_ok).fillna(False).astype(bool)
        reasons = []
        for i, row in out.iterrows():
            if sectors and not isinstance(row["sector"], str):
                reasons.append("missing sector label")
            elif sectors and not row["sector_allowed"]:
                reasons.append(f"excluded activity: {row['sector']}")
            elif not has.iloc[i]:
                reasons.append("no AAOIFI metrics")
            elif not debt_ok.iloc[i]:
                reasons.append("debt ratio exceeds threshold")
            elif not cash_ok.iloc[i]:
                reasons.append("cash ratio exceeds threshold")
            elif not recv_ok.iloc[i]:
                reasons.append("receivables ratio exceeds threshold")
            else:
                reasons.append("passes")
        out["reason"] = reasons
        allowed = out["sector_allowed"] if sectors else True
        out["is_compliant"] = (out["financial_pass"] & allowed).astype(bool)
        out["metrics_as_of"] = stamp
        return out[HALAL_COLUMNS].sort_values("symbol").reset_index(drop=True)

    def impure_ratios(self, as_of) -> dict[str, float]:
        snap = self.metrics_on(as_of)
        if snap.empty or "impure_ratio" not in snap.columns:
            return {}
        values = pd.to_numeric(snap["impure_ratio"], errors="coerce")
        return {str(s): float(v) for s, v in zip(snap["symbol"], values) if pd.notna(v)}

    def breaches_between(self, start, end, symbols=None) -> pd.DataFrame:
        """Failing 10-Q / 10-K filings with ``start < filed_date <= end``."""
        events = self.filing_events
        if events is None or events.empty:
            return pd.DataFrame(columns=["symbol", "filed_date", "reason"])
        filed = pd.to_datetime(events["filed_date"])
        mask = (filed > pd.Timestamp(start)) & (filed <= pd.Timestamp(end))
        mask &= ~events["is_compliant"].fillna(True).astype(bool)
        if symbols is not None:
            mask &= events["symbol"].isin(list(symbols))
        return events.loc[mask].copy()

    # -------- benchmarks --------
    def total_return(self, symbol: str) -> pd.Series:
        series = self.prices.adj_close.get(symbol)
        return pd.Series(dtype=float) if series is None else series.dropna()

    def benchmarks(self, symbols=("SPUS", "SPY")) -> pd.DataFrame:
        return pd.DataFrame({s: self.total_return(s) for s in symbols})

    def dividends_on(self, day) -> pd.DataFrame:
        frame = self.dividends
        if frame is None or frame.empty:
            return pd.DataFrame(columns=["symbol", "ex_date", "dividend"])
        return frame.loc[pd.to_datetime(frame["ex_date"]) == pd.Timestamp(day)]

    @cached_property
    def dividends_by_day(self) -> dict[pd.Timestamp, list[tuple[str, float]]]:
        out: dict[pd.Timestamp, list[tuple[str, float]]] = {}
        frame = self.dividends
        if frame is None or frame.empty:
            return out
        clean = frame.drop_duplicates(["symbol", "ex_date"], keep="last")
        for row in clean.itertuples(index=False):
            amount = float(row.dividend) if pd.notna(row.dividend) else 0.0
            if amount > 0:
                out.setdefault(pd.Timestamp(row.ex_date), []).append((str(row.symbol), amount))
        return out

    def describe(self) -> pd.DataFrame:
        m = self.manifest
        rows = [
            ("window", f"{self.start} → {self.end}"),
            ("universe", f"{self.index}, point-in-time" if self.pit_available else f"{self.index}, current list only"),
            ("symbols", m.get("n_symbols")),
            ("snapshots", len(self.snapshot_dates)),
            ("price rows", m.get("n_price_rows")),
            ("dividends", m.get("n_dividends")),
            ("filing events", m.get("n_filing_events")),
            ("halalquant", m.get("halalquant_version")),
            ("snapshot hash", m.get("hash")),
        ]
        return pd.DataFrame(rows, columns=["field", "value"])


def _ratios(snap: pd.DataFrame) -> pd.DataFrame:
    cols = ["symbol", "market_cap", "market_cap_24m", "debt_ratio", "cash_ratio", "receivables_ratio"]
    if snap is None or snap.empty:
        return pd.DataFrame(columns=cols)
    frame = snap.copy()
    num = lambda c: pd.to_numeric(frame.get(c), errors="coerce") if c in frame.columns else pd.Series(np.nan, index=frame.index)  # noqa: E731
    # Same denominator as halalquant's AAOIFIScreener: the 24-month cap when the column exists.
    mc24 = (num("market_cap_24m") if "market_cap_24m" in frame.columns else num("market_cap")).where(lambda s: s > 0)
    debt = num("total_debt").fillna(0.0)
    cash = num("cash_and_equiv").fillna(0.0) + num("interest_bearing_securities").fillna(0.0)
    recv = num("receivables").fillna(0.0) + num("liquid_assets").fillna(0.0)
    return pd.DataFrame(
        {
            "symbol": frame["symbol"].astype(str).values,
            "market_cap": num("market_cap").values,
            "market_cap_24m": mc24.values,
            "debt_ratio": (debt / mc24).values,
            "cash_ratio": (cash / mc24).values,
            "receivables_ratio": (recv / mc24).values,
        }
    )
