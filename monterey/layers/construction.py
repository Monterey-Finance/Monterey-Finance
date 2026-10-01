"""Construction layer: selection → invested weights (sum to 1) with name and sector lids."""

from __future__ import annotations

import pandas as pd

from monterey.legacy.sleeves.weighting import apply_name_cap, collapse_share_classes
from monterey.spec import BookSpec


def build_weights(selected: pd.DataFrame, spec: BookSpec, sectors: dict[str, str] | None = None) -> pd.Series:
    """Weights for the fully invested book, before the overlay scales exposure."""
    if selected is None or selected.empty:
        return pd.Series(dtype=float)
    c = spec.construction
    frame = selected.copy()
    kind = str(c["weight"])
    if kind == "cap":
        raw = pd.to_numeric(frame["market_cap"], errors="coerce").clip(lower=0).fillna(0.0)
        if raw.sum() <= 0:
            raw = pd.Series(1.0, index=frame.index)
    elif kind == "equal":
        raw = pd.Series(1.0, index=frame.index)
    elif kind == "score":
        raw = pd.to_numeric(frame["score"], errors="coerce").clip(lower=0).fillna(0.0)
    else:
        raise ValueError(f"unknown construction.weight {kind!r}")
    frame["weight"] = raw / raw.sum()
    frame = frame.sort_values("weight", ascending=False)
    if c.get("collapse_share_classes"):
        # Same as the frozen book: keep the larger listing of a dual class, then renormalise.
        frame = collapse_share_classes(frame)
    weights = frame.set_index("symbol")["weight"].astype(float)
    weights = weights[weights > 0]
    weights = weights / weights.sum()
    weights = apply_name_cap(weights, c.get("name_cap"))
    if c.get("sector_cap"):
        weights = apply_sector_cap(weights, sectors or {}, float(c["sector_cap"]), c.get("name_cap"))
    return weights.sort_values(ascending=False)


def apply_sector_cap(
    weights: pd.Series,
    sectors: dict[str, str],
    cap: float,
    name_cap: float | None = None,
    iterations: int = 50,
) -> pd.Series:
    """
    Scale sectors above ``cap`` down to it and spread the excess over the other
    sectors in proportion. Re-applies the name cap each pass. If every sector
    would breach the lid, the book cannot satisfy it and the last pass is kept.
    """
    w = weights.astype(float).copy()
    if w.empty or cap <= 0:
        return w
    labels = w.index.map(lambda s: sectors.get(str(s)) or "unknown")
    for _ in range(iterations):
        by_sector = w.groupby(labels).sum()
        over = by_sector[by_sector > cap + 1e-9]
        if over.empty:
            break
        under_mask = ~labels.isin(over.index)
        room = float(w[under_mask].sum())
        if room <= 0:
            break
        excess = 0.0
        for sector, total in over.items():
            mask = labels == sector
            scale = cap / total
            excess += float(w[mask].sum()) * (1 - scale)
            w[mask] = w[mask] * scale
        w[under_mask] = w[under_mask] + excess * (w[under_mask] / room)
        if name_cap:
            w = apply_name_cap(w, name_cap)
    return w / w.sum()


def drop_and_renormalise(weights: pd.Series, names, spec: BookSpec, sectors: dict[str, str] | None = None) -> pd.Series:
    """Remove breached names and re-apply the lids to what is left."""
    kept = weights.drop(labels=[n for n in names if n in weights.index])
    if kept.empty:
        return kept
    kept = kept / kept.sum()
    c = spec.construction
    kept = apply_name_cap(kept, c.get("name_cap"))
    if c.get("sector_cap"):
        kept = apply_sector_cap(kept, sectors or {}, float(c["sector_cap"]), c.get("name_cap"))
    return kept
