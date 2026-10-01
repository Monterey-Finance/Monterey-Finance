"""python -m monterey  — replay a book spec, write diagnostics."""

from __future__ import annotations

import argparse
import json

from monterey.spec import BookSpec


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m monterey")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="Simulate a book spec over a date window.")
    run.add_argument("book", help="Name under books/ or a YAML path.")
    run.add_argument("--start", default="2020-01-02")
    run.add_argument("--end", default="2026-09-30")
    run.add_argument("--mode", default="replay")
    run.add_argument("--no-write", action="store_true")
    sub.add_parser("archive-v1", help="Copy ops/state/nav.csv into a monterey ledger folder.")
    sub.add_parser("v2-baseline", help="Run fcf-sma-v2-baseline and write Research/diagnostics/v2-baseline.md.")
    sub.add_parser("write-sprints", help="Write Research/papers/16–20 notebooks.")
    sprint = sub.add_parser("sprint", help="Run one October sprint (16–20) against v2 baseline.")
    sprint.add_argument("number", choices=["16", "17", "18", "19", "20"])
    args = parser.parse_args(argv)

    if args.cmd == "archive-v1":
        from ops.fund import archive_v1_ledger

        print(archive_v1_ledger())
        return 0
    if args.cmd == "v2-baseline":
        from monterey.research import run_v2_baseline

        ledger, diag = run_v2_baseline()
        print(json.dumps({
            "path": str(ledger.path),
            "hash": ledger.spec.hash(),
            "total_return": (diag.get("performance") or {}).get("total_return"),
        }, indent=2, default=str))
        return 0
    if args.cmd == "write-sprints":
        from monterey.sprints import write_notebooks

        for path in write_notebooks():
            print(path)
        return 0
    if args.cmd == "sprint":
        from monterey.sprints import run_sprint

        ledgers, table = run_sprint(args.number)
        print(table.to_string())
        print(json.dumps({"ledgers": [str(getattr(row, "path", "")) for row in ledgers]}, indent=2))
        return 0

    from monterey.data import load_research_data
    from monterey.diagnostics import diagnose
    from monterey.paths import LEDGERS
    from monterey.sim import simulate

    spec = BookSpec.load(args.book)
    data = load_research_data(args.start, args.end)
    ledger = simulate(
        spec,
        data,
        args.start,
        args.end,
        root=None if args.no_write else LEDGERS,
        mode=args.mode,
        progress=True,
    )
    if ledger.path is not None:
        diagnose(ledger, data)
    print(json.dumps({
        "book": spec.id,
        "hash": spec.hash(),
        "sessions": len(ledger.nav),
        "path": str(ledger.path),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
