"""Clearing a halt is an audited action. The flag does not drop by itself."""

from __future__ import annotations

from pathlib import Path

from ops.account import PaperAccount, load_account, save_account
from ops.audit import append_event


def clear_halt(
    account: PaperAccount | None = None,
    *,
    actor: str,
    reason: str,
    root: Path | None = None,
) -> PaperAccount:
    who = str(actor or "").strip()
    why = str(reason or "").strip()
    if not who or not why:
        raise ValueError("actor and reason are required")
    book = account or load_account(root)
    if not book.halted:
        raise ValueError("the account is not halted")
    prior = book.halt_reason
    book.halted = False
    book.halt_reason = ""
    append_event(
        "halt_cleared",
        actor=who,
        root=root,
        reason=why,
        prior_reason=prior,
    )
    save_account(book, root)
    return book
