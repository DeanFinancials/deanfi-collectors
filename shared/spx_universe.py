"""
S&P 500 Universe Fetcher with Deduplication

Fetches the list of S&P 500 tickers with multiple fallback sources:
1. Wikipedia (primary)
2. GitHub dataset (fallback)
3. Hardcoded list (last resort)

Includes logic to remove duplicate share classes and keep the most liquid ticker.
Also provides SEC EDGAR compatible ticker conversion.
"""
from pathlib import Path
from typing import Optional, List
import pandas as pd
import requests
from io import StringIO
import json
import sys

WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
GITHUB_SPX_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"

# SEC EDGAR ticker mapping (some tickers need conversion)
# BRK.B on Wikipedia -> BRK-B for SEC EDGAR lookups
SEC_TICKER_MAP = {
    "BRK.B": "BRK-B",
    "BF.B": "BF-B",
}

# Fallback: Static list (last updated: 2025-11-16)
FALLBACK_TICKERS = [
    "A", "AAPL", "ABBV", "ABNB", "ABT", "ACGL", "ACN", "ADBE", "ADI", "ADM",
    "ADP", "ADSK", "AEE", "AEP", "AES", "AFL", "AIG", "AIZ", "AJG", "AKAM",
    "ALB", "ALGN", "ALL", "ALLE", "AMAT", "AMCR", "AMD", "AME", "AMGN", "AMP",
    "AMT", "AMZN", "ANET", "AON", "AOS", "APA", "APD", "APH", "APO", "APP",
    "APTV", "ARE", "ATO", "AVB", "AVGO", "AVY", "AWK", "AXON", "AXP", "AZO",
    "BA", "BAC", "BALL", "BAX", "BBY", "BDX", "BEN", "BF-B", "BG", "BIIB",
    "BK", "BKNG", "BKR", "BLDR", "BLK", "BMY", "BR", "BRK-B", "BRO", "BSX",
    "BX", "BXP", "C", "CAG", "CAH", "CARR", "CAT", "CB", "CBOE", "CBRE",
    "CCI", "CCL", "CDNS", "CDW", "CEG", "CF", "CFG", "CHD", "CHRW", "CHTR",
    "CI", "CINF", "CL", "CLX", "CMCSA", "CME", "CMG", "CMI", "CMS", "CNC",
    "CNP", "COF", "COIN", "COO", "COP", "COR", "COST", "CPAY", "CPB", "CPRT",
    "CPT", "CRL", "CRM", "CRWD", "CSCO", "CSGP", "CSX", "CTAS", "CTRA", "CTSH",
    "CTVA", "CVS", "CVX", "D", "DAL", "DASH", "DAY", "DD", "DDOG", "DE",
    "DECK", "DELL", "DG", "DGX", "DHI", "DHR", "DIS", "DLR", "DLTR", "DOC",
    "DOV", "DOW", "DPZ", "DRI", "DTE", "DUK", "DVA", "DVN", "DXCM", "EA",
    "EBAY", "ECL", "ED", "EFX", "EG", "EIX", "EL", "ELV", "EME", "EMR",
    "EOG", "EPAM", "EQIX", "EQR", "EQT", "ERIE", "ES", "ESS", "ETN", "ETR",
    "EVRG", "EW", "EXC", "EXE", "EXPD", "EXPE", "EXR", "F", "FANG", "FAST",
    "FCX", "FDS", "FDX", "FE", "FFIV", "FI", "FICO", "FIS", "FITB", "FOXA",
    "FRT", "FSLR", "FTNT", "FTV", "GD", "GDDY", "GE", "GEHC", "GEN",
    "GEV", "GILD", "GIS", "GL", "GLW", "GM", "GNRC", "GOOGL", "GPC",
    "GPN", "GRMN", "GS", "GWW", "HAL", "HAS", "HBAN", "HCA", "HD", "HIG",
    "HII", "HLT", "HOLX", "HON", "HOOD", "HPE", "HPQ", "HRL", "HSIC", "HST",
    "HSY", "HUBB", "HUM", "HWM", "IBKR", "IBM", "ICE", "IDXX", "IEX", "IFF",
    "INCY", "INTC", "INTU", "INVH", "IP", "IPG", "IQV", "IR", "IRM", "ISRG",
    "IT", "ITW", "IVZ", "J", "JBHT", "JBL", "JCI", "JKHY", "JNJ", "JPM",
    "K", "KDP", "KEY", "KEYS", "KHC", "KIM", "KKR", "KLAC", "KMB", "KMI",
    "KO", "KR", "KVUE", "L", "LDOS", "LEN", "LH", "LHX", "LII", "LIN",
    "LKQ", "LLY", "LMT", "LNT", "LOW", "LRCX", "LULU", "LUV", "LVS", "LW",
    "LYB", "LYV", "MA", "MAA", "MAR", "MAS", "MCD", "MCHP", "MCK", "MCO",
    "MDLZ", "MDT", "MET", "META", "MGM", "MHK", "MKC", "MLM", "MMC", "MMM",
    "MNST", "MO", "MOH", "MOS", "MPC", "MPWR", "MRK", "MRNA", "MS", "MSCI",
    "MSFT", "MSI", "MTB", "MTCH", "MTD", "MU", "NCLH", "NDAQ", "NDSN", "NEE",
    "NEM", "NFLX", "NI", "NKE", "NOC", "NOW", "NRG", "NSC", "NTAP", "NTRS",
    "NUE", "NVDA", "NVR", "NWSA", "NXPI", "O", "ODFL", "OKE", "OMC",
    "ON", "ORCL", "ORLY", "OTIS", "OXY", "PANW", "PAYC", "PAYX", "PCAR", "PCG",
    "PEG", "PEP", "PFE", "PFG", "PG", "PGR", "PH", "PHM", "PKG", "PLD",
    "PLTR", "PM", "PNC", "PNR", "PNW", "PODD", "POOL", "PPG", "PPL", "PRU",
    "PSA", "PSKY", "PSX", "PTC", "PWR", "PYPL", "Q", "QCOM", "RCL", "REG",
    "REGN", "RF", "RJF", "RL", "RMD", "ROK", "ROL", "ROP", "ROST", "RSG",
    "RTX", "RVTY", "SBAC", "SBUX", "SCHW", "SHW", "SJM", "SLB", "SMCI", "SNA",
    "SNPS", "SO", "SOLS", "SOLV", "SPG", "SPGI", "SRE", "STE", "STLD", "STT",
    "STX", "STZ", "SW", "SWK", "SWKS", "SYF", "SYK", "SYY", "T", "TAP",
    "TDG", "TDY", "TECH", "TEL", "TER", "TFC", "TGT", "TJX", "TKO", "TMO",
    "TMUS", "TPL", "TPR", "TRGP", "TRMB", "TROW", "TRV", "TSCO", "TSLA", "TSN",
    "TT", "TTD", "TTWO", "TXN", "TXT", "TYL", "UAL", "UBER", "UDR", "UHS",
    "ULTA", "UNH", "UNP", "UPS", "URI", "USB", "V", "VICI", "VLO", "VLTO",
    "VMC", "VRSK", "VRSN", "VRTX", "VST", "VTR", "VTRS", "VZ", "WAB", "WAT",
    "WBD", "WDAY", "WDC", "WEC", "WELL", "WFC", "WM", "WMB", "WMT", "WRB",
    "WSM", "WST", "WTW", "WY", "WYNN", "XEL", "XOM", "XYL", "XYZ", "YUM",
    "ZBH", "ZBRA", "ZTS"
]


def deduplicate_tickers(tickers: list) -> list:
    """
    Remove duplicate share classes, keeping the most common/liquid ticker.
    
    For companies with multiple share classes (e.g., BRK.A and BRK.B),
    keep only the one that appears in the index.
    
    Args:
        tickers: List of ticker symbols
        
    Returns:
        Deduplicated list of tickers
    """
    # Dictionary of preferred tickers when duplicates exist
    preferred = {
        'BRK': 'BRK-B',  # Berkshire Hathaway B shares (more liquid)
        'BF': 'BF-B',    # Brown-Forman B shares
        'GOOGL': 'GOOGL',  # Alphabet A shares (with voting rights)
        'GOOG': 'GOOGL',   # Prefer GOOGL over GOOG
        'NWS': 'NWSA',     # News Corp A shares
    }
    
    deduplicated = []
    seen_bases = set()
    
    for ticker in tickers:
        # Extract base ticker (before -, .)
        base = ticker.split('-')[0].split('.')[0]
        
        # Check if we've seen this base before
        if base in seen_bases:
            # If there's a preferred ticker, use it
            if base in preferred and ticker == preferred[base]:
                # Replace the previous occurrence
                deduplicated = [t for t in deduplicated if not t.startswith(base)]
                deduplicated.append(ticker)
        else:
            deduplicated.append(ticker)
            seen_bases.add(base)
    
    return sorted(deduplicated)


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


def fetch_spx_tickers(sec_compatible: bool = False) -> list:
    """
    Fetch S&P 500 ticker symbols with multiple fallback sources.
    
    Args:
        sec_compatible: If True, convert tickers to SEC EDGAR compatible format
    
    Returns:
        List of S&P 500 ticker symbols (deduplicated, with . replaced by -)
    """
    tickers = []
    
    # Try Wikipedia first
    try:
        print("Fetching S&P 500 tickers from Wikipedia...", file=sys.stderr)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
            )
        }
        response = requests.get(WIKI_URL, headers=headers, timeout=20)
        response.raise_for_status()
        
        tables = pd.read_html(StringIO(response.text))
        
        # Find the table with 'Symbol' column and enough rows
        df = None
        for table in tables:
            if 'Symbol' in table.columns and len(table) > 400:
                df = table
                break
        
        if df is None:
            raise ValueError("Could not find S&P 500 constituents table")
        
        # Convert tickers
        if sec_compatible:
            tickers = [convert_ticker_for_sec(t) for t in df['Symbol'].tolist()]
        else:
            # Replace . with - for Yahoo Finance compatibility (e.g., BRK.B -> BRK-B)
            tickers = df['Symbol'].str.replace('.', '-', regex=False).tolist()
        
        tickers = deduplicate_tickers(tickers)
        print(f"✓ Fetched {len(tickers)} tickers from Wikipedia", file=sys.stderr)
        return tickers
    except Exception as e:
        print(f"✗ Wikipedia fetch failed: {e}", file=sys.stderr)
    
    # Try GitHub dataset as fallback
    try:
        print("Fetching S&P 500 tickers from GitHub dataset...", file=sys.stderr)
        response = requests.get(GITHUB_SPX_URL, timeout=10)
        response.raise_for_status()
        df = pd.read_csv(StringIO(response.text))
        
        # Convert tickers
        if sec_compatible:
            tickers = [convert_ticker_for_sec(t) for t in df['Symbol'].tolist()]
        else:
            # Replace . with - for Yahoo Finance compatibility
            tickers = df['Symbol'].str.replace('.', '-', regex=False).tolist()
        
        tickers = deduplicate_tickers(tickers)
        print(f"✓ Fetched {len(tickers)} tickers from GitHub", file=sys.stderr)
        return tickers
    except Exception as e:
        print(f"✗ GitHub fetch failed: {e}", file=sys.stderr)
    
    # Use hardcoded fallback
    print("Using hardcoded S&P 500 ticker list (fallback)", file=sys.stderr)
    print(f"✓ Loaded {len(FALLBACK_TICKERS)} tickers from fallback", file=sys.stderr)
    return FALLBACK_TICKERS


def get_spx_tickers(exclusions: Optional[list] = None) -> list:
    """
    Get S&P 500 tickers with optional exclusions.
    
    Alias for fetch_spx_tickers() with exclusion support.
    Used by analysttrends, earningscalendar, earningssurprises.
    
    Args:
        exclusions: List of tickers to exclude (optional)
        
    Returns:
        List of S&P 500 ticker symbols
    """
    tickers = fetch_spx_tickers()
    
    if exclusions:
        original_count = len(tickers)
        tickers = [t for t in tickers if t not in exclusions]
        removed = original_count - len(tickers)
        if removed > 0:
            print(f"Excluded {removed} ticker(s)", file=sys.stderr)
    
    return sorted(tickers)


if __name__ == "__main__":
    tickers = fetch_spx_tickers()
    print(json.dumps(tickers, indent=2))
