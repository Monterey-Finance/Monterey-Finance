"""Monterey desk. A dense paper-fund terminal. It only reads the ledger."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Input, Static, TabbedContent, TabPane
from rich.text import Text

from desk.model import Desk, Holding, load_desk

BG = "#101114"
INK = "#d5dbe3"
MUTED = "#8b939e"
GREEN = "#3ecf8e"
RED = "#e15d64"
BLUE = "#6aa7ff"
LINE = "#2a3038"


def _text(value: str, style: str = INK) -> Text:
    return Text(value, style=style)


def _pct(value: float | None, signed: bool = False, digits: int = 2) -> str:
    if value is None:
        return "—"
    number = value * 100
    if signed:
        return f"{number:+.{digits}f}"
    return f"{number:.{digits}f}"


def _money(value: float | None, signed: bool = False) -> str:
    if value is None:
        return "—"
    if signed:
        return f"{value:+,.2f}"
    return f"{value:,.2f}"


def _px(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.2f}"


def _shares(value: float) -> str:
    if value <= 0:
        return "—"
    return f"{value:,.0f}"


def _cap(value: float | None) -> str:
    if value is None:
        return "—"
    if abs(value) >= 1e12:
        return f"{value / 1e12:.2f}T"
    if abs(value) >= 1e9:
        return f"{value / 1e9:.1f}B"
    if abs(value) >= 1e6:
        return f"{value / 1e6:.1f}M"
    return f"{value:,.0f}"


def _tone_pct(value: float | None, signed: bool = False) -> Text:
    if value is None:
        return _text("—", MUTED)
    style = GREEN if value > 1e-12 else RED if value < -1e-12 else MUTED
    return _text(_pct(value, signed=signed), style)


def _screen(label: str) -> Text:
    if label == "PASS":
        return _text("PASS", GREEN)
    if label == "REVIEW":
        return _text("REVIEW", RED)
    return _text(label, MUTED)


def _bar(weight: float, cap: float, width: int = 18) -> Text:
    scale = cap if cap > 0 else 0.10
    filled = int(round(min(max(weight, 0.0) / scale, 1.0) * width))
    style = BLUE if weight >= scale - 1e-9 else GREEN
    return Text("█" * filled + "░" * (width - filled), style=style)


def _meter(value: float | None, line: float, width: int = 14) -> Text:
    if value is None or line <= 0:
        return _text("—", MUTED)
    filled = int(round(min(value / line, 1.0) * width))
    style = RED if value >= line else BLUE if line - value <= 0.02 else GREEN
    return Text(f"{'█' * filled}{'░' * (width - filled)}  {value * 100:.1f}", style=style)


class Panel(Vertical):
    """A bordered section. The title sits on the top edge."""

    def __init__(self, title: str, **kwargs) -> None:
        classes = f"{kwargs.pop('classes', '')} panel".strip()
        super().__init__(classes=classes, **kwargs)
        self.border_title = title


class Performance(Static):
    """Fund figures for the Book tab. Holdings stay in the table beside this."""

    def render(self) -> Text:
        desk: Desk | None = getattr(self.app, "desk", None)
        if desk is None or desk.nav is None:
            return _text("NAV prints after the first session.", MUTED)
        since = None
        if desk.starting_cash:
            since = desk.nav / desk.starting_cash - 1.0
        report = desk.health or {}
        needed = int(report.get("sessions_required") or 20)
        have = int(report.get("n_sessions") or len(desk.nav_points))
        short = max(needed - have, 0)

        def metric(value, kind: str) -> Text:
            if value is None:
                note = f"—   {short} sessions short" if short else "—"
                return _text(note, MUTED)
            if kind == "pct":
                return _tone_pct(float(value), signed=True)
            return _text(f"{float(value):.2f}", INK)

        day_style = GREEN if (desk.daily_return or 0) > 0 else RED if (desk.daily_return or 0) < 0 else MUTED
        sma = "On" if desk.sma_on else "Cash" if desk.sma_on is False else "—"
        sma_style = GREEN if desk.sma_on else RED if desk.sma_on is False else MUTED
        invested_pct = desk.invested / max(desk.invested + desk.cash, 1.0)
        left = [
            ("Day", _tone_pct(desk.daily_return, signed=True)),
            ("Since start", _tone_pct(since, signed=True)),
            ("Sessions", _text(str(have), INK)),
            ("Max drawdown", metric(report.get("max_drawdown"), "pct")),
            ("Sharpe", metric(report.get("sharpe"), "num")),
            ("Sortino", metric(report.get("sortino"), "num")),
            ("Beta SPUS", metric(report.get("beta_spus"), "num")),
            ("Beta SPY", metric(report.get("beta_spy"), "num")),
            ("Tracking error", metric(report.get("tracking_error_spus"), "num")),
            ("Alpha", metric(report.get("alpha_spus"), "num")),
            ("VaR 95", metric(report.get("var_95"), "num")),
            ("CVaR 95", metric(report.get("cvar_95"), "num")),
        ]
        right = [
            ("Cash", _text(_money(desk.cash), INK)),
            ("Invested", _text(_money(desk.invested), INK)),
            ("Invested %", _text(_pct(invested_pct, digits=1), GREEN)),
            ("Names", _text(str(desk.n_positions), INK)),
            ("SMA", _text(sma, sma_style)),
            ("Kill switch", _text("Halted" if desk.halted else "Clear", RED if desk.halted else GREEN)),
            ("Purify today", _text(_money(desk.purification_today), INK)),
            ("Purify life", _text(_money(desk.purification_cumulative), INK)),
            ("Name cap", _text(f"{desk.name_cap:.0%}", BLUE)),
            ("Cash weight", _text(_pct(desk.cash_weight, digits=1), MUTED)),
            ("Last fill", _text(desk.fill_basis or "—", BLUE)),
            ("Book", _text(desk.book_version or "1b", MUTED)),
        ]
        lines = [
            Text.assemble(("NAV", MUTED)),
            Text(f"{desk.nav:,.2f}", style=INK),
            Text.assemble(("Day ", MUTED), (_pct(desk.daily_return, signed=True), day_style), ("    Since start ", MUTED), (_pct(since, signed=True), GREEN if (since or 0) > 0 else RED if (since or 0) < 0 else MUTED)),
            Text(""),
            Text.assemble(("RETURN", GREEN), (" " * 22), ("BOOK", BLUE)),
        ]
        for (left_label, left_value), (right_label, right_value) in zip(left, right):
            lines.append(
                Text.assemble(
                    (f"{left_label:<16}", MUTED),
                    left_value,
                    " " * 4,
                    (f"{right_label:<14}", MUTED),
                    right_value,
                )
            )
        reason = desk.halt_reason or desk.sma_reason or desk.reconcile_reason
        if reason:
            lines.append(Text(""))
            lines.append(Text(reason, style=RED if desk.halted else MUTED))
        holding = desk.holding(getattr(self.app, "_symbol", "")) if getattr(self.app, "_symbol", "") else None
        if holding is not None:
            lines.extend(
                [
                    Text(""),
                    Text.assemble(("HOLDING", MUTED), "  ", (holding.symbol, INK), "  ", _screen(holding.screen)),
                    Text.assemble(
                        ("Shares ", MUTED),
                        (_shares(holding.shares), INK),
                        ("    Value ", MUTED),
                        (_money(holding.market_value), INK),
                        ("    Last ", MUTED),
                        (_px(holding.price), MUTED),
                    ),
                    Text.assemble(
                        ("Target ", MUTED),
                        (_pct(holding.target_weight), INK),
                        ("    Actual ", MUTED),
                        _tone_pct(holding.actual_weight),
                        ("    Drift ", MUTED),
                        _tone_pct(holding.drift, signed=True),
                        "    ",
                        (_text("CAP", BLUE) if holding.name_capped else _text("under cap", MUTED)),
                    ),
                    Text.assemble(("Debt 30  ", MUTED), _meter(holding.debt_ratio, 0.30, 18)),
                    Text.assemble(("Cash 30  ", MUTED), _meter(holding.cash_ratio, 0.30, 18)),
                    Text.assemble(("Recv 70  ", MUTED), _meter(holding.receivables_ratio, 0.70, 18)),
                    Text.assemble(
                        ("FCF ", MUTED),
                        (_pct(holding.fcf_margin, digits=1), INK),
                        ("    Market cap ", MUTED),
                        (_cap(holding.market_cap), MUTED),
                    ),
                ]
            )
        window = report.get("window")
        if window:
            lines.append(Text(""))
            lines.append(Text(f"Risk window  {window}", style=MUTED))
        return Text("\n").join(lines)


class SessionList(Static):
    """One compact box per day produced by python -m ops run."""

    def render(self) -> Text:
        desk: Desk | None = getattr(self.app, "desk", None)
        width = max((self.size.width or 48) - 2, 36)
        if desk is None or not desk.sessions:
            return _text("No day yet. Run python -m ops run --as-of today.", MUTED)
        blocks: list[Text] = []
        for index, session in enumerate(desk.sessions):
            if index:
                blocks.append(Text(""))
            blocks.extend(_session_box(session, width))
        return Text("\n").join(blocks)


def _session_box(session: dict, width: int) -> list[Text]:
    day = str(session.get("as_of") or "")
    nav = session.get("nav")
    nav_text = "—" if nav is None else f"{float(nav):,.2f}"
    change = _tone_pct(session.get("daily_return"), signed=True)
    halted = bool(session.get("halted"))
    state = "Halted" if halted else "Clear"
    state_style = RED if halted else GREEN
    sma_on = session.get("sma_on")
    sma = "SMA on" if sma_on else "SMA cash" if sma_on is False else "SMA"
    sma_style = GREEN if sma_on else RED if sma_on is False else MUTED
    inner = max(width - 2, 24)
    title = f" {day} "
    dash = max(inner - len(title), 0)
    top = Text.assemble(("┌", MUTED), (title, INK), ("─" * dash, MUTED), ("┐", MUTED))
    nav_line = Text.assemble(
        ("│ ", MUTED),
        ("NAV ", MUTED),
        (nav_text, INK),
        ("   Day ", MUTED),
        change,
        "   ",
        (f"{int(session.get('n_positions') or 0)} names", INK),
    )
    nav_line.pad_right(max(width - nav_line.cell_len - 1, 0))
    nav_line.append("│", style=MUTED)
    ops = Text.assemble(
        ("│ ", MUTED),
        (_fill_label(str(session.get("fill_basis") or "")), BLUE),
        "   ",
        (sma, sma_style),
        "   ",
        (state, state_style),
        "   ",
        (f"{int(session.get('n_fills') or 0)} fills", INK),
    )
    if int(session.get("n_pending") or 0):
        ops.append(f"   {int(session['n_pending'])} waiting", style=BLUE)
    ops.append(f"   purify {_money(session.get('purification_today'))}", style=MUTED)
    ops.pad_right(max(width - ops.cell_len - 1, 0))
    ops.append("│", style=MUTED)
    note = session.get("halt_reason") or session.get("sma_reason") or ""
    if session.get("n_filing_fails"):
        note = f"{int(session['n_filing_fails'])} filing fails. {note}".strip()
    note = str(note)
    if len(note) > inner - 1:
        note = note[: inner - 2] + "…"
    note_line = Text.assemble(("│ ", MUTED), (note or "—", MUTED if not halted else RED))
    note_line.pad_right(max(width - note_line.cell_len - 1, 0))
    note_line.append("│", style=MUTED)
    bottom = Text("└" + "─" * inner + "┘", style=MUTED)
    return [top, nav_line, ops, note_line, bottom]


def _fill_label(basis: str) -> str:
    labels = {
        "close_bootstrap": "Bought at the close",
        "next_open": "Filled at the open",
        "queued_next_open": "Queued for the next open",
        "already_marked": "Already marked",
        "submitted_opg": "Sent for the open",
        "draft": "Draft only",
        "halted": "Halted",
        "no_orders": "No orders",
        "broker_sync": "Synced from the broker",
        "rejected": "Rejected",
    }
    return labels.get(basis, basis.replace("_", " ") if basis else "No fill")


class DiagnosticsView(Static):
    """Attribution, switch cost, concentration, and compliance from diagnostics.json."""

    def render(self) -> Text:
        desk: Desk | None = getattr(self.app, "desk", None)
        diag = getattr(desk, "diagnostics", None) or {}
        if not diag:
            return _text("No diagnostics.json on this ledger yet.", MUTED)
        lines: list[Text] = []
        perf = diag.get("performance") or {}
        lines.append(_text(f"{diag.get('book')}  {diag.get('spec_hash')}", INK))
        lines.append(Text.assemble(
            ("CAGR ", MUTED), _tone_pct(perf.get("cagr"), signed=True),
            ("   MaxDD ", MUTED), _tone_pct(perf.get("max_drawdown"), signed=True),
            ("   Calmar ", MUTED), _text(f"{perf.get('calmar'):.2f}" if perf.get("calmar") is not None else "—"),
        ))
        parts = diag.get("components") or {}
        if parts:
            lines.append(Text.assemble(
                ("Price ", MUTED), _tone_pct(parts.get("price"), signed=True),
                ("  Div ", MUTED), _tone_pct(parts.get("dividends"), signed=True),
                ("  Cost ", MUTED), _tone_pct(parts.get("costs"), signed=True),
                ("  Purify ", MUTED), _tone_pct(parts.get("purification"), signed=True),
            ))
        switch = ((diag.get("benchmarks") or {}).get("SPUS") or {}).get("switch") or {}
        if switch:
            lines.append(Text.assemble(
                ("Switch cuts ", MUTED), _text(str(switch.get("cuts"))),
                ("  off-day ", MUTED), _tone_pct(switch.get("off_day_loss"), signed=True),
                ("  on-day missed ", MUTED), _tone_pct(switch.get("on_day_missed"), signed=True),
            ))
        excl = ((diag.get("compliance") or {}).get("excluded_exposure") or {})
        lines.append(Text.assemble(
            ("Excluded-sector sessions ", MUTED),
            _text(str(excl.get("sessions", 0)), RED if excl.get("sessions") else GREEN),
            ("  names ", MUTED),
            _text(", ".join(excl.get("names") or []) or "none"),
        ))
        sectors = diag.get("sectors") or {}
        if sectors:
            top = list(sectors.items())[:6]
            lines.append(_text("  ".join(f"{name} {value*100:.0f}%" for name, value in top), MUTED))
        return Text("\n").join(lines)


class CompareView(Static):
    """Overlay two ledger NAV paths and a few headline figures."""

    def render(self) -> Text:
        desk: Desk | None = getattr(self.app, "desk", None)
        other: Desk | None = getattr(self.app, "compare", None)
        if desk is None or desk.nav is None:
            return _text("Load a ledger to compare.", MUTED)
        if other is None or other.nav is None:
            return _text("No second ledger. Archive v1 or run an experiment.", MUTED)
        lines = [
            Text.assemble((_text(getattr(desk, "ledger_name", "A") or "A", GREEN)), (" vs ", MUTED), (_text(getattr(other, "ledger_name", "B") or "B", BLUE))),
            Text.assemble(("NAV  ", MUTED), _text(_money(desk.nav), GREEN), ("   ", MUTED), _text(_money(other.nav), BLUE)),
            Text.assemble(("Since start  ", MUTED), _tone_pct((desk.nav / (desk.starting_cash or desk.nav)) - 1 if desk.starting_cash else None, signed=True), ("   ", MUTED), _tone_pct((other.nav / (other.starting_cash or other.nav)) - 1 if other.starting_cash else None, signed=True)),
            Text.assemble(("Max DD  ", MUTED), _tone_pct((desk.health or {}).get("max_drawdown"), signed=True), ("   ", MUTED), _tone_pct((other.health or {}).get("max_drawdown"), signed=True)),
            Text.assemble(("Sharpe  ", MUTED), _text(f"{(desk.health or {}).get('sharpe') or 0:.2f}"), ("   ", MUTED), _text(f"{(other.health or {}).get('sharpe') or 0:.2f}", BLUE)),
        ]
        return Text("\n").join(lines)


class Tape(Static):
    """Two full-width status lines. Numbers use the width of the terminal."""

    def render(self) -> Text:
        desk: Desk | None = getattr(self.app, "desk", None)
        width = max(self.size.width, 40)
        if desk is None:
            return _text("MONTEREY  loading ledger", MUTED)
        nav = "—" if desk.nav is None else f"{desk.nav:,.2f}"
        day = _pct(desk.daily_return, signed=True)
        day_style = GREEN if (desk.daily_return or 0) > 0 else RED if (desk.daily_return or 0) < 0 else MUTED
        state = "HALT" if desk.halted else "CLEAR"
        state_style = RED if desk.halted else GREEN
        sma = "SMA ON" if desk.sma_on else "SMA CASH" if desk.sma_on is False else "SMA"
        sma_style = GREEN if desk.sma_on else RED if desk.sma_on is False else MUTED
        line = Text.assemble(
            ("MONTEREY", GREEN),
            (" · ", MUTED),
            ("PAPER", BLUE),
            (" · ", MUTED),
            (desk.as_of or "NO SESSION", INK),
            (" · ", MUTED),
            (desk.book_version or "1b", MUTED),
            (" · NAV ", MUTED),
            (nav, INK),
            (" · DAY ", MUTED),
            (day, day_style),
            (" · CASH ", MUTED),
            (f"{desk.cash:,.2f}", INK),
            (" · INVESTED ", MUTED),
            (f"{desk.invested:,.2f}", INK),
            (f" · {desk.n_positions} NAMES", INK),
        )
        total = max(desk.invested + desk.cash, 1.0)
        invested_pct = desk.invested / total * 100
        flags = Text.assemble(
            (sma, sma_style),
            (" · ", MUTED),
            (state, state_style),
            (" · ", MUTED),
            (desk.venue.upper(), BLUE),
            (" · ", MUTED),
            (f"{invested_pct:.1f}%", INK),
        )
        bar_width = max(8, width - flags.cell_len - 1)
        invested_cells = min(bar_width, max(0, int(round(desk.invested / total * bar_width))))
        bar = Text.assemble(
            ("█" * invested_cells, GREEN),
            ("░" * (bar_width - invested_cells), MUTED),
            " ",
            flags,
        )
        return Text("\n").join([line, bar])


class DeskApp(App):
    """Read-only monitor for the shadow fund."""

    TITLE = "Monterey"
    ENABLE_COMMAND_PALETTE = False
    CSS = f"""
    Screen {{
        background: {BG};
        color: {INK};
    }}
    #tape {{
        height: 2;
        background: {BG};
        color: {INK};
        padding: 0 1;
    }}
    TabbedContent {{
        height: 1fr;
        background: {BG};
    }}
    ContentSwitcher {{
        height: 1fr;
    }}
    TabPane {{
        height: 1fr;
        background: {BG};
        padding: 0;
    }}
    Tabs {{
        background: {BG};
    }}
    Tab {{
        background: {BG};
        color: {MUTED};
        padding: 0 2;
    }}
    Tab.-active {{
        color: {INK};
        text-style: bold;
        background: {BG};
    }}
    Underline > .underline--bar {{
        color: {GREEN};
        background: {LINE};
    }}
    Horizontal, Vertical {{
        height: 1fr;
        background: {BG};
    }}
    .panel {{
        border: solid #3a414c;
        border-title-color: {MUTED};
        border-title-background: {BG};
        border-title-align: left;
        height: 1fr;
        width: 1fr;
        background: {BG};
        padding: 0 1;
    }}
    #book-main {{
        width: 1fr;
        height: 1fr;
    }}
    #perf-panel {{
        height: auto;
        max-height: 34;
    }}
    #runs-panel {{
        height: 1fr;
        min-height: 8;
    }}
    #holdings-panel {{
        width: 1fr;
    }}
    #perf {{
        height: auto;
        width: 1fr;
        padding: 1 1 0 1;
    }}
    #runs {{
        height: 1fr;
        width: 1fr;
        padding: 0 1;
    }}
    #health-table, #rules-table {{
        height: 1fr;
        max-height: 14;
    }}
    #status-table, #limits-table {{
        height: 1fr;
    }}
    DataTable {{
        height: 1fr;
        width: 1fr;
        background: {BG};
        color: {INK};
    }}
    DataTable > .datatable--header {{
        background: #181b20;
        color: {MUTED};
        text-style: bold;
    }}
    DataTable > .datatable--cursor {{
        background: #163028;
        color: #f2f5f8;
    }}
    DataTable > .datatable--even-row {{
        background: #14171c;
    }}
    #facts {{
        height: 16;
        min-height: 10;
    }}
    #bars {{
        height: 1fr;
    }}
    #grid {{
        height: 1fr;
    }}
    #foot {{
        height: 1;
        background: #181b20;
    }}
    #find {{
        width: 22;
        height: 1;
        border: none;
        background: #181b20;
        color: {INK};
        padding: 0 1;
    }}
    #find:focus {{
        border: none;
    }}
    #keys {{
        width: 1fr;
        height: 1;
        background: #181b20;
        color: {MUTED};
        content-align: right middle;
        padding: 0 1;
    }}
    """
    BINDINGS = [
        Binding("1", "show('book')", "Book", show=False),
        Binding("2", "show('weights')", "Weights", show=False),
        Binding("3", "show('orders')", "Orders", show=False),
        Binding("4", "show('ledger')", "Ledger", show=False),
        Binding("5", "show('system')", "System", show=False),
        Binding("6", "show('diagnostics')", "Diagnostics", show=False),
        Binding("7", "show('compare')", "Compare", show=False),
        Binding("left_square_bracket", "prev_ledger", "Prev ledger", show=False),
        Binding("right_square_bracket", "next_ledger", "Next ledger", show=False),
        Binding("slash", "focus_find", "Find", show=False),
        Binding("r", "reload", "Reload"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, desk: Desk | None = None, state=None, runs=None) -> None:
        super().__init__()
        self._state = state
        self._runs = runs
        self.desk = desk
        self.compare = None
        self._ledgers: list = []
        self._ledger_i = 0
        self._query = ""
        self._symbol = ""
        self._mute = False

    def compose(self) -> ComposeResult:
        yield Tape(id="tape")
        with TabbedContent(id="tabs"):
            with TabPane("Book", id="book"):
                with Horizontal():
                    with Vertical(id="book-main"):
                        with Panel("Performance", id="perf-panel"):
                            yield Performance(id="perf")
                        with Panel("Daily runs", id="runs-panel"):
                            yield SessionList(id="runs")
                    with Panel("Holdings", id="holdings-panel"):
                        yield DataTable(id="book-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Weights", id="weights"):
                with Panel("Target weights"):
                    yield DataTable(id="weights-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Orders", id="orders"):
                with Vertical():
                    with Panel("Gap to the book"):
                        yield DataTable(id="orders-table", cursor_type="row", zebra_stripes=True)
                    with Panel("Fills"):
                        yield DataTable(id="fills-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Ledger", id="ledger"):
                with Horizontal():
                    with Panel("Activity"):
                        yield DataTable(id="activity-table", cursor_type="row", zebra_stripes=True)
                    with Panel("Halal lines"):
                        yield DataTable(id="ratio-table", cursor_type="row", zebra_stripes=True)
                    with Panel("Cash path"):
                        yield DataTable(id="cash-table", cursor_type="row", zebra_stripes=True)
            with TabPane("System", id="system"):
                with Horizontal(id="grid"):
                    with Vertical():
                        with Panel("Risk"):
                            yield DataTable(id="health-table", show_cursor=False, zebra_stripes=True)
                        with Panel("Session"):
                            yield DataTable(id="status-table", show_cursor=False, zebra_stripes=True)
                    with Vertical():
                        with Panel("Rules"):
                            yield DataTable(id="rules-table", show_cursor=False, zebra_stripes=True)
                        with Panel("Distance to the line"):
                            yield DataTable(id="limits-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Diagnostics", id="diagnostics"):
                with Panel("Diagnostics"):
                    yield DiagnosticsView(id="diag-view")
            with TabPane("Compare", id="compare"):
                with Panel("Compare ledgers"):
                    yield CompareView(id="compare-view")
        with Horizontal(id="foot"):
            yield Input(placeholder="find symbol", id="find")
            yield Static("1 book  2 weights  3 orders  4 ledger  5 system  6 diag  7 compare   [ ] ledger   / find   r reload   q quit", id="keys")

    def on_mount(self) -> None:
        if self.desk is None:
            self.desk = load_desk(self._state, self._runs)
        self._refresh_ledger_list()
        for table in self.query(DataTable):
            table.cell_padding = 1
            table.fixed_columns = 1
        self._fill()
        self.query_one("#book-table", DataTable).focus()

    def action_show(self, tab: str) -> None:
        self.query_one(TabbedContent).active = tab

    def action_focus_find(self) -> None:
        self.query_one("#find", Input).focus()

    def action_reload(self) -> None:
        self.desk = load_desk(self._state, self._runs, ledger=getattr(self.desk, "source", None) if self.desk and str(self.desk.source).endswith(tuple("0123456789abcdef")) else None)
        self._refresh_ledger_list()
        self._fill()
        self.query_one("#tape", Tape).refresh()

    def action_next_ledger(self) -> None:
        self._shift_ledger(1)

    def action_prev_ledger(self) -> None:
        self._shift_ledger(-1)

    def _refresh_ledger_list(self) -> None:
        try:
            from monterey.ledger import list_ledgers

            self._ledgers = list_ledgers()
        except Exception:
            self._ledgers = []
        if len(self._ledgers) >= 2:
            try:
                self.compare = load_desk(ledger=self._ledgers[1]["path"])
            except Exception:
                self.compare = None

    def _shift_ledger(self, delta: int) -> None:
        if not self._ledgers:
            self._refresh_ledger_list()
        if not self._ledgers:
            return
        self._ledger_i = (self._ledger_i + delta) % len(self._ledgers)
        self.desk = load_desk(ledger=self._ledgers[self._ledger_i]["path"])
        self._fill()
        self.query_one("#tape", Tape).refresh()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "find":
            return
        self._query = event.value.strip()
        self._fill()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if self._mute or event.data_table.id not in {"book-table", "weights-table"}:
            return
        symbol = str(event.row_key.value)
        if symbol and symbol != self._symbol:
            self._symbol = symbol
            self.query_one("#perf", Performance).refresh()

    def _rows(self) -> list[Holding]:
        assert self.desk is not None
        return [row for row in self.desk.holdings if self.desk.matches(row.symbol, self._query)]

    def _fill(self) -> None:
        self._mute = True
        try:
            self._fill_book()
            self._fill_weights()
            self._fill_orders()
            self._fill_ledger()
            self._fill_system()
            rows = self._rows()
            if rows and (not self._symbol or self.desk.holding(self._symbol) is None or not self.desk.matches(self._symbol, self._query)):
                self._symbol = rows[0].symbol
        finally:
            self._mute = False
        self.query_one("#tape", Tape).refresh()
        self.query_one("#perf", Performance).refresh()
        self.query_one("#runs", SessionList).refresh()
        try:
            self.query_one("#diag-view", DiagnosticsView).refresh()
            self.query_one("#compare-view", CompareView).refresh()
        except Exception:
            pass

    def _fill_book(self) -> None:
        table = self.query_one("#book-table", DataTable)
        _columns(
            table,
            [
                ("SYM", 8),
                ("WGT", 8),
                ("ACT", 8),
                ("VALUE", 12),
                ("SH", 6),
                ("DRIFT", 7),
                ("SCREEN", 7),
                ("CAP", 4),
            ],
        )
        for row in self._rows():
            table.add_row(
                _text(row.symbol, INK),
                _text(_pct(row.target_weight), INK),
                _tone_pct(row.actual_weight),
                _text(_money(row.market_value), INK),
                _text(_shares(row.shares), INK),
                _tone_pct(row.drift, signed=True),
                _screen(row.screen),
                _text("CAP", BLUE) if row.name_capped else _text("·", MUTED),
                key=row.symbol,
            )

    def _fill_weights(self) -> None:
        table = self.query_one("#weights-table", DataTable)
        desk = self.desk
        assert desk is not None
        _columns(
            table,
            [
                ("SYM", 8),
                ("TARGET", 8),
                ("INVESTED", 10),
                ("ACTUAL", 8),
                ("DRIFT", 8),
                ("$ DRIFT", 12),
                ("COST", 10),
                ("CAP", 6),
                ("ROOM", 8),
                ("FCF", 8),
                ("MKT CAP", 10),
                ("BAR", 20),
            ],
        )
        nav = desk.nav or 0.0
        for row in self._rows():
            drift_dollars = None if row.drift is None else row.drift * nav
            cost = None if drift_dollars is None else abs(drift_dollars) * 10 / 10_000
            room = desk.name_cap - row.target_weight
            table.add_row(
                _text(row.symbol),
                _text(_pct(row.target_weight)),
                _text(_pct(row.invested_weight), MUTED),
                _tone_pct(row.actual_weight),
                _tone_pct(row.drift, signed=True),
                _text(_money(drift_dollars, signed=True), BLUE if drift_dollars and abs(drift_dollars) >= 100 else MUTED),
                _text(_money(cost), MUTED),
                _text("CAP", BLUE) if row.name_capped else _text("·", MUTED),
                _text(_pct(room), MUTED),
                _text(_pct(row.fcf_margin, digits=1), INK),
                _text(_cap(row.market_cap), MUTED),
                _bar(row.target_weight, desk.name_cap, 16),
                key=row.symbol,
            )

    def _fill_orders(self) -> None:
        desk = self.desk
        assert desk is not None
        orders = self.query_one("#orders-table", DataTable)
        fills = self.query_one("#fills-table", DataTable)
        _columns(
            orders,
            [
                ("SYM", 8),
                ("SIDE", 6),
                ("TARGET", 8),
                ("ACTUAL", 8),
                ("DRIFT", 8),
                ("NOTIONAL", 14),
                ("COST 10BP", 12),
                ("REASON", 16),
                ("STATUS", 10),
            ],
        )
        nav = desk.nav or 0.0
        pending = {str(row.get("symbol")): row for row in desk.pending}
        for row in self._rows():
            dollars = 0.0 if row.drift is None else row.drift * nav
            if row.symbol in pending:
                side = str(pending[row.symbol].get("side") or "buy").upper()
                status = "QUEUED"
                reason = str(pending[row.symbol].get("reason") or "pending")
            elif abs(dollars) < 100:
                side = "FLAT"
                status = "IN BOOK"
                reason = "dust" if row.drift else "matched"
            elif dollars > 0:
                side = "BUY"
                status = "GAP"
                reason = "rebalance"
            else:
                side = "SELL"
                status = "GAP"
                reason = "exit" if row.target_weight <= 0 else "rebalance"
            side_style = GREEN if side == "BUY" else RED if side == "SELL" else MUTED
            orders.add_row(
                _text(row.symbol),
                _text(side, side_style),
                _text(_pct(row.target_weight)),
                _tone_pct(row.actual_weight),
                _tone_pct(row.drift, signed=True),
                _text(_money(dollars, signed=True)),
                _text(_money(abs(dollars) * 0.001)),
                _text(reason, MUTED),
                _text(status, BLUE if status == "QUEUED" else INK),
                key=row.symbol,
            )
        _columns(
            fills,
            [
                ("DATE", 12),
                ("SYM", 8),
                ("SIDE", 6),
                ("SH", 8),
                ("PX", 12),
                ("AMOUNT", 14),
                ("STATUS", 10),
                ("WHY", 14),
            ],
        )
        for fill in reversed(desk.fills):
            if self._query and self._query.upper() not in str(fill.get("symbol") or "").upper():
                continue
            price = float(fill.get("price") or 0)
            shares = float(fill.get("shares") or 0)
            amount = shares * price
            side = str(fill.get("side") or "")
            fills.add_row(
                _text(str(fill.get("as_of") or "")[:10], MUTED),
                _text(str(fill.get("symbol") or "")),
                _text(side.upper(), GREEN if side == "buy" else RED),
                _text(f"{shares:,.0f}"),
                _text(_px(price), MUTED),
                _text(_money(-amount if side == "buy" else amount, signed=True)),
                _text(str(fill.get("status") or ""), BLUE),
                _text(str(fill.get("reason") or fill.get("detail") or ""), MUTED),
            )

    def _fill_ledger(self) -> None:
        desk = self.desk
        assert desk is not None
        activity = self.query_one("#activity-table", DataTable)
        ratios = self.query_one("#ratio-table", DataTable)
        cash = self.query_one("#cash-table", DataTable)
        _columns(activity, [("WHEN", 12), ("TYPE", 12), ("SYM", 8), ("AMOUNT", 14), ("DETAIL", 22)])
        source = desk.activity or [
            {
                "as_of": fill.get("as_of"),
                "type": "fill",
                "symbol": fill.get("symbol"),
                "amount": (float(fill.get("shares") or 0) * float(fill.get("price") or 0))
                * (-1 if fill.get("side") == "buy" else 1),
                "detail": fill.get("side"),
            }
            for fill in desk.fills
        ]
        for row in reversed(source):
            symbol = str(row.get("symbol") or "")
            if self._query and self._query.upper() not in symbol.upper() and symbol:
                continue
            activity.add_row(
                _text(str(row.get("as_of") or "")[:10], MUTED),
                _text(str(row.get("type") or ""), BLUE),
                _text(symbol),
                _text(_money(_num(row.get("amount")), signed=True)),
                _text(str(row.get("detail") or ""), MUTED),
            )
        _columns(ratios, [("SYM", 8), ("LINE", 8), ("GAP", 8), ("DEBT", 8), ("CASH", 8), ("RECV", 8), ("SCREEN", 8)])
        ordered = sorted(self._rows(), key=lambda row: row.nearest_gap if row.nearest_gap is not None else 99)
        for row in ordered:
            gap_style = RED if row.nearest_gap is not None and row.nearest_gap < 0 else BLUE if row.nearest_gap is not None and row.nearest_gap <= 0.02 else GREEN
            ratios.add_row(
                _text(row.symbol),
                _text(row.nearest_name or "—", MUTED),
                _text(_pct(row.nearest_gap, signed=True), gap_style),
                _text(_pct(row.debt_ratio, digits=1)),
                _text(_pct(row.cash_ratio, digits=1)),
                _text(_pct(row.receivables_ratio, digits=1)),
                _screen(row.screen),
                key=row.symbol,
            )
        _columns(cash, [("STEP", 12), ("SYM", 8), ("SIDE", 6), ("AMOUNT", 14), ("CASH", 14)])
        for row in desk.cash_path:
            symbol = str(row.get("symbol") or "")
            if self._query and symbol and self._query.upper() not in symbol.upper():
                continue
            side = str(row.get("side") or "")
            cash.add_row(
                _text(str(row.get("step") or ""), MUTED),
                _text(symbol or "·"),
                _text(side.upper(), GREEN if side == "buy" else RED if side in {"sell", "gap"} else MUTED),
                _text(_money(_num(row.get("amount")), signed=True)),
                _text(_money(_num(row.get("cash")))),
            )

    def _fill_system(self) -> None:
        desk = self.desk
        assert desk is not None
        health = self.query_one("#health-table", DataTable)
        status = self.query_one("#status-table", DataTable)
        rules = self.query_one("#rules-table", DataTable)
        limits = self.query_one("#limits-table", DataTable)
        _columns(health, [("METRIC", 18), ("VALUE", 14), ("WINDOW", 28)])
        report = desk.health or {}
        needed = int(report.get("sessions_required") or 20)
        have = int(report.get("n_sessions") or 0)
        short = max(needed - have, 0)
        note = report.get("window") or "no NAV"
        for label, key in (
            ("sessions", "n_sessions"),
            ("max drawdown", "max_drawdown"),
            ("sharpe", "sharpe"),
            ("sortino", "sortino"),
            ("beta SPUS", "beta_spus"),
            ("beta SPY", "beta_spy"),
            ("tracking error", "tracking_error_spus"),
            ("alpha SPUS", "alpha_spus"),
            ("VaR 95", "var_95"),
            ("CVaR 95", "cvar_95"),
        ):
            value = report.get(key)
            if key == "n_sessions":
                shown = str(have)
                style = INK
            elif value is None:
                shown = f"—  {short} short" if short else "—"
                style = MUTED
            elif key == "max_drawdown":
                shown = _pct(float(value), signed=True)
                style = RED
            else:
                shown = f"{float(value):.2f}"
                style = INK
            health.add_row(_text(label, MUTED), _text(shown, style), _text(str(note), MUTED))
        _columns(status, [("CHECK", 16), ("STATE", 12), ("DETAIL", None)])
        status_rows = [
            ("as of", desk.as_of or "—", desk.source, INK),
            ("nav mark", "MARKED" if desk.nav is not None else "MISSING", desk.fill_basis or "—", GREEN if desk.nav is not None else RED),
            ("sma", "ON" if desk.sma_on else "CASH" if desk.sma_on is False else "—", desk.sma_reason or "—", GREEN if desk.sma_on else RED),
            ("kill switch", "HALT" if desk.halted else "CLEAR", desk.halt_reason or "clear", RED if desk.halted else GREEN),
            ("reconcile", "SEE NOTE", desk.reconcile_reason or "—", INK),
            ("pending", str(len(desk.pending)), "orders waiting for the open", BLUE if desk.pending else MUTED),
            ("filing fails", str(len(desk.fails)), "AAOIFI fails on the last run", RED if desk.fails else GREEN),
            ("purify today", _money(desk.purification_today), f"owed {desk.purification_payable:,.2f}", INK),
            ("purify life", _money(desk.purification_cumulative), "paper ledger, not a wire", MUTED),
            ("venue", desk.venue, "local paper account" if desk.venue != "alpaca" else "Alpaca paper", BLUE),
            ("contribution", "ON" if desk.contribution.get("enabled") else "OFF", str(desk.contribution.get("next_date") or "no date"), GREEN if desk.contribution.get("enabled") else MUTED),
            ("names", str(len(desk.holdings)), f"cap {desk.name_cap:.0%}", INK),
        ]
        for label, state, detail, style in status_rows:
            status.add_row(_text(label, MUTED), _text(state, style), _text(detail, MUTED))
        _columns(rules, [("RULE", 18), ("VALUE", 28)])
        for label, value in desk.rules:
            rules.add_row(_text(label, MUTED), _text(value, INK))
        if desk.contribution:
            rules.add_row(_text("monthly", MUTED), _text(f"{desk.contribution.get('amount', 0)}  next {desk.contribution.get('next_date') or '—'}", INK))
        rules.add_row(_text("standard", MUTED), _text("AAOIFI 30 / 30 / 70", BLUE))
        _columns(limits, [("SYM", 8), ("LINE", 8), ("GAP", 8), ("DEBT", 8), ("CASH", 8), ("RECV", 8)])
        ordered = sorted(self._rows(), key=lambda row: row.nearest_gap if row.nearest_gap is not None else 99)
        for row in ordered:
            gap_style = RED if row.nearest_gap is not None and row.nearest_gap <= 0.02 else INK
            limits.add_row(
                _text(row.symbol),
                _text(row.nearest_name or "—", MUTED),
                _text(_pct(row.nearest_gap, signed=True), gap_style),
                _meter(row.debt_ratio, 0.30, 8),
                _meter(row.cash_ratio, 0.30, 8),
                _meter(row.receivables_ratio, 0.70, 8),
                key=row.symbol,
            )

def _columns(table: DataTable, columns: list[tuple[str, int | None]]) -> None:
    table.clear(columns=True)
    for label, width in columns:
        if width is None:
            table.add_column(label)
        else:
            table.add_column(label, width=width)


def _num(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def main() -> None:
    DeskApp().run()
