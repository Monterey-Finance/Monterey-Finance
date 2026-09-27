import type { Metadata } from "next"
import { GeistMono } from "geist/font/mono"
import { GeistSans } from "geist/font/sans"
import "./globals.css"

export const metadata: Metadata = {
  title: "Monterey — Paper fund",
  description: "Paper-account overview for the Monterey Finance shadow fund.",
}

const themeBoot = `
try {
  var theme = localStorage.getItem("monterey-theme");
  if (theme === "black") document.documentElement.setAttribute("data-theme", "black");
} catch (e) {}
`

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeBoot }} />
      </head>
      <body>{children}</body>
    </html>
  )
}
