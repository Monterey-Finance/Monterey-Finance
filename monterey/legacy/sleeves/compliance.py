"""Point-in-time AAOIFI filter shared by every sleeve."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .rules import AaoifiRules, FrozenRules, SHARE_CLASS_MAP


def _screener(rules: AaoifiRules):
    from halalquant.screening._aaoifi import AAOIFIScreener

    return AAOIFIScreener(
        debt_threshold=rules.debt_threshold,
        cash_threshold=rules.cash_threshold,
        receivables_threshold=rules.receivables_threshold,
    )


def snapshot_on(panel: pd.DataFrame, as_of: date | str) -> pd.DataFrame:
    if panel is None or panel.empty:
        return pd.DataFrame()
    as_of_d = pd.Timestamp(as_of).date()
    return panel[pd.to_datetime(panel["as_of"]).dt.date == as_of_d].copy()


def last_snapshot_on_or_before(panel: pd.DataFrame, as_of: date | str) -> pd.DataFrame:
    if panel is None or panel.empty or "as_of" not in panel.columns:
        return pd.DataFrame()
    as_of_d = pd.Timestamp(as_of).date()
    dates = pd.to_datetime(panel["as_of"]).dt.date
    prior = sorted({d for d in dates if d <= as_of_d})
    if not prior:
        return pd.DataFrame()
    return snapshot_on(panel, prior[-1])


def halal_pass(
    snap: pd.DataFrame,
    rules: FrozenRules | AaoifiRules | None = None,
    apply_halal: bool = True,
) -> pd.DataFrame:
    """Return compliant rows with ratio columns attached."""
    if snap is None or snap.empty:
        return pd.DataFrame()
    aaoifi = rules.aaoifi if isinstance(rules, FrozenRules) else (rules or AaoifiRules())
    work = snap.copy()
    if "report_date" not in work.columns:
        work["report_date"] = work.get("as_of")
    if not apply_halal:
        for col in ("debt_ratio", "cash_ratio", "receivables_ratio", "is_compliant"):
            if col not in work.columns:
                work[col] = np.nan if col != "is_compliant" else True
        work = work[pd.to_numeric(work["market_cap"], errors="coerce") > 0]
        return work

    screened = _screener(aaoifi).evaluate_compliance(work)
    work = work.drop(
        columns=[c for c in ("debt_ratio", "cash_ratio", "receivables_ratio") if c in work.columns]
    )
    passed = work.merge(screened, on="symbol", how="inner")
    passed = passed.loc[passed["is_compliant"].fillna(False).astype(bool)].copy()
    if passed.empty or "market_cap" not in passed.columns:
        return passed
    passed = passed[pd.to_numeric(passed["market_cap"], errors="coerce") > 0]
    return passed


def collapse_issuers(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "symbol" not in frame.columns:
        return frame
    out = frame.copy()
    out["symbol"] = out["symbol"].replace(SHARE_CLASS_MAP)
    return out.drop_duplicates("symbol", keep="first")
