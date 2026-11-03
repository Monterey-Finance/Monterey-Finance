"""Overlay layer: how much of NAV is invested, decided at each close.

The series is indexed by the close that decided it. Execution applies it at
the next open, so a signal never earns the return of the day that made it.
A brake on this book's own NAV cannot live here — ``regime()`` runs before
any NAV exists. That rule is applied in ``Simulator.step``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from monterey.data import ResearchData
from monterey.spec import BookSpec


def regime(data: ResearchData, spec: BookSpec, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    """Columns ``on`` (switch state), ``raw`` (price vs line today), and ``exposure`` in [0, 1]."""
    o = spec.overlay
    kind = str(o["kind"])
    if kind in {"none", "off", ""}:
        frame = pd.DataFrame(index=sessions)
        frame["raw"] = True
        frame["on"] = True
        frame["exposure"] = 1.0
        return _vol_scale(frame, data, spec, sessions)

    window = int(o["window"])
    band = float(o.get("band") or 0.0)
    confirm = int(o.get("confirm_days") or 0)
    off = float(o.get("off_exposure") or 0.0)

    if kind == "spy_sma":
        raw, on = _sma_state(data, str(o["ticker"]), sessions, window, band, confirm)
    elif kind == "both_sma":
        spy_raw, spy_on = _sma_state(data, "SPY", sessions, window, band, confirm)
        other_raw, other_on = _sma_state(data, str(o.get("ticker") or "SPUS"), sessions, window, band, confirm)
        raw, on = spy_raw & other_raw, spy_on & other_on
    elif kind == "either_sma":
        spy_raw, spy_on = _sma_state(data, "SPY", sessions, window, band, confirm)
        other_raw, other_on = _sma_state(data, str(o.get("ticker") or "SPUS"), sessions, window, band, confirm)
        raw, on = spy_raw | other_raw, spy_on | other_on
    else:
        raise ValueError(f"unknown overlay kind {kind!r}")

    frame = pd.DataFrame(index=sessions)
    frame["raw"] = raw.values
    frame["on"] = on.values
    frame["exposure"] = np.where(frame["on"], 1.0, off)
    return _vol_scale(frame, data, spec, sessions)


def _sma_state(
    data: ResearchData,
    ticker: str,
    sessions: pd.DatetimeIndex,
    window: int,
    band: float,
    confirm: int,
) -> tuple[pd.Series, pd.Series]:
    px = data.prices.adj_close.get(ticker)
    if px is None:
        raise ValueError(f"no {ticker} prices for the overlay")
    px = px.ffill().dropna()
    sma = px.rolling(window, min_periods=window).mean()
    raw = (px > sma).reindex(sessions).ffill().fillna(False).astype(bool)
    upper = (px > sma * (1 + band)).reindex(sessions).ffill().fillna(False).astype(bool)
    lower = (px < sma * (1 - band)).reindex(sessions).ffill().fillna(False).astype(bool)
    ready = sma.reindex(sessions).ffill().notna()

    states = []
    on = False
    streak = 0
    for i in range(len(sessions)):
        if not ready.iloc[i]:
            on, streak = False, 0
            states.append(on)
            continue
        if band > 0:
            want_flip = (not on and upper.iloc[i]) or (on and lower.iloc[i])
        else:
            want_flip = raw.iloc[i] != on
        streak = streak + 1 if want_flip else 0
        if want_flip and streak > confirm:
            on, streak = not on, 0
        states.append(on)
    return raw, pd.Series(states, index=sessions)


def _vol_scale(frame: pd.DataFrame, data: ResearchData, spec: BookSpec, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    o = spec.overlay
    target = o.get("vol_target")
    if not target:
        return frame
    px = data.prices.adj_close.get(str(o["ticker"]))
    returns = px.ffill().pct_change()
    realised = returns.rolling(int(o.get("vol_lookback") or 20)).std() * np.sqrt(252)
    scale = (float(target) / realised).clip(upper=1.0).reindex(sessions).ffill().fillna(1.0)
    frame["exposure"] = frame["exposure"] * scale.values
    # Round to 5% steps so a small vol wiggle does not trade the whole book.
    frame["exposure"] = (frame["exposure"] * 20).round() / 20
    return frame
