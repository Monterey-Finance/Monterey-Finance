# Design — shadow fund surfaces

**Status:** planning. Applies to the investor and operator shells in [PRD.md](PRD.md).

The shadow fund should feel like a calm account: white surfaces, large figures, soft cards, and a clear status for every number. The two boards with the blue frames are the visual source. Everything else in the planning set is a feature list, not a skin.

---

## 1. Type

The UI face is **Geist**.

| Role | Family | Weight | Tracking |
| --- | --- | --- | --- |
| Default UI: nav, titles, buttons, body, labels | Geist Sans | 400 body, 500 labels and nav, 600 titles | **-0.04em** |
| Hero NAV and the single milestone figure | Geist Sans | 600 | **-0.04em** |
| Money, weights, ratios, tables | Geist Mono | 400, 500 for emphasis | 0 |

`-0.04em` is minus 4% of the font size. It is the default tracking on the investor and operator shells, including buttons and navigation. Geist Mono stays at 0 so columns of figures do not collide, and every numeric column uses tabular figures.

One exception: paragraphs of compliance prose longer than two lines (the “why this is Halal” explanation, an audit reason) use Geist Sans at **-0.02em** and weight 400. Titles inside those cards stay at -0.04em.

```css
:root {
  --font-sans: "Geist", "Geist Sans", ui-sans-serif, system-ui, sans-serif;
  --font-mono: "Geist Mono", ui-monospace, monospace;
  --tracking: -0.04em;
  --tracking-prose: -0.02em;
}

body {
  font-family: var(--font-sans);
  letter-spacing: var(--tracking);
  font-feature-settings: "ss01" 0;
}

.figure,
table .num {
  font-family: var(--font-mono);
  letter-spacing: 0;
  font-variant-numeric: tabular-nums;
}
```

### Scale

Desktop sizes. Mobile steps down one size on the hero only; labels do not go below 12px.

| Token | Size | Use |
| --- | --- | --- |
| Hero | 44px / 600 | The one NAV on Home |
| Milestone | 56px / 600 | The one goal figure. Never on the same row as the hero |
| Title | 15px / 600 | Widget titles |
| Body | 14px / 400 | Explanations |
| Label | 12px / 500 | Stat captions, table headers, axis labels. Secondary ink |
| Table | 13px mono | Operator grids and activity rows |

Line height is 1.45 for body and 1.1 for hero figures. Widget titles are sentence case. Stat captions are sentence case, in the secondary ink, sitting above the figure they name.

Do not introduce a second display face, a serif, or a tracked-out all-caps heading style.

---

## 2. Principles

### White mode and black mode

Both shells ship with a theme switch. White is the default the first time someone opens the product. Black is the same layout, type, radius, and motion, on inverted surfaces. It is not a separate “terminal theme” and not a marketing dark hero.

The switch lives in the top bar as a two-state control (sun / moon, or “White” / “Black” in the settings page) and remembers the choice on this browser profile. Changing theme does not refetch the book. The Paper chip, as-of date, and status colors stay legible in both.

**White**

| Token | Value | Use |
| --- | --- | --- |
| Canvas | `#F3F4F6` | Page behind the cards |
| Surface | `#FFFFFF` | Widgets |
| Surface muted | `#F7F8FA` | Inset rows, table header, active nav pill |
| Ink | `#0E1116` | Primary text and the primary button |
| Ink secondary | `#5C6570` | Labels, as-of, helper copy |
| Line | `rgba(14, 17, 22, 0.08)` | Hairline dividers and card borders |
| Shadow | `0 10px 40px rgba(15, 23, 42, 0.06)` | Resting card |

**Black**

| Token | Value | Use |
| --- | --- | --- |
| Canvas | `#0C0E12` | Page |
| Surface | `#16181D` | Widgets |
| Surface muted | `#1C1F26` | Inset rows, active nav |
| Ink | `#F4F5F7` | Primary text |
| Ink secondary | `#9AA1AB` | Labels |
| Line | `rgba(255, 255, 255, 0.08)` | Hairlines |
| Shadow | `0 10px 40px rgba(0, 0, 0, 0.35)` | Resting card. The 1px line does more of the separation than the shadow |

**Meaning colors, identical in both modes**

| Token | Value | Reserved for |
| --- | --- | --- |
| Positive | `#16A34A` | Up moves, pass, compliant, active job |
| Positive wash | `#DCFCE7` in white, `#14281C` in black | Percent pills, pass chips |
| Negative | `#DC2626` | Down moves, fail, halt, error |
| Negative wash | `#FEE2E2` in white, `#2A1515` in black | Fail chips |
| Neutral dot | `#9AA1AB` | Idle, skipped, not in this session |

Category chips may use a rose wash and a violet wash the way the reference balance card separates two accounts (paper cash versus invested). Those hues never encode profit or loss. Profit and loss are only positive, negative, or secondary ink when the change is flat.

The primary button is ink-colored fill with canvas-colored text: near-black on white mode, near-white on black mode. Green is not a button color. A destructive confirm uses the negative wash for the sheet accent and an ink button labeled with the action (“Post to ledger”, “Approve orders”).

Links and the focused-field ring use `#0A66C2`. That blue does not fill large areas.

### Clean widgets

A screen is a canvas, a left rail, a top bar, and a small number of white (or black-surface) cards. Cards do not nest more than one level deep.

- Radius **16px** on cards, **12px** on inputs and inner charts, **999px** on pills, chips, and the search field
- Padding **20px** on investor cards, **16px** on operator cards
- One hairline border plus the soft shadow. No heavy gray frames, no glass blur, no gradient meshes behind numbers
- One hero figure per screen. Supporting figures are at most the table size or the stat-row size
- Dividers inside a card are the line token, 1px, inset from the card padding
- Charts sit on the surface color. Grid lines are the line token. The series is a 2px stroke in positive or negative, with a soft fill at about 12% opacity under a line or area. Candles, where the PRD allows them, use the same two hues with flat bodies and thin wicks
- Iconography is a single 1.5px stroke set, 18px in the rail, currentColor. Filled icons are reserved for status dots

The rail is **232px**, surface-colored, with the wordmark at the top. Items are icon plus label. The active item is a surface-muted pill across the row, ink-colored text, no colored bar on the edge. Sections in the rail (the account group, the operator group) are separated by space and a 12px secondary label, not by boxes.

The top bar holds search (a pill, secondary placeholder), the Paper chip, the as-of date, and the theme switch. Search stretches. It does not compete with the hero number.

Investor pages stack: hero card, then a two-column row, then full-width list. The right column is the narrower card (purification, goal, or health). Operator pages may split 60 / 40 or use a full-width grid. Page max width is **1200px** for the investor shell and **1440px** for the operator shell, centered on the canvas.

### Motion

Motion confirms that a widget is there and that a control can be pressed. It does not demonstrate a brand.

**Appear.** When a widget first crosses into the viewport, it fades and rises once:

- From `opacity: 0` and `translateY(10px)` to rest
- **480ms**, `cubic-bezier(0.22, 1, 0.36, 1)`
- Stagger **50ms** between sibling widgets in document order
- Threshold about **20%** visible
- Play once per page load. Scrolling back up does not replay it
- The hero and the first row may play on load without waiting for scroll, with the same stagger. Content below the fold waits for the viewport

**Hover.** On a card or a clickable row:

- `translateY(-2px)` and a slightly deeper shadow
- **200ms**, the same curve
- Charts, figures, and text do not scale
- A row that is not a card only changes its background to surface-muted, in **120ms**, with no lift

**Press.** Buttons darken slightly. No bounce, no spring overshoot, no scale past 1.

**Theme.** Cross-fade surfaces and ink over **200ms**. Do not animate layout.

**Charts.** A line may draw on first appearance over **600ms**. After that, range changes swap the series without a draw-on. Tooltips follow the pointer with no delay.

**Reduced motion.** Under `prefers-reduced-motion: reduce`, appear, lift, and chart-draw are off. Opacity starts at 1. Hover still changes the background or the border so the target is obvious.

Do not add parallax, particle fields, number-scramble tickers, or scroll-pinned storytelling. The milestone percent does not count up.

---

## 3. What the two reference boards contribute

These are the boards framed in blue in the planning set. They lead. Other collages in that set supply features only.

### Board A — account terminal and home cards

The wide board: a market terminal with a left rail and a large price, an account home with balance, money-flow bars, and a recent-activity list, plus quote cards with a candlestick and small portfolio stats.

Take:

- The **rail plus top search** chrome, floating on a gray canvas inside a softly rounded window
- The **hero price**: large Geist figure, a green or red change beside it, a row of captioned stats underneath, then range pills (`1M` `3M` `YTD` `1Y` `All`)
- The **line that changes hue** with the move, green above the story and red below, on a quiet grid
- The **activity list**: a type icon, a label, a date, an amount aligned in mono
- The **small stat cards**: caption, figure, a thin progress bar, a sparkline. Used for sector weights, the 10% cap, or goal progress — one job each
- The **candlestick** as the operator’s name inspector, and only there

Leave:

- Crypto naming, coin logos, “Buy” as the primary action, and marketing upgrade banners
- The overlapping collage itself. The product is a grid of cards, not a stack of screenshots
- A second competing hero (the reference shows several large balances at once). Monterey Home has one

### Board B — balances, milestone, chart, sessions

The wide board: stacked account balances with a large total, a milestone with a green percent pill, a soft area chart, and a “where you’re logged in” list with status dots.

Take:

- **Stacked account rows** with a small category chip, then one total beneath them. Map the rows to paper cash and invested value. The total is NAV
- **Pill buttons** under the total for the two paper actions (deposit as the filled ink button, withdraw as the outline button)
- The **milestone block**: one oversized figure, a positive-wash pill with the percent, a large quiet secondary figure behind it. Map this to the investor’s paper goal. One per home, and only when a goal amount was set
- The **area chart** with a soft green fill, a floating tooltip (date and value), and a compact export action in the card header when the PRD allows an export
- The **status list**: title, one sentence of helper copy, then rows with a dot, a primary line, a secondary line, and a status chip. Map this to operator Today (data refresh, paper broker, NAV mark, kill switch) and to Settings sessions

Leave:

- Device-login copy and geographic session details, until a real session list exists. The pattern is for **job health** first
- Decorative giant type used as a background texture. The secondary milestone figure is real (goal amount, or cash on a throttle day), or it is omitted

---

## 4. How the principles land on each surface

### Investor

| Surface | Layout | Reference cue |
| --- | --- | --- |
| Onboarding | Centered card, 560px, step list on the left of the card, one question on the right. Back as text, Next as the ink button | The stepped sheet from the planning set, skinned with these tokens |
| Home | Rail, hero NAV card (figure, change, stat row, chart), right column with Shariah badge and purification, goal card if a target exists | Board A hero and chart. Board B milestone and status chip |
| Holdings | List of rows with sparkline optional, allocation card (donut, treemap toggle). Open row expands the Halal card in place | Board A stat cards for weights. Bars for the three ratios |
| Activity | One list, type chips, mono amounts | Board A recent activity |
| Contribute | Board B balance stack, deposit and withdraw pills, monthly toggle as a single row with a switch, illustrative chart below a caption | Board B |
| Settings | Theme switch, profile summary, job/session status list | Board B status list |

The Shariah badge is a pill: positive wash and a green dot for Compliant, negative wash for Halted, a neutral wash for Review. It sits in the right column, not inside the hero number.

Ratio rows on the Halal card are a label, a mono value, a thin track, and a tick at the AAOIFI line. The filled portion is positive ink while under the line and negative ink when over it. The DJIM tick, when shown, is a hairline labeled “DJIM 33%” in secondary ink.

### Operator

Same canvas, rail, type, and theme. Density goes up by tightening padding and using mono in every numeric cell. The order matrix is a real table: sticky header, hairline rows, hover wash, no card-per-row. Status steps for a commit (Draft, Approved, Executing, Completed) are a horizontal trail of pills at the top of the Orders page. The current step is ink-filled. Future steps are outline. Halted replaces the trail’s current step with the negative wash.

The breach queue and the audit log use the status-list pattern at table density: dot, ticker or event, secondary filing or actor line, chip.

Black mode is the preferred working mode for a long operator session only because the user chose it. The layout does not change when they do.

---

## 5. Components

**Paper chip.** Outline pill, 12px, secondary ink, label `Paper`. Always in the top bar. Beside it, `NAV as of 12 Mar 2026` in secondary ink. When the book is stale, the date turns negative ink and the text becomes `Last NAV 12 Mar 2026`.

**Stat row.** Four cells, hairline between them, caption above, mono figure below. No icons required.

**Range pills.** A muted track with the active range in a surface pill and ink text. Inactive ranges are secondary ink.

**Chart tooltip.** Small surface card, 12px radius, shadow, date in secondary, value in mono. One tooltip at a time.

**Progress.** 4px track, line-colored, rounded, fill in positive or negative. Used for goal percent, cap usage, and ratio bars.

**Confirm sheet.** Centered surface, 480px, 16px radius. Title, the before → after diff in mono, the paper disclosure sentence, then Cancel (outline) and the ink confirm button. The sheet fades the canvas with `rgba(14, 17, 22, 0.4)` and rises 8px over 200ms. Reduced motion skips the rise.

**Empty.** The widget still renders its title. The body is one sentence in secondary ink and, when useful, the condition that fills it (“NAV prints after the first session”). No illustration of a coin or a rocket.

**Halt banner.** Full width under the top bar, negative wash, one line of reason, a text action “View run” for the operator. The investor version uses the investor sentence from the PRD. It does not animate in a loop.

---

## 6. Accessibility and responsiveness

- Text contrast meets WCAG AA in both themes, including secondary ink on surface and positive ink on positive wash
- Focus is a 2px `#0A66C2` ring, 2px offset, on every interactive control. Hover lift is never the only affordance
- Status is not color alone. Dots are paired with a chip label (Compliant, Review, Halted, Active, Skipped, Error)
- Tables scroll horizontally inside the card before the page does. The first column (name or event) stays sticky
- Below 960px the rail collapses to icons with a tooltip, or to a top drawer. The hero drops to 36px. The right column stacks under the chart. Touch targets are at least 40px

---

## 7. Implementation notes

- Load Geist Sans and Geist Mono as the only UI faces
- Put the tokens in section 2 on `:root` and `[data-theme="black"]`. Components consume tokens, not raw hexes
- Appear-on-scroll is an intersection observer on the widget, not a scroll listener that recalculates layout
- Chart colors come from the positive and negative tokens so a theme switch recolors series with the surfaces
- Do not ship a third theme, a density toggle, or per-widget color preferences in this phase
