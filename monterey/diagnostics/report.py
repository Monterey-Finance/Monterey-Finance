"""diagnose(ledger, data) → diagnostics.json, and a markdown write-up from it."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from monterey.data import ResearchData
from monterey.diagnostics import attribution, compliance, exposure, performance
from monterey.ledger import Ledger


def diagnose(ledger: Ledger, data: ResearchData | None = None, benchmarks=("SPUS", "SPY"), write: bool = True) -> dict:
    """Every figure the v1 audit used, computed from the ledger alone (plus benchmark prices)."""
    nav = ledger.nav
    values = ledger.nav_series()
    spec = ledger.spec
    out: dict = {
        "book": spec.id,
        "spec_hash": spec.hash(),
        "rules": spec.summary(),
        "performance": performance.stats(values),
        "yearly": _records(performance.yearly(values).reset_index()),
        "components": attribution.components(nav),
        "benchmarks": {},
        "trading": exposure.trading(nav, ledger.fills),
        "concentration": _records(exposure.concentration(ledger.positions, spec.construction.get("name_cap")).reset_index().rename(columns={"date": "year"})),
        "sectors": {str(k): float(v) for k, v in exposure.sector_mix(ledger.positions).items()},
        "compliance": {
            "excluded_exposure": compliance.excluded_exposure(ledger.positions),
            "breaches": compliance.breach_handling(ledger.events, ledger.positions),
            "purification": compliance.purification(ledger.cashflows),
            "watch_list": compliance.watch_list(
                ledger.positions,
                float(spec.screen.get("watch_band") or 0.02),
                {"debt_ratio": spec.screen["debt"], "cash_ratio": spec.screen["cash"], "receivables_ratio": spec.screen["receivables"]},
            ),
            "delistings": int((ledger.events["type"] == "delisted").sum()) if not ledger.events.empty else 0,
        },
    }
    if data is not None:
        for symbol in benchmarks:
            total = data.total_return(symbol)
            price = data.prices.close.get(symbol)
            if total.empty:
                continue
            aligned = total.reindex(values.index).ffill()
            bench = {
                "performance": performance.stats(aligned),
                "yearly": _records(performance.yearly(aligned).reset_index()),
                "relative": performance.relative(values, aligned),
            }
            if price is not None:
                price = price.dropna()
                bench["selection"] = attribution.selection_vs_bench(nav, price)
                bench["always_invested"] = attribution.always_invested(nav, price)
            bench["switch"] = attribution.switch_cost(nav, total)
            out["benchmarks"][symbol] = bench
    if write and ledger.path is not None:
        (Path(ledger.path) / "diagnostics.json").write_text(json.dumps(out, indent=2, default=_json) + "\n", encoding="utf-8")
    return out


def _records(frame: pd.DataFrame) -> list[dict]:
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def _json(value):
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def pct(value, digits: int = 1, signed: bool = False) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    text = f"{value * 100:+.{digits}f}%" if signed else f"{value * 100:.{digits}f}%"
    return text


def headline_table(diag: dict) -> str:
    """Markdown table: book versus each benchmark."""
    perf = diag["performance"]
    heads = ["", "Book"] + [f"{s} (total return)" for s in diag["benchmarks"]]
    rows = []

    def line(label, key, fmt):
        cells = [label, fmt(perf.get(key))]
        for bench in diag["benchmarks"].values():
            cells.append(fmt(bench["performance"].get(key)))
        rows.append(cells)

    line("Total return", "total_return", lambda v: pct(v, 1, True))
    line("CAGR", "cagr", lambda v: pct(v, 1))
    line("Max drawdown", "max_drawdown", lambda v: pct(v, 1))
    line("Calmar", "calmar", lambda v: "—" if v is None else f"{v:.2f}")
    line("Sharpe", "sharpe", lambda v: "—" if v is None else f"{v:.2f}")
    line("Volatility", "volatility", lambda v: pct(v, 1))
    return _table(heads, rows)


def yearly_table(diag: dict) -> str:
    years = {row["year"]: row for row in diag["yearly"]}
    heads = ["Year", "Book", *diag["benchmarks"].keys(), "Intra-year DD"]
    rows = []
    for year, row in years.items():
        cells = [str(year), pct(row["return"], 1, True)]
        for bench in diag["benchmarks"].values():
            match = {r["year"]: r for r in bench["yearly"]}.get(year)
            cells.append(pct(match["return"], 1, True) if match else "—")
        cells.append(pct(row["intra_year_drawdown"], 1))
        rows.append(cells)
    return _table(heads, rows)


def _table(heads, rows) -> str:
    out = ["| " + " | ".join(heads) + " |", "|" + "|".join(["---"] * len(heads)) + "|"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(out)


def write_audit(diag: dict, path: str | Path, *, title: str | None = None) -> Path:
    """Markdown write-up with the same sections as the v1 book diagnostics."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    title = title or f"Book diagnostics — {diag.get('book', 'book')}"
    lines = [
        f"# {title}",
        "",
        f"**Book.** `{diag.get('book')}`  **hash.** `{diag.get('spec_hash')}`.",
        "",
        "## Rules",
        "",
        "| Layer | Value |",
        "|---|---|",
    ]
    for label, value in diag.get("rules") or []:
        lines.append(f"| {label} | {value} |")
    lines += ["", "## Headline performance", "", headline_table(diag), "", yearly_table(diag), ""]

    def num(value, pattern, fallback="—"):
        return fallback if value is None else pattern.format(value)

    rel = ((diag.get("benchmarks") or {}).get("SPUS") or {}).get("relative") or {}
    if rel:
        beta = num(rel.get("beta"), "{:.2f}")
        te = num(rel.get("tracking_error"), "{:.1%}")
        corr = num(rel.get("correlation"), "{:.2f}")
        lines += [f"Versus SPUS: beta {beta}, tracking error {te}, correlation {corr}.", ""]

    switch = ((diag.get("benchmarks") or {}).get("SPUS") or {}).get("switch") or {}
    if switch:
        lines += [
            "## Switch cost (next-open)",
            "",
            f"- Cuts: {switch.get('cuts')}. Raises: {switch.get('raises')}.",
            f"- Fund return on switch-off days: {pct(switch.get('off_day_loss'), 1, True)}.",
            f"- Benchmark return on switch-on days: {pct(switch.get('on_day_missed'), 1, True)}.",
            f"- Benchmark return while not fully invested: {pct(switch.get('out_of_market'), 1, True)} ({switch.get('days_not_invested')} sessions).",
            "",
        ]
        by_year = switch.get("by_year") or []
        if by_year:
            lines += [
                _table(
                    ["Year", "Cuts", "Off-day hit", "On-day missed", "Days out"],
                    [
                        [str(r["year"]), str(r["cuts"]), pct(r["off_day_loss"], 1, True), pct(r["on_day_missed"], 1, True), str(r["days_not_invested"])]
                        for r in by_year
                    ],
                ),
                "",
            ]

    always = ((diag.get("benchmarks") or {}).get("SPUS") or {}).get("always_invested") or {}
    if always:
        calmar = num(always.get("calmar"), "{:.2f}")
        lines += [
            "## Always-invested counterfactual",
            "",
            f"Total {pct(always.get('total_return'), 1, True)}, CAGR {pct(always.get('cagr'), 1)}, max drawdown {pct(always.get('max_drawdown'), 1)}, Calmar {calmar}.",
            "",
        ]

    sel = ((diag.get("benchmarks") or {}).get("SPUS") or {}).get("selection") or {}
    if sel:
        lines += [
            "## Selection vs SPUS (price, fully invested days)",
            "",
            f"{sel.get('days')} days. Book {pct(sel.get('book'), 1, True)} vs SPUS {pct(sel.get('bench'), 1, True)}.",
            "",
        ]

    parts = diag.get("components") or {}
    if parts:
        lines += [
            "## Return components",
            "",
            f"- Price: {pct(parts.get('price'), 1, True)}",
            f"- Dividends: {pct(parts.get('dividends'), 1, True)}",
            f"- Costs: {pct(parts.get('costs'), 1, True)}",
            f"- Purification: {pct(parts.get('purification'), 1, True)}",
            "",
        ]

    trade = diag.get("trading") or {}
    if trade:
        turn = num(trade.get("annual_turnover"), "{:.2f}")
        switch_share = num(trade.get("switch_share"), "{:.1%}")
        small = num(trade.get("small_fill_share"), "{:.1%}")
        lines += [
            "## Turnover and churn",
            "",
            f"- Annual one-way turnover: {turn}.",
            f"- Traded notional: ${trade.get('traded_notional', 0):,.0f}. Costs: ${trade.get('costs', 0):,.0f}.",
            f"- Share of notional on switch fills: {switch_share}.",
            f"- Fills: {trade.get('fills')}. Median fills/day: {trade.get('median_fills_per_day')}. Share under $2k: {small}.",
            "",
        ]

    conc = diag.get("concentration") or []
    if conc:
        lines += [
            "## Concentration",
            "",
            _table(
                ["Year", "Names", "Top-5", "Top-10", "At cap", "Effective names"],
                [
                    [
                        str(int(r.get("year") or r.get("index") or 0)),
                        f"{r.get('names', 0):.0f}",
                        pct(r.get("top5"), 1),
                        pct(r.get("top10"), 1),
                        f"{r.get('capped', 0):.1f}",
                        f"{r.get('effective_names', 0):.1f}",
                    ]
                    for r in conc
                ],
            ),
            "",
        ]

    sectors = diag.get("sectors") or {}
    if sectors:
        lines += ["## Sectors (last session)", ""]
        for name, weight in sectors.items():
            lines.append(f"- {name}: {pct(weight, 1)}")
        lines.append("")

    comp = diag.get("compliance") or {}
    excl = comp.get("excluded_exposure") or {}
    breaches = comp.get("breaches") or {}
    pur = comp.get("purification") or {}
    names = ", ".join(excl.get("names") or []) or "none"
    lines += [
        "## Compliance",
        "",
        f"- Sessions holding an excluded-sector name: {excl.get('sessions', 0)}. Names: {names}.",
        f"- Latest excluded weight: {pct(excl.get('latest_weight'), 2)}.",
        f"- Breach events: {breaches.get('events', 0)} across {breaches.get('names', 0)} names. Still held 5 sessions later: {breaches.get('still_held', 0)}.",
        f"- Dividends credited: ${pur.get('dividends', 0):,.0f}. Purification: ${pur.get('purification', 0):,.0f} ({pur.get('posts', 0)} posts).",
        f"- Delistings: {comp.get('delistings', 0)}.",
        "",
    ]
    for row in comp.get("watch_list") or []:
        lines.append(f"- {row['symbol']} {row['ratio']} {row['value']:.1%} vs {row['line']:.0%} (gap {row['gap']:.1%})")
    if comp.get("watch_list"):
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
