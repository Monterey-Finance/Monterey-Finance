"use client"

import { useEffect, useMemo, useState } from "react"
import type { FundSnapshot, NavPoint } from "@/lib/fund"

type RangeKey = "1M" | "3M" | "YTD" | "1Y" | "All"

const RANGES: RangeKey[] = ["1M", "3M", "YTD", "1Y", "All"]

const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const sharesFormat = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 })

export function Dashboard({ fund }: { fund: FundSnapshot }) {
  const [theme, setTheme] = useState<"white" | "black">("white")
  const [query, setQuery] = useState("")
  const [range, setRange] = useState<RangeKey>("All")

  useEffect(() => {
    const stored = window.localStorage.getItem("monterey-theme")
    if (stored === "black") {
      setTheme("black")
      document.documentElement.setAttribute("data-theme", "black")
    }
  }, [])

  function chooseTheme(next: "white" | "black") {
    setTheme(next)
    window.localStorage.setItem("monterey-theme", next)
    if (next === "black") document.documentElement.setAttribute("data-theme", "black")
    else document.documentElement.removeAttribute("data-theme")
  }

  const latest = fund.points.at(-1) ?? null
  const series = useMemo(() => filterRange(fund.points, range), [fund.points, range])
  const holdings = fund.holdings.filter((row) => row.symbol.toLowerCase().includes(query.trim().toLowerCase()))
  const sinceStart = totalReturn(fund.points)
  const day = latest?.dailyReturn ?? null

  return (
    <div className="shell">
      <aside className="rail">
        <p className="wordmark">Monterey</p>
        <p className="rail-label">Account</p>
        <a className="nav-item" href="/" aria-current="page">
          Home
        </a>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <input
            className="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search holdings"
            aria-label="Search holdings"
          />
          <span className="paper-chip">Paper</span>
          <span className={latest ? "asof" : "asof stale"}>
            {latest ? `NAV as of ${formatDate(latest.asOf)}` : "Last NAV unavailable"}
          </span>
          <div className="theme-switch" role="group" aria-label="Theme">
            <button type="button" aria-pressed={theme === "white"} onClick={() => chooseTheme("white")}>
              White
            </button>
            <button type="button" aria-pressed={theme === "black"} onClick={() => chooseTheme("black")}>
              Black
            </button>
          </div>
        </header>
        {fund.halted ? (
          <div className="halt" role="status">
            Trading is paused until the paper account is reconciled.
            {fund.haltReason ? ` ${fund.haltReason}` : ""}
          </div>
        ) : null}
        <main className="page">
          <section className="card widget" aria-labelledby="nav-title">
            <div className="hero-head">
              <h1 id="nav-title" className="card-title">
                Net asset value
              </h1>
              <div className="range" role="group" aria-label="Chart range">
                {RANGES.map((key) => (
                  <button key={key} type="button" aria-pressed={range === key} onClick={() => setRange(key)}>
                    {key}
                  </button>
                ))}
              </div>
            </div>
            <div className="hero-figure">
              <p className="figure">{latest ? money.format(latest.nav) : "—"}</p>
              {day != null && latest ? <span className={toneClass(day)}>{signedPercent(day)}</span> : null}
            </div>
            <p className="session-note">
              {latest
                ? `Paper account. Day change uses the ledger close on ${formatDate(latest.asOf)}.`
                : "NAV prints after the first session."}
            </p>
            <div className="stats">
              <Stat label="Invested" value={latest ? money.format(latest.invested) : "—"} />
              <Stat label="Cash" value={latest ? money.format(latest.cash) : "—"} />
              <Stat label="Holdings" value={latest ? String(fund.holdings.length || latest.nPositions) : "0"} />
              <Stat label="Since start" value={sinceStart == null ? "—" : signedPercent(sinceStart)} />
            </div>
            {fund.smaOn === false ? (
              <p className="cash-note">
                The book is in cash. {fund.smaReason ?? "SPY is at or below its 200-day average."}
              </p>
            ) : null}
            <GrowthChart points={series} />
          </section>

          <section className="card holdings widget" aria-labelledby="holdings-title">
            <div className="list-head">
              <h2 id="holdings-title" className="card-title">
                Holdings
              </h2>
              <span className={statusClass(fund)}>
                {statusLabel(fund)}
              </span>
            </div>
            {holdings.length === 0 ? (
              <p className="empty">
                {fund.smaOn === false
                  ? "The paper book is in cash. No companies are held this session."
                  : query
                    ? "No holding matches that search."
                    : "No names in the paper book yet."}
              </p>
            ) : (
              <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Holding</th>
                      <th className="num">Weight</th>
                      <th className="num">Value</th>
                      <th className="num">Shares</th>
                      <th>Screen</th>
                    </tr>
                  </thead>
                  <tbody>
                    {holdings.map((row) => (
                      <tr key={row.symbol}>
                        <td className="symbol">{row.symbol}</td>
                        <td className="num">{(row.weight * 100).toFixed(2)}%</td>
                        <td className="num">{row.marketValue == null ? "—" : money.format(row.marketValue)}</td>
                        <td className="num">{row.shares == null ? "—" : sharesFormat.format(row.shares)}</td>
                        <td>
                          <span className={row.compliant === false ? "status fail" : row.compliant ? "status pass" : "status neutral"}>
                            {row.compliant === false ? "Review" : row.compliant ? "Pass" : "—"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </main>
      </div>
    </div>
  )
}

function statusLabel(fund: FundSnapshot): string {
  if (fund.halted) return "Halted"
  if (fund.smaOn === false) return "Cash"
  if (fund.holdings.length) return "Compliant"
  return "Waiting"
}

function statusClass(fund: FundSnapshot): string {
  if (fund.halted) return "status fail"
  if (fund.smaOn === false || fund.holdings.length === 0) return "status neutral"
  return "status pass"
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="stat">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  )
}

function GrowthChart({ points }: { points: NavPoint[] }) {
  const [hover, setHover] = useState<number | null>(null)
  if (points.length < 2) {
    return (
      <div className="chart-empty">
        The series starts after the next session.
      </div>
    )
  }

  const width = 800
  const height = 280
  const pad = 16
  const values = points.map((point) => point.nav)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const coords = values.map((value, index) => {
    const x = pad + (index / (values.length - 1)) * (width - pad * 2)
    const y = pad + (1 - (value - min) / span) * (height - pad * 2)
    return { x, y }
  })
  const up = values[values.length - 1] >= values[0]
  const stroke = up ? "var(--positive)" : "var(--negative)"
  const line = coords.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" ")
  const area = `${line} L ${coords[coords.length - 1].x} ${height - pad} L ${coords[0].x} ${height - pad} Z`
  const active = hover == null ? null : points[hover]

  return (
    <div
      className="chart-wrap"
      onMouseLeave={() => setHover(null)}
    >
      <svg
        className="chart"
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="Paper NAV growth"
        onMouseMove={(event) => {
          const rect = event.currentTarget.getBoundingClientRect()
          const ratio = (event.clientX - rect.left) / rect.width
          const index = Math.round(ratio * (points.length - 1))
          setHover(Math.min(points.length - 1, Math.max(0, index)))
        }}
      >
        {[0, 1, 2, 3].map((row) => {
          const y = pad + ((height - pad * 2) / 3) * row
          return <line key={row} x1={pad} x2={width - pad} y1={y} y2={y} stroke="var(--line)" />
        })}
        <path d={area} fill={stroke} opacity="0.12" />
        <path d={line} fill="none" stroke={stroke} strokeWidth="2" />
        {active && hover != null ? (
          <circle cx={coords[hover].x} cy={coords[hover].y} r="4" fill={stroke} />
        ) : null}
      </svg>
      {active && hover != null ? (
        <div
          className="tooltip"
          style={{
            left: `${(coords[hover].x / width) * 100}%`,
            top: 12,
            transform: "translateX(-50%)",
          }}
        >
          <p className="date">{formatDate(active.asOf)}</p>
          <p className="value">{money.format(active.nav)}</p>
        </div>
      ) : null}
    </div>
  )
}

function filterRange(points: NavPoint[], range: RangeKey): NavPoint[] {
  if (range === "All" || points.length === 0) return points
  const end = new Date(`${points[points.length - 1].asOf}T00:00:00`)
  const start = new Date(end)
  if (range === "1M") start.setMonth(start.getMonth() - 1)
  else if (range === "3M") start.setMonth(start.getMonth() - 3)
  else if (range === "1Y") start.setFullYear(start.getFullYear() - 1)
  else start.setMonth(0, 1)
  const cutoff = start.toISOString().slice(0, 10)
  const filtered = points.filter((point) => point.asOf >= cutoff)
  return filtered.length ? filtered : points.slice(-1)
}

function totalReturn(points: NavPoint[]): number | null {
  if (points.length === 0) return null
  const first = points[0].nav
  const last = points[points.length - 1].nav
  if (!first) return null
  return last / first - 1
}

function signedPercent(value: number): string {
  const sign = value > 0 ? "+" : ""
  return `${sign}${(value * 100).toFixed(2)}%`
}

function toneClass(value: number): string {
  if (value > 0) return "change up"
  if (value < 0) return "change down"
  return "change flat"
}

function formatDate(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number)
  return new Date(year, (month || 1) - 1, day || 1).toLocaleDateString("en-US", {
    day: "numeric",
    month: "short",
    year: "numeric",
  })
}
