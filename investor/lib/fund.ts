import fs from "fs"
import path from "path"

export type NavPoint = {
  asOf: string
  nav: number
  cash: number
  invested: number
  dailyReturn: number
  nPositions: number
  smaOn: boolean
  halted: boolean
  purificationCumulative: number
}

export type Holding = {
  symbol: string
  weight: number
  marketValue: number | null
  shares: number | null
  debtRatio: number | null
  cashRatio: number | null
  receivablesRatio: number | null
  compliant: boolean | null
}

export type FundSnapshot = {
  points: NavPoint[]
  holdings: Holding[]
  asOf: string | null
  smaOn: boolean | null
  smaReason: string | null
  halted: boolean
  haltReason: string | null
}

const REPO = path.resolve(process.cwd(), "..")
const STATE = path.join(REPO, "ops", "state")
const RUNS = path.join(REPO, "ops", "runs")

export function loadFund(): FundSnapshot {
  const points = readNav()
  const latest = points.at(-1) ?? null
  const run = readLatestRun()
  const positions = readPositions()
  const halted = Boolean(run?.halted ?? latest?.halted)
  const holdings = (run?.holdings ?? []).map((row) => {
    const shares = positions[row.symbol]
    const marketValue = latest ? row.weight * latest.nav : null
    return {
      ...row,
      shares: shares ?? null,
      marketValue,
    }
  })

  return {
    points,
    holdings,
    asOf: latest?.asOf ?? run?.asOf ?? null,
    smaOn: run?.smaOn ?? latest?.smaOn ?? null,
    smaReason: run?.smaReason ?? null,
    halted,
    haltReason: run?.haltReason ?? null,
  }
}

function readNav(): NavPoint[] {
  const file = path.join(STATE, "nav.csv")
  if (!fs.existsSync(file)) return []
  return parseCsv(fs.readFileSync(file, "utf8"))
    .map((row) => ({
      asOf: String(row.as_of ?? "").slice(0, 10),
      nav: num(row.nav),
      cash: num(row.cash),
      invested: num(row.invested),
      dailyReturn: num(row.daily_return),
      nPositions: Math.round(num(row.n_positions)),
      smaOn: bool(row.sma_on),
      halted: bool(row.halted),
      purificationCumulative: num(row.purification_cumulative),
    }))
    .filter((row) => row.asOf && Number.isFinite(row.nav))
    .sort((a, b) => a.asOf.localeCompare(b.asOf))
}

function readPositions(): Record<string, number> {
  const file = path.join(STATE, "account.json")
  if (!fs.existsSync(file)) return {}
  try {
    const payload = JSON.parse(fs.readFileSync(file, "utf8")) as {
      positions?: Record<string, number>
    }
    const positions = payload.positions ?? {}
    return Object.fromEntries(
      Object.entries(positions).map(([symbol, shares]) => [symbol, Number(shares)]),
    )
  } catch {
    return {}
  }
}

function readLatestRun(): {
  asOf: string | null
  smaOn: boolean | null
  smaReason: string | null
  halted: boolean
  haltReason: string | null
  holdings: Omit<Holding, "shares" | "marketValue">[]
} | null {
  if (!fs.existsSync(RUNS)) return null
  const days = fs
    .readdirSync(RUNS)
    .filter((name) => /^\d{4}-\d{2}-\d{2}$/.test(name))
    .sort()
  const day = [...days].reverse().find((name) => fs.existsSync(path.join(RUNS, name, "intended_book.csv")))
  if (!day) return null

  const summaryPath = path.join(RUNS, day, "summary.json")
  let summary: Record<string, unknown> = {}
  if (fs.existsSync(summaryPath)) {
    try {
      summary = JSON.parse(fs.readFileSync(summaryPath, "utf8")) as Record<string, unknown>
    } catch {
      summary = {}
    }
  }

  const holdings = parseCsv(fs.readFileSync(path.join(RUNS, day, "intended_book.csv"), "utf8"))
    .map((row) => {
      const debt = maybeNum(row.debt_ratio)
      const cash = maybeNum(row.cash_ratio)
      const recv = maybeNum(row.receivables_ratio)
      const weight = num(row.target_weight)
      const known = debt != null && cash != null && recv != null
      return {
        symbol: String(row.symbol ?? ""),
        weight,
        debtRatio: debt,
        cashRatio: cash,
        receivablesRatio: recv,
        compliant: known ? debt < 0.3 && cash < 0.3 && recv < 0.7 : null,
      }
    })
    .filter((row) => row.symbol && row.weight > 0)
    .sort((a, b) => b.weight - a.weight)

  return {
    asOf: typeof summary.as_of === "string" ? summary.as_of.slice(0, 10) : day,
    smaOn: typeof summary.sma_on === "boolean" ? summary.sma_on : null,
    smaReason: typeof summary.sma_reason === "string" ? summary.sma_reason : null,
    halted: summary.halted === true,
    haltReason: typeof summary.halt_reason === "string" ? summary.halt_reason : null,
    holdings,
  }
}

function parseCsv(text: string): Record<string, string>[] {
  const lines = text.trim().split(/\r?\n/).filter(Boolean)
  if (lines.length < 2) return []
  const headers = splitCsvLine(lines[0])
  return lines.slice(1).map((line) => {
    const cells = splitCsvLine(line)
    const row: Record<string, string> = {}
    headers.forEach((header, index) => {
      row[header] = cells[index] ?? ""
    })
    return row
  })
}

function splitCsvLine(line: string): string[] {
  const cells: string[] = []
  let current = ""
  let quoted = false
  for (let i = 0; i < line.length; i += 1) {
    const char = line[i]
    if (char === '"') {
      if (quoted && line[i + 1] === '"') {
        current += '"'
        i += 1
      } else {
        quoted = !quoted
      }
    } else if (char === "," && !quoted) {
      cells.push(current)
      current = ""
    } else {
      current += char
    }
  }
  cells.push(current)
  return cells
}

function num(value: string | undefined): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

function maybeNum(value: string | undefined): number | null {
  if (value == null || value.trim() === "") return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function bool(value: string | undefined): boolean {
  return String(value).toLowerCase() === "true"
}
