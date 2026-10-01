"""Live book: the YAML spec, plus FrozenRules for notebooks that still load sleeves."""

from __future__ import annotations

from pathlib import Path

from monterey.spec import BookSpec
from ops.paths import STATE, ensure_research_on_path

ensure_research_on_path()

from sleeves.rules import FrozenRules  # noqa: E402

LIVE_BOOK = "fcf-sma-v2-baseline"
BOOK_VERSION = "fcf-sma-v2-baseline"


def live_spec(root: Path | None = None) -> BookSpec:
    """The traded book. An overlay in ``ops/state/rules_overlay.json`` is applied if present."""
    spec = BookSpec.load(LIVE_BOOK)
    overlay = _overlay(root)
    if not overlay:
        return spec
    return spec.replace(**overlay)


def live_rules() -> FrozenRules:
    """FCF quality funnel, 10% name cap, whole-NAV SPY SMA to cash."""
    spec = BookSpec.load(LIVE_BOOK)
    book = spec.construction
    screen = spec.screen
    overlay = spec.overlay
    accounting = spec.accounting
    return FrozenRules().with_book(
        sleeve_weights={
            "fcf_quality": 1.0,
            "roic": 0.0,
            "sue": 0.0,
            "dual_momentum": 0.0,
            "high_beta": 0.0,
        },
        name_cap=float(book["name_cap"] or 0.10),
        throttle="spy_sma" if overlay["kind"] == "spy_sma" else "off",
        collapse_share_classes=bool(book.get("collapse_share_classes", True)),
        cost_bps=float(accounting["cost_bps"]),
        rebalance_freq="ME",
        breach_exit=str(screen["breach_exit"]),
        breach_monitor="filings",
        purify_schedule=str(accounting["purify"]),
    )


def _overlay(root: Path | None) -> dict:
    import json

    path = (root or STATE) / "rules_overlay.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    changes = dict(payload.get("changes") or {})
    allowed = ("universe", "screen", "signal", "construction", "overlay", "execution", "accounting")
    return {key: value for key, value in changes.items() if key in allowed}
