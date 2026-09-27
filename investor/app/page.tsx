import { Dashboard } from "./dashboard"
import { loadFund } from "@/lib/fund"

export const dynamic = "force-dynamic"

export default function HomePage() {
  return <Dashboard fund={loadFund()} />
}
