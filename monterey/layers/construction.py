"""Construction layer: selection → invested weights (sum to 1) with name and sector lids."""

from __future__ import annotations

from typing import Mapping

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
    if c.get("sector_floors"):
        weights = apply_sector_floors(weights, sectors or {}, c["sector_floors"], c.get("name_cap"))
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


def apply_sector_floors(
    weights: pd.Series,
    sectors: dict[str, str],
    floors: Mapping[str, float] | None,
    name_cap: float | None = None,
    iterations: int = 50,
) -> pd.Series:
    """
    Lift sectors already on the list up to a minimum weight. Extra weight comes
    from names already in the book, not from names the brain did not pick.
    A floor whose sector has no holdings is skipped. Re-applies the name cap
    each pass. If donors have no room left under their own floors, the last
    pass is kept.
    """
    w = weights.astype(float).copy()
    if w.empty or not floors:
        return w
    wanted = {_sector_key(name): float(level) for name, level in dict(floors).items() if level and float(level) > 0}
    if not wanted:
        return w
    labels = w.index.map(lambda s: sectors.get(str(s)) or "unknown")
    keys = labels.map(_sector_key)
    for _ in range(iterations):
        by_key = w.groupby(keys).sum()
        present = {key for key, total in by_key.items() if float(total) > 1e-12}
        under = {}
        for key, floor in wanted.items():
            if key not in present:
                continue
            current = float(by_key.get(key, 0.0))
            if current + 1e-9 < floor:
                under[key] = floor - current
        if not under:
            break
        need = sum(under.values())
        capacity = {}
        for key in present:
            if key in under:
                continue
            current = float(by_key[key])
            room = current - wanted.get(key, 0.0)
            if room > 1e-12:
                capacity[key] = room
        room_total = sum(capacity.values())
        if room_total <= 0:
            break
        take = min(need, room_total)
        for key, deficit in under.items():
            add = take * (deficit / need)
            mask = keys == key
            current = float(w[mask].sum())
            if current <= 0:
                continue
            w[mask] = w[mask] * ((current + add) / current)
        for key, room in capacity.items():
            cut = take * (room / room_total)
            mask = keys == key
            current = float(w[mask].sum())
            if current <= 0:
                continue
            w[mask] = w[mask] * ((current - cut) / current)
        if name_cap:
            w = apply_name_cap(w, name_cap)
        w = w / w.sum()
    return w / w.sum()


def _sector_key(label) -> str:
    key = str(label).strip().lower()
    if key == "healthcare":
        return "health care"
    return key


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
    if c.get("sector_floors"):
        kept = apply_sector_floors(kept, sectors or {}, c["sector_floors"], c.get("name_cap"))
    return kept
