"""Position weights used by every sleeve."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .rules import SHARE_CLASS_MAP


def assign_cap_weights(selected: pd.DataFrame) -> pd.DataFrame:
    out = selected.copy()
    if out.empty:
        out["weight"] = pd.Series(dtype=float)
        return out
    cap = pd.to_numeric(out["market_cap"], errors="coerce").clip(lower=0)
    total = float(cap.sum(skipna=True))
    if np.isfinite(total) and total > 0:
        out["weight"] = cap / total
        out["weight"] = out["weight"].fillna(0.0)
        wsum = float(out["weight"].sum())
        out["weight"] = out["weight"] / wsum if wsum > 0 else 1.0 / len(out)
    else:
        out["weight"] = 1.0 / len(out)
    return out


def assign_equal_weights(selected: pd.DataFrame) -> pd.DataFrame:
    out = selected.copy()
    if out.empty:
        out["weight"] = pd.Series(dtype=float)
        return out
    out["weight"] = 1.0 / len(out)
    return out


def collapse_share_classes(
    frame: pd.DataFrame,
    symbol_col: str = "symbol",
    mapping: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Map dual listings onto one ticker so GOOG/GOOGL cannot both get weight."""
    if frame.empty or symbol_col not in frame.columns:
        return frame
    mapping = mapping or SHARE_CLASS_MAP
    out = frame.copy()
    out[symbol_col] = out[symbol_col].replace(mapping)
    subset = [symbol_col]
    if "announce_date" in out.columns:
        subset.append("announce_date")
    return out.drop_duplicates(subset, keep="first")


def apply_name_cap(weights: pd.Series, cap: float | None) -> pd.Series:
    """Clip single-name weights and push leftover onto uncapped names."""
    w = weights.astype(float).copy()
    w = w[w > 0]
    if w.empty or cap is None or cap <= 0:
        return w
    total = float(w.sum())
    if total <= 0:
        return w
    w = w / total
    for _ in range(20):
        over = w > cap + 1e-12
        if not over.any():
            break
        w.loc[over] = cap
        leftover = 1.0 - float(w.sum())
        under = w < cap - 1e-12
        room = float(w.loc[under].sum())
        if leftover <= 1e-12 or room <= 0:
            break
        w.loc[under] = w.loc[under] + leftover * (w.loc[under] / room)
    w = w.clip(upper=cap)
    s = float(w.sum())
    return w / s if s > 0 else w


def blend_sleeve_weights(
    sleeves: dict[str, pd.Series],
    sleeve_weights: dict[str, float],
    name_cap: float | None = None,
) -> pd.Series:
    """Combine sleeve weight series into one book. Missing names are zero."""
    combined = pd.Series(dtype=float)
    for sleeve_id, series in sleeves.items():
        scale = float(sleeve_weights.get(sleeve_id, 0.0))
        if scale <= 0 or series is None or series.empty:
            continue
        s = series.astype(float)
        s = s[s > 0]
        if s.empty:
            continue
        s = s / s.sum() * scale
        combined = combined.add(s, fill_value=0.0)
    if combined.empty:
        return combined
    combined = combined / combined.sum()
    return apply_name_cap(combined, name_cap)
