"""
S&P 100 Universe Fetcher with Fallbacks

Fetches the list of S&P 100 tickers with multiple fallback sources:
1. Wikipedia S&P 100 constituents page (primary)
2. Hardcoded fallback list (last resort)

Includes special handling for:
- BRK.B -> BRK-B conversion for SEC EDGAR compatibility
- Deduplication of share classes (GOOGL vs GOOG)
"""
from typing import Optional, List
import pandas as pd
import requests
from io import StringIO
import json
import sys

WIKI_URL = "https://en.wikipedia.org/wiki/S%26P_100"

# SEC EDGAR ticker mapping (some tickers need conversion)
# BRK.B on Wikipedia -> BRK-B for SEC EDGAR lookups
SEC_TICKER_MAP = {
    "BRK.B": "BRK-B",
    "BF.B": "BF-B",
}

# Fallback: Static list (last updated: 2025-12-06)
# Source: Wikipedia S&P 100 constituents
FALLBACK_TICKERS = [
    "AAPL", "ABBV", "ABT", "ACN", "ADBE", "AIG", "AMD", "AMGN", "AMT", "AMZN",
    "AVGO", "AXP", "BA", "BAC", "BK", "BKNG", "BLK", "BMY", "BRK-B", "C",
    "CAT", "CL", "CMCSA", "COF", "COP", "COST", "CRM", "CSCO", "CVS", "CVX",
    "DE", "DHR", "DIS", "DUK", "EMR", "FDX", "GD", "GE", "GILD", "GM",
    "GOOGL", "GS", "HD", "HON", "IBM", "INTC", "INTU", "ISRG", "JNJ", "JPM",
    "KO", "LIN", "LLY", "LMT", "LOW", "MA", "MCD", "MDLZ", "MDT", "MET",
    "META", "MMM", "MO", "MRK", "MS", "MSFT", "NEE", "NFLX", "NKE", "NOW",
    "NVDA", "ORCL", "PEP", "PFE", "PG", "PLTR", "PM", "PYPL", "QCOM", "RTX",
    "SBUX", "SCHW", "SO", "SPG", "T", "TGT", "TMO", "TMUS", "TSLA", "TXN",
    "UBER", "UNH", "UNP", "UPS", "USB", "V", "VZ", "WFC", "WMT", "XOM"
]


def deduplicate_tickers(tickers: list) -> list:
    """
    Remove duplicate share classes, keeping the preferred ticker.
    
    For companies with multiple share classes (e.g., GOOG and GOOGL),
    keep only the primary/most liquid ticker.
    
    Args:
        tickers: List of ticker symbols
        
    Returns:
        Deduplicated list of tickers
    """
    # Dictionary of preferred tickers when duplicates exist
    preferred = {
        'GOOGL': 'GOOGL',  # Alphabet A shares (with voting rights) - preferred
        'GOOG': 'GOOGL',   # Redirect C shares to A shares
    }
    
    deduplicated = []
    seen_companies = set()
    
    for ticker in tickers:
        # Check if this ticker should be replaced
        canonical = preferred.get(ticker, ticker)
        
        # Extract base ticker for deduplication
        base = canonical.split('-')[0].split('.')[0]
        
        # Skip if we've already seen this company
        if base in seen_companies and base in ['GOOG', 'GOOGL']:
            continue
        
        # Mark company as seen
        if base in ['GOOG', 'GOOGL']:
            seen_companies.add('GOOG')
            seen_companies.add('GOOGL')
            deduplicated.append('GOOGL')  # Always use GOOGL
        else:
            deduplicated.append(canonical)
            seen_companies.add(base)
    
    return sorted(set(deduplicated))


def convert_ticker_for_sec(ticker: str) -> str:
    """
    Convert Wikipedia ticker format to SEC EDGAR format.
    
    Args:
        ticker: Ticker symbol from Wikipedia
        
    Returns:
        SEC EDGAR compatible ticker
    """
    # Apply known conversions
    if ticker in SEC_TICKER_MAP:
        return SEC_TICKER_MAP[ticker]
    
    # Replace . with - for general compatibility
    return ticker.replace('.', '-')


def fetch_sp100_tickers() -> List[str]:
    """
    Fetch S&P 100 ticker symbols with multiple fallback sources.
    
    Returns:
        List of S&P 100 ticker symbols (deduplicated, SEC EDGAR compatible)
    """
    # Try Wikipedia first
    try:
        print("Fetching S&P 100 tickers from Wikipedia...", file=sys.stderr)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
            )
        }
        response = requests.get(WIKI_URL, headers=headers, timeout=20)
        response.raise_for_status()
        
        tables = pd.read_html(StringIO(response.text))
        
        # Find the table with 'Symbol' column and appropriate row count
        # S&P 100 has ~101 constituents (including both Alphabet classes)
        df = None
        for table in tables:
            if 'Symbol' in table.columns and len(table) >= 95:
                df = table
                break
        
        if df is None:
            raise ValueError("Could not find S&P 100 constituents table")
        
        # Convert tickers for SEC EDGAR compatibility
        tickers = [convert_ticker_for_sec(t) for t in df['Symbol'].tolist()]
        tickers = deduplicate_tickers(tickers)
        print(f"✓ Fetched {len(tickers)} tickers from Wikipedia", file=sys.stderr)
        return tickers
    except Exception as e:
        print(f"✗ Wikipedia fetch failed: {e}", file=sys.stderr)
    
    # Use hardcoded fallback
    print("Using hardcoded S&P 100 ticker list (fallback)", file=sys.stderr)
    print(f"✓ Loaded {len(FALLBACK_TICKERS)} tickers from fallback", file=sys.stderr)
    return FALLBACK_TICKERS.copy()


def get_sp100_tickers(exclusions: Optional[List[str]] = None) -> List[str]:
    """
    Get S&P 100 tickers with optional exclusions.
    
    Alias for fetch_sp100_tickers() with exclusion support.
    
    Args:
        exclusions: List of tickers to exclude (optional)
        
    Returns:
        List of S&P 100 ticker symbols
    """
    tickers = fetch_sp100_tickers()
    
    if exclusions:
        original_count = len(tickers)
        tickers = [t for t in tickers if t not in exclusions]
        removed = original_count - len(tickers)
        if removed > 0:
            print(f"Excluded {removed} ticker(s)", file=sys.stderr)
    
    return sorted(tickers)


if __name__ == "__main__":
    tickers = fetch_sp100_tickers()
    print(json.dumps(tickers, indent=2))
