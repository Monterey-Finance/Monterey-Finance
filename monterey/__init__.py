"""Monterey Finance fund core.

    from monterey import BookSpec, simulate
    from monterey.research import boot

    rd = boot("paper-16", start="2019-12-01", end="2026-09-30")
    spec = BookSpec.load("fcf-sma-v2-baseline")
    ledger = simulate(spec, rd, start="2020-01-02", end="2026-09-30")
"""

from monterey.spec import BookSpec

__version__ = "0.2.0"

__all__ = ["BookSpec", "simulate", "__version__"]


def __getattr__(name: str):
    if name == "simulate":
        from monterey.sim.engine import simulate

        return simulate
    raise AttributeError(name)
