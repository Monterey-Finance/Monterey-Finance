"""S&P 500 list, activity screen, tech/clean-energy and ROIC focus buckets."""

from __future__ import annotations

from io import StringIO

import pandas as pd
import requests

from .rules import (
    CLEAN_ENERGY_EXTRA,
    CLEAN_ENERGY_KEYWORDS,
    TECH_SECTORS,
)

FALLBACK_SP500 = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "BRK-B", "LLY", "AVGO", "JPM",
    "UNH", "XOM", "V", "MA", "PG", "COST", "HD", "JNJ", "ABBV", "NFLX",
    "CRM", "MRK", "AMD", "PEP", "KO", "TMO", "ADBE", "WMT", "CSCO", "ACN",
]


def load_sp500_tickers() -> list[str]:
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    headers = {"User-Agent": "MontereyFinanceResearch/1.0 (halal-quant-sleeves)"}
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        table = pd.read_html(StringIO(response.text), attrs={"id": "constituents"})[0]
        return (
            table["Symbol"]
            .astype(str)
            .str.replace(".", "-", regex=False)
            .tolist()
        )
    except Exception as exc:
        print(f"Could not fetch S&P 500 list ({exc}); using fallback basket.")
        return FALLBACK_SP500.copy()


def apply_sector_screen(tickers: list[str]) -> tuple[list[str], pd.DataFrame, dict[str, str]]:
    from halalquant.providers._yfinance import YFinanceProvider
    from halalquant.screening._sector_filter import SectorFilter

    provider = YFinanceProvider()
    sector_map = provider.get_sector_map(tickers)
    sector_filter = SectorFilter()
    kept = sector_filter.filter_symbols(tickers, sector_map=sector_map)
    audit = pd.DataFrame(sector_filter.audit_log)
    return kept, audit, sector_map


def is_tech_or_clean_energy(sector: str, industry: str, symbol: str) -> bool:
    if str(symbol).upper() in {s.upper() for s in CLEAN_ENERGY_EXTRA}:
        return True
    sec = (sector or "").strip()
    if sec in TECH_SECTORS:
        return True
    blob = f"{sec} {industry or ''}".lower()
    return any(k in blob for k in CLEAN_ENERGY_KEYWORDS)


def classify_focus(sector: str, industry: str) -> str:
    s = (sector or "").strip().lower()
    i = (industry or "").strip().lower()
    if "health information services" in i:
        return "SaaS"
    if any(
        token in i
        for token in (
            "medical devices",
            "medical instruments",
            "diagnostics & research",
            "medical distribution",
        )
    ):
        return "MedTech"
    if (
        any(
            token in i
            for token in (
                "drug manufacturers",
                "biotechnology",
                "healthcare plans",
                "medical care facilities",
                "pharmaceutical",
            )
        )
        or s in {"healthcare", "health care"}
    ):
        return "Healthcare"
    if any(token in i for token in ("software", "information technology services")):
        return "SaaS"
    return "Other"
