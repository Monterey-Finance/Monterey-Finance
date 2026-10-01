"""Diagnostics computed from any ledger. Papers, the desk, and the audit all read diagnostics.json."""

from monterey.diagnostics.performance import relative, scorecard, stats, yearly
from monterey.diagnostics.report import diagnose, headline_table, write_audit, yearly_table

__all__ = ["diagnose", "headline_table", "relative", "scorecard", "stats", "yearly", "yearly_table", "write_audit"]
