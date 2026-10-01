"""Universe layer: who is in the index on a date."""

from __future__ import annotations

import pandas as pd

from monterey.data import ResearchData
from monterey.spec import BookSpec


def members(data: ResearchData, as_of, spec: BookSpec) -> pd.DataFrame:
    """Index members on ``as_of``, point-in-time or today's list as the spec says."""
    return data.universe(as_of, pit=bool(spec.universe["pit"]))
