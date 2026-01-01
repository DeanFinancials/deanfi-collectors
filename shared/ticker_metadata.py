"""shared.ticker_metadata

Schwab ticker metadata lookup (sector / industry / sub-industry).

This module provides a lightweight, cached lookup over
`Schwab-Tickers-Combined-Final.csv` so collectors can enrich outputs without
making additional external API calls.

The CSV is treated as a *preferred* enrichment source when available, with
collector-specific mappings used as fallback.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

from shared.ticker_utils import candidate_tickers, normalize_ticker


@dataclass(frozen=True)
class TickerMetadata:
    symbol: str
    sector: Optional[str]
    industry: Optional[str]
    sub_industry: Optional[str]


def _default_csv_path() -> Path:
    # shared/ -> project root
    return Path(__file__).resolve().parents[1] / "Schwab-Tickers-Combined-Final.csv"


def _normalize_header_name(name: str) -> str:
    """Normalize a CSV header name for tolerant matching.

    Removes whitespace/punctuation and lowercases, so e.g.:
    - "Sub-Industry" -> "subindustry"
    - "Market Capitalization" -> "marketcapitalization"
    """

    return re.sub(r"[^a-z0-9]+", "", (name or "").strip().lower())


# Canonical fields we care about, with tolerated header variants.
_HEADER_ALIASES = {
    "symbol": ["symbol", "ticker", "sym"],
    "sector": ["sector", "gicssector"],
    "industry": ["industry", "gicsindustry"],
    "sub_industry": ["subindustry", "subindustryname", "gicssubindustry"],
}


def _resolve_header(fieldnames: Optional[list[str]], canonical: str) -> Optional[str]:
    if not fieldnames:
        return None

    wanted = set(_HEADER_ALIASES.get(canonical, []))
    for name in fieldnames:
        if _normalize_header_name(name) in wanted:
            return name
    return None


@lru_cache(maxsize=1)
def _load_schwab_metadata(csv_path: Optional[str] = None) -> Dict[str, TickerMetadata]:
    path = Path(csv_path) if csv_path else _default_csv_path()
    mapping: Dict[str, TickerMetadata] = {}

    if not path.exists():
        return mapping

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        # Required headers (order-independent):
        # - Symbol (or Ticker)
        # Optional headers we use when present:
        # - Sector, Industry, Sub-Industry (header variants tolerated)

        symbol_header = _resolve_header(reader.fieldnames, "symbol")
        sector_header = _resolve_header(reader.fieldnames, "sector")
        industry_header = _resolve_header(reader.fieldnames, "industry")
        sub_industry_header = _resolve_header(reader.fieldnames, "sub_industry")

        if not symbol_header:
            # If we can't identify the symbol column, treat the CSV as unusable
            # and let the hardcoded mapping handle sector lookups.
            return mapping

        for row in reader:
            raw_symbol = (row.get(symbol_header) or "").strip()
            if not raw_symbol:
                continue

            sector = (row.get(sector_header) or "").strip() if sector_header else ""
            industry = (row.get(industry_header) or "").strip() if industry_header else ""
            sub_industry = (row.get(sub_industry_header) or "").strip() if sub_industry_header else ""

            sector = sector or None
            industry = industry or None
            sub_industry = sub_industry or None

            meta = TickerMetadata(
                symbol=raw_symbol,
                sector=sector,
                industry=industry,
                sub_industry=sub_industry,
            )

            # Store under normalized forms for robust lookup.
            key = normalize_ticker(raw_symbol)
            if key:
                mapping[key] = meta

    return mapping


def get_ticker_metadata(ticker: str, csv_path: Optional[str] = None) -> Optional[TickerMetadata]:
    """Lookup ticker metadata from the Schwab CSV.

    Args:
        ticker: Any ticker format (e.g., BRK.B, BRK-B, BRK/B)
        csv_path: Optional override path for testing

    Returns:
        TickerMetadata or None if not found.
    """

    mapping = _load_schwab_metadata(csv_path)
    if not mapping:
        return None

    for candidate in candidate_tickers(ticker):
        meta = mapping.get(candidate)
        if meta is not None:
            return meta

    return None


def get_sector(ticker: str, csv_path: Optional[str] = None) -> Optional[str]:
    meta = get_ticker_metadata(ticker, csv_path)
    return meta.sector if meta else None


def get_industry(ticker: str, csv_path: Optional[str] = None) -> Optional[str]:
    meta = get_ticker_metadata(ticker, csv_path)
    return meta.industry if meta else None


def get_sub_industry(ticker: str, csv_path: Optional[str] = None) -> Optional[str]:
    meta = get_ticker_metadata(ticker, csv_path)
    return meta.sub_industry if meta else None
