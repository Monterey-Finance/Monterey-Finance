"""Brains: the swappable stock-selection layer."""

from monterey.layers.signals import brains as _brains  # noqa: F401  (registers the built-ins)
from monterey.layers.signals.registry import BRAINS, Context, brain, run_brain

__all__ = ["BRAINS", "Context", "brain", "run_brain"]
