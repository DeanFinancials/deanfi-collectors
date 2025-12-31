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


@lru_cache(maxsize=1)
def _load_schwab_metadata(csv_path: Optional[str] = None) -> Dict[str, TickerMetadata]:
    path = Path(csv_path) if csv_path else _default_csv_path()
    mapping: Dict[str, TickerMetadata] = {}

    if not path.exists():
        return mapping

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        # Expected headers:
        # Symbol,Description,Market Capitalization,Average Volume (10 Day),Price,Universe,Sector,Industry,Sub-Industry
        for row in reader:
            raw_symbol = (row.get("Symbol") or "").strip()
            if not raw_symbol:
                continue

            sector = (row.get("Sector") or "").strip() or None
            industry = (row.get("Industry") or "").strip() or None
            sub_industry = (row.get("Sub-Industry") or "").strip() or None

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
