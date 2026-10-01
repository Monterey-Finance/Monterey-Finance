"""python -m ops — paper-fund session and the operator actions around it."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from typing import Optional, Sequence


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ops",
        description="Run the paper fund, or record a cash move, order approval, or halt clearance.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="Refresh, write target weights, trade the paper account, mark NAV.")
    _add_run_flags(run)

    schedule = sub.add_parser("schedule", help="Run today's session when the market is open and NAV is unmarked.")
    schedule.add_argument("--as-of", default="today")
    schedule.add_argument("--dry-run", action="store_true")
    schedule.add_argument("--skip-refresh", action="store_true")
    schedule.add_argument("--draft-only", action="store_true")
    schedule.add_argument("--venue", choices=("local", "alpaca"), default="local")
    schedule.add_argument("--capital", type=float, default=1_000_000)

    replay = sub.add_parser("replay", help="Walk a date range in one process, loading the market cache once.")
    replay.add_argument("--start", required=True, help="YYYY-MM-DD.")
    replay.add_argument("--end", required=True, help="YYYY-MM-DD.")
    replay.add_argument("--budget-minutes", type=float, default=0, help="Stop cleanly after this many minutes. 0 runs the whole range.")
    replay.add_argument("--lookback-days", type=int, default=550)

    approve = sub.add_parser("approve", help="Approve a draft batch and queue it for the next open.")
    approve.add_argument("--as-of", default="today")
    approve.add_argument("--actor", required=True)

    cancel = sub.add_parser("cancel", help="Cancel a draft batch. This does not trade.")
    cancel.add_argument("--as-of", default="today")
    cancel.add_argument("--actor", required=True)

    cash = sub.add_parser("cash", help="Paper deposit or withdrawal.")
    cash_sub = cash.add_subparsers(dest="cash_cmd", required=True)
    for name in ("deposit", "withdraw"):
        cmd = cash_sub.add_parser(name)
        cmd.add_argument("--amount", type=float, required=True)
        cmd.add_argument("--actor", required=True)
        cmd.add_argument("--reason", required=True)
        cmd.add_argument("--confirm", action="store_true")

    contribute = sub.add_parser("contribute", help="Turn the monthly paper contribution on or off.")
    contribute.add_argument("--actor", required=True)
    contribute.add_argument("--amount", type=float, default=0.0)
    contribute.add_argument("--next", default="", help="YYYY-MM-DD. Required when turning the plan on.")
    mode = contribute.add_mutually_exclusive_group(required=True)
    mode.add_argument("--on", action="store_true")
    mode.add_argument("--off", action="store_true")

    halt = sub.add_parser("halt", help="Clear a halt. The reason is stored in the audit log.")
    halt_sub = halt.add_subparsers(dest="halt_cmd", required=True)
    clear = halt_sub.add_parser("clear")
    clear.add_argument("--actor", required=True)
    clear.add_argument("--reason", required=True)

    purify = sub.add_parser("purify", help="Export the purification ledger or post accrued rows.")
    purify_sub = purify.add_subparsers(dest="purify_cmd", required=True)
    purify_sub.add_parser("export")
    post = purify_sub.add_parser("post")
    post.add_argument("--actor", required=True)
    post.add_argument("--key", action="append", default=None)

    audit = sub.add_parser("audit", help="Read the audit log, or record a note.")
    audit_sub = audit.add_subparsers(dest="audit_cmd", required=True)
    listing = audit_sub.add_parser("list")
    listing.add_argument("--type", default="")
    listing.add_argument("--since", default="")
    note = audit_sub.add_parser("note")
    note.add_argument("--actor", required=True)
    note.add_argument("--reason", required=True)
    note.add_argument("--symbol", default="")
    note.add_argument("--attachment", default="")

    rules = sub.add_parser("rules", help="Propose or confirm a frozen-rule change.")
    rules_sub = rules.add_subparsers(dest="rules_cmd", required=True)
    propose = rules_sub.add_parser("propose")
    propose.add_argument("--actor", required=True)
    propose.add_argument("--reason", required=True)
    propose.add_argument("--name-cap", type=float, default=None)
    propose.add_argument("--cost-bps", type=float, default=None)
    propose.add_argument("--throttle", default=None)
    propose.add_argument("--breach-exit", default=None)
    propose.add_argument("--purify-schedule", default=None)
    propose.add_argument("--rebalance-freq", default=None)
    confirm = rules_sub.add_parser("confirm")
    confirm.add_argument("--id", required=True)
    confirm.add_argument("--actor", required=True)

    sub.add_parser("health", help="Risk figures from the paper NAV ledger.")

    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return _dispatch(args)
    except Exception as exc:
        sys.stderr.write(f"ops {args.cmd} failed: {exc}\n")
        return 1


def _add_run_flags(run: argparse.ArgumentParser) -> None:
    run.add_argument("--as-of", default="today", help="YYYY-MM-DD or today.")
    run.add_argument("--skip-refresh", action="store_true", help="Do not call halalquant refresh.")
    run.add_argument("--targets-only", action="store_true", help="Write the intended book and do not trade.")
    run.add_argument("--capital", type=float, default=1_000_000, help="Starting paper cash if the account is new.")
    run.add_argument("--min-notional", type=float, default=100, help="Skip rebalance trades smaller than this many dollars.")
    run.add_argument("--coverage", action="store_true", help="Write coverage_summary from the cache.")
    run.add_argument("--lookback-days", type=int, default=550, help="Price/metrics window into the cache.")
    run.add_argument("--no-persist", action="store_true", help="Print only; do not write ops/runs/.")
    run.add_argument("--venue", choices=("local", "alpaca"), default="local")
    run.add_argument("--draft-only", action="store_true", help="Write a draft batch and do not submit orders.")


def _dispatch(args) -> int:
    if args.cmd == "run":
        return _cmd_run(args)
    if args.cmd == "schedule":
        return _cmd_schedule(args)
    if args.cmd == "replay":
        return _cmd_replay(args)
    if args.cmd == "approve":
        from ops.commit import approve_draft

        print(json.dumps(approve_draft(args.as_of, actor=args.actor), indent=2, default=str))
        return 0
    if args.cmd == "cancel":
        from ops.commit import cancel_draft

        print(json.dumps(cancel_draft(args.as_of, actor=args.actor), indent=2, default=str))
        return 0
    if args.cmd == "cash":
        return _cmd_cash(args)
    if args.cmd == "contribute":
        return _cmd_contribute(args)
    if args.cmd == "halt":
        from ops.halt import clear_halt

        clear_halt(actor=args.actor, reason=args.reason)
        print(json.dumps({"halted": False, "reason": args.reason}, indent=2))
        return 0
    if args.cmd == "purify":
        return _cmd_purify(args)
    if args.cmd == "audit":
        return _cmd_audit(args)
    if args.cmd == "rules":
        return _cmd_rules(args)
    if args.cmd == "health":
        from ops.health import health_report

        print(json.dumps(health_report(), indent=2, default=str))
        return 0
    raise ValueError(f"unknown command {args.cmd}")


def _cmd_run(args) -> int:
    if args.targets_only:
        from ops.session import run_session

        result = run_session(
            args.as_of,
            refresh=not args.skip_refresh,
            coverage=args.coverage,
            persist=not args.no_persist,
            trade=False,
            capital=args.capital,
            min_notional=args.min_notional,
            lookback_days=args.lookback_days,
            venue=args.venue,
            commit=not args.draft_only,
        )
        _print_session(result)
        return 0
    from ops.fund import run_live_session

    print(json.dumps(run_live_session(
        args.as_of,
        refresh=not args.skip_refresh,
        capital=args.capital,
        persist=not args.no_persist,
        venue=args.venue,
    ), indent=2, default=str))
    return 0


def _cmd_schedule(args) -> int:
    from ops.fund import run_live_session
    from ops.schedule import run_schedule

    def runner(day: date):
        return run_live_session(
            day,
            refresh=not args.skip_refresh,
            venue=args.venue,
            capital=args.capital,
        )

    outcome = run_schedule(args.as_of, dry_run=args.dry_run, runner=runner)
    print(json.dumps(outcome, indent=2, default=str))
    return 0


def _cmd_replay(args) -> int:
    from ops.fund import replay_book

    ledger = replay_book(
        args.start,
        args.end,
        progress=True,
    )
    print(json.dumps({
        "book": ledger.spec.id,
        "hash": ledger.spec.hash(),
        "sessions": int(len(ledger.nav)),
        "last_nav": None if ledger.nav.empty else float(ledger.nav["nav"].iloc[-1]),
        "path": str(ledger.path),
    }, indent=2))
    return 0


def _cmd_cash(args) -> int:
    from ops.account import load_account
    from ops.cash import move_cash

    account = load_account()
    record = move_cash(
        account,
        args.amount,
        args.cash_cmd,
        actor=args.actor,
        reason=args.reason,
        confirm=args.confirm,
    )
    print(json.dumps(record, indent=2))
    return 0


def _cmd_contribute(args) -> int:
    from ops.cash import set_contribution

    next_date = date.fromisoformat(args.next) if args.next else None
    plan = set_contribution(
        enabled=bool(args.on),
        amount=args.amount,
        next_date=next_date,
        actor=args.actor,
    )
    print(json.dumps(plan, indent=2))
    return 0


def _cmd_purify(args) -> int:
    if args.purify_cmd == "export":
        from ops.purify_ledger import export_purification, totals

        path = export_purification()
        print(json.dumps({"path": str(path), **totals()}, indent=2))
        return 0
    from ops.account import load_account, save_account
    from ops.purify_ledger import post_ledger

    account = load_account()
    paid = post_ledger(account, actor=args.actor, keys=args.key)
    save_account(account)
    print(json.dumps({"posted": paid}, indent=2))
    return 0


def _cmd_audit(args) -> int:
    from ops.audit import append_event, read_events

    if args.audit_cmd == "note":
        row = append_event(
            "override",
            actor=args.actor,
            reason=args.reason,
            symbol=args.symbol,
            attachment=args.attachment,
        )
        print(json.dumps(row, indent=2))
        return 0
    rows = read_events(
        event_type=args.type or None,
        since=args.since or None,
    )
    print(json.dumps(rows, indent=2, default=str))
    return 0


def _cmd_rules(args) -> int:
    from ops.ruleset import confirm, propose

    if args.rules_cmd == "confirm":
        print(json.dumps(confirm(args.id, actor=args.actor), indent=2, default=str))
        return 0
    changes = {}
    for key, value in (
        ("name_cap", args.name_cap),
        ("cost_bps", args.cost_bps),
        ("throttle", args.throttle),
        ("breach_exit", args.breach_exit),
        ("purify_schedule", args.purify_schedule),
        ("rebalance_freq", args.rebalance_freq),
    ):
        if value is not None:
            changes[key] = value
    print(json.dumps(propose(changes, actor=args.actor, reason=args.reason), indent=2))
    return 0


def _print_session(result) -> None:
    summary = result.book.summary()
    summary.update(result.extra)
    if result.folder:
        summary["run_dir"] = str(result.folder)
    print(json.dumps(summary, indent=2, default=str))
    if result.breaches is not None and not result.breaches.empty:
        print("\nFiling fails (library reports; fund sells next open):")
        cols = [c for c in ("symbol", "form", "filed_date", "reason") if c in result.breaches.columns]
        print(result.breaches[cols].to_string(index=False) if cols else result.breaches.to_string(index=False))


if __name__ == "__main__":
    raise SystemExit(main())
