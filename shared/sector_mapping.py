"""
Comprehensive S&P 500 Sector Mapping (GICS Sectors)

Maps all S&P 500 tickers to their respective GICS sectors.
This mapping is comprehensive and covers all SPX constituents.

GICS Sectors (11 total):
1. Information Technology (XLK)
2. Health Care (XLV)
3. Financials (XLF)
4. Consumer Discretionary (XLY)
5. Communication Services (XLC)
6. Industrials (XLI)
7. Consumer Staples (XLP)
8. Energy (XLE)
9. Utilities (XLU)
10. Real Estate (XLRE)
11. Materials (XLB)
"""

from __future__ import annotations

from shared.ticker_metadata import get_sector as _get_sector_from_csv
from shared.ticker_utils import normalize_ticker

# Comprehensive ticker to sector mapping
TICKER_TO_SECTOR = {
    # Information Technology (XLK)
    'AAPL': 'Information Technology', 'MSFT': 'Information Technology', 'NVDA': 'Information Technology',
    'AVGO': 'Information Technology', 'ORCL': 'Information Technology', 'ADBE': 'Information Technology',
    'CRM': 'Information Technology', 'AMD': 'Information Technology', 'CSCO': 'Information Technology',
    'ACN': 'Information Technology', 'INTC': 'Information Technology', 'QCOM': 'Information Technology',
    'INTU': 'Information Technology', 'TXN': 'Information Technology', 'AMAT': 'Information Technology',
    'ADI': 'Information Technology', 'NOW': 'Information Technology', 'PANW': 'Information Technology',
    'MU': 'Information Technology', 'KLAC': 'Information Technology', 'LRCX': 'Information Technology',
    'SNPS': 'Information Technology', 'CDNS': 'Information Technology', 'ADSK': 'Information Technology',
    'NXPI': 'Information Technology', 'MCHP': 'Information Technology', 'PLTR': 'Information Technology',
    'CRWD': 'Information Technology', 'ANET': 'Information Technology', 'APH': 'Information Technology',
    'MSI': 'Information Technology', 'FTNT': 'Information Technology', 'FICO': 'Information Technology',
    'WDAY': 'Information Technology', 'DDOG': 'Information Technology', 'ROP': 'Information Technology',
    'KEYS': 'Information Technology', 'IT': 'Information Technology', 'CTSH': 'Information Technology',
    'GLW': 'Information Technology', 'HPQ': 'Information Technology', 'DELL': 'Information Technology',
    'HPE': 'Information Technology', 'SMCI': 'Information Technology', 'NTAP': 'Information Technology',
    'EPAM': 'Information Technology', 'STX': 'Information Technology', 'WDC': 'Information Technology',
    'TER': 'Information Technology', 'TRMB': 'Information Technology', 'AKAM': 'Information Technology',
    'FFIV': 'Information Technology', 'JNPR': 'Information Technology', 'GEN': 'Information Technology',
    'ON': 'Information Technology', 'SWKS': 'Information Technology', 'ZBRA': 'Information Technology',
    'TYL': 'Information Technology', 'VRSN': 'Information Technology', 'JKHY': 'Information Technology',
    'PTC': 'Information Technology', 'GDDY': 'Information Technology', 'CDW': 'Information Technology',
    'IBM': 'Information Technology', 'TEL': 'Information Technology', 'MPWR': 'Information Technology',
    
    # Health Care (XLV)
    'UNH': 'Health Care', 'LLY': 'Health Care', 'JNJ': 'Health Care', 'ABBV': 'Health Care',
    'MRK': 'Health Care', 'TMO': 'Health Care', 'ABT': 'Health Care', 'ISRG': 'Health Care',
    'DHR': 'Health Care', 'AMGN': 'Health Care', 'PFE': 'Health Care', 'BSX': 'Health Care',
    'VRTX': 'Health Care', 'SYK': 'Health Care', 'GILD': 'Health Care', 'BMY': 'Health Care',
    'ELV': 'Health Care', 'REGN': 'Health Care', 'CI': 'Health Care', 'MCK': 'Health Care',
    'CVS': 'Health Care', 'ZTS': 'Health Care', 'BDX': 'Health Care', 'HCA': 'Health Care',
    'MDT': 'Health Care', 'COR': 'Health Care', 'IQV': 'Health Care', 'IDXX': 'Health Care',
    'EW': 'Health Care', 'HUM': 'Health Care', 'CNC': 'Health Care', 'A': 'Health Care',
    'RMD': 'Health Care', 'DXCM': 'Health Care', 'GEHC': 'Health Care', 'BIIB': 'Health Care',
    'MRNA': 'Health Care', 'WST': 'Health Care', 'STE': 'Health Care', 'PODD': 'Health Care',
    'LH': 'Health Care', 'DGX': 'Health Care', 'RVTY': 'Health Care', 'BAX': 'Health Care',
    'ALGN': 'Health Care', 'HOLX': 'Health Care', 'MOH': 'Health Care', 'INCY': 'Health Care',
    'VTRS': 'Health Care', 'TECH': 'Health Care', 'SOLV': 'Health Care', 'UHS': 'Health Care',
    'CRL': 'Health Care', 'WAT': 'Health Care', 'HSIC': 'Health Care', 'DVA': 'Health Care',
    'CTLT': 'Health Care', 'COO': 'Health Care', 'POOL': 'Health Care', 'TFX': 'Health Care',
    'ZBH': 'Health Care', 'MTD': 'Health Care',
    
    # Financials (XLF)
    'JPM': 'Financials', 'BRK-B': 'Financials', 'V': 'Financials', 'MA': 'Financials',
    'BAC': 'Financials', 'WFC': 'Financials', 'MS': 'Financials', 'GS': 'Financials',
    'SPGI': 'Financials', 'BLK': 'Financials', 'C': 'Financials', 'AXP': 'Financials',
    'SCHW': 'Financials', 'CB': 'Financials', 'MMC': 'Financials', 'PGR': 'Financials',
    'ICE': 'Financials', 'CME': 'Financials', 'USB': 'Financials', 'PNC': 'Financials',
    'AON': 'Financials', 'TFC': 'Financials', 'MCO': 'Financials', 'COF': 'Financials',
    'BX': 'Financials', 'AIG': 'Financials', 'TRV': 'Financials', 'AFL': 'Financials',
    'AJG': 'Financials', 'MET': 'Financials', 'ALL': 'Financials', 'FIS': 'Financials',
    'PRU': 'Financials', 'MSCI': 'Financials', 'DFS': 'Financials', 'MTB': 'Financials',
    'FITB': 'Financials', 'WTW': 'Financials', 'BK': 'Financials', 'NDAQ': 'Financials',
    'RJF': 'Financials', 'GPN': 'Financials', 'STT': 'Financials', 'TROW': 'Financials',
    'HBAN': 'Financials', 'SYF': 'Financials', 'RF': 'Financials', 'CBOE': 'Financials',
    'CFG': 'Financials', 'FDS': 'Financials', 'NTRS': 'Financials', 'KEY': 'Financials',
    'WRB': 'Financials', 'PFG': 'Financials', 'L': 'Financials', 'CINF': 'Financials',
    'BRO': 'Financials', 'IVZ': 'Financials', 'ERIE': 'Financials', 'AIZ': 'Financials',
    'GL': 'Financials', 'MKTX': 'Financials', 'BEN': 'Financials', 'JEF': 'Financials',
    'HOOD': 'Financials', 'IBKR': 'Financials', 'KKR': 'Financials', 'APO': 'Financials',
    'COIN': 'Financials', 'FISV': 'Financials', 'CPAY': 'Financials', 'PYPL': 'Financials',
    'PAYC': 'Financials', 'TOST': 'Financials', 'ACGL': 'Financials', 'AMP': 'Financials',
    'HIG': 'Financials',
    
    # Consumer Discretionary (XLY)
    'AMZN': 'Consumer Discretionary', 'TSLA': 'Consumer Discretionary', 'HD': 'Consumer Discretionary',
    'MCD': 'Consumer Discretionary', 'NKE': 'Consumer Discretionary', 'BKNG': 'Consumer Discretionary',
    'LOW': 'Consumer Discretionary', 'SBUX': 'Consumer Discretionary', 'TJX': 'Consumer Discretionary',
    'CMG': 'Consumer Discretionary', 'ABNB': 'Consumer Discretionary', 'MAR': 'Consumer Discretionary',
    'GM': 'Consumer Discretionary', 'F': 'Consumer Discretionary', 'HLT': 'Consumer Discretionary',
    'ORLY': 'Consumer Discretionary', 'AZO': 'Consumer Discretionary', 'YUM': 'Consumer Discretionary',
    'ROST': 'Consumer Discretionary', 'DHI': 'Consumer Discretionary', 'LEN': 'Consumer Discretionary',
    'DECK': 'Consumer Discretionary', 'LULU': 'Consumer Discretionary', 'TSCO': 'Consumer Discretionary',
    'EBAY': 'Consumer Discretionary', 'CCL': 'Consumer Discretionary', 'RCL': 'Consumer Discretionary',
    'NCLH': 'Consumer Discretionary', 'DRI': 'Consumer Discretionary', 'ULTA': 'Consumer Discretionary',
    'LVS': 'Consumer Discretionary', 'WYNN': 'Consumer Discretionary', 'MGM': 'Consumer Discretionary',
    'GPC': 'Consumer Discretionary', 'APTV': 'Consumer Discretionary', 'TPR': 'Consumer Discretionary',
    'RL': 'Consumer Discretionary', 'GRMN': 'Consumer Discretionary', 'DPZ': 'Consumer Discretionary',
    'WHR': 'Consumer Discretionary', 'NVR': 'Consumer Discretionary', 'PHM': 'Consumer Discretionary',
    'MHK': 'Consumer Discretionary', 'BBWI': 'Consumer Discretionary', 'LKQ': 'Consumer Discretionary',
    'POOL': 'Consumer Discretionary', 'HAS': 'Consumer Discretionary', 'WSM': 'Consumer Discretionary',
    'BWA': 'Consumer Discretionary', 'KMX': 'Consumer Discretionary', 'BBY': 'Consumer Discretionary',
    'EXPE': 'Consumer Discretionary', 'UBER': 'Consumer Discretionary', 'DASH': 'Consumer Discretionary',
    'LYV': 'Consumer Discretionary', 'MTCH': 'Consumer Discretionary', 'TGT': 'Consumer Discretionary',
    'TKO': 'Consumer Discretionary',
    
    # Communication Services (XLC)
    'GOOGL': 'Communication Services', 'META': 'Communication Services', 'NFLX': 'Communication Services',
    'DIS': 'Communication Services', 'T': 'Communication Services', 'VZ': 'Communication Services',
    'CMCSA': 'Communication Services', 'TMUS': 'Communication Services', 'EA': 'Communication Services',
    'CHTR': 'Communication Services', 'WBD': 'Communication Services', 'TTWO': 'Communication Services',
    'LYV': 'Communication Services', 'OMC': 'Communication Services', 'FOXA': 'Communication Services',
    'IPG': 'Communication Services', 'NWSA': 'Communication Services', 'MTCH': 'Communication Services',
    'PARA': 'Communication Services', 'TTD': 'Communication Services', 'XYZ': 'Communication Services',
    
    # Industrials (XLI)
    'GE': 'Industrials', 'CAT': 'Industrials', 'RTX': 'Industrials', 'UNP': 'Industrials',
    'HON': 'Industrials', 'ETN': 'Industrials', 'BA': 'Industrials', 'ADP': 'Industrials',
    'LMT': 'Industrials', 'DE': 'Industrials', 'GEV': 'Industrials', 'UPS': 'Industrials',
    'TT': 'Industrials', 'PH': 'Industrials', 'WM': 'Industrials', 'GD': 'Industrials',
    'CTAS': 'Industrials', 'EMR': 'Industrials', 'ITW': 'Industrials', 'MMM': 'Industrials',
    'TDG': 'Industrials', 'CSX': 'Industrials', 'NOC': 'Industrials', 'FDX': 'Industrials',
    'CARR': 'Industrials', 'NSC': 'Industrials', 'PCAR': 'Industrials', 'JCI': 'Industrials',
    'URI': 'Industrials', 'GWW': 'Industrials', 'PAYX': 'Industrials', 'CMI': 'Industrials',
    'PWR': 'Industrials', 'FAST': 'Industrials', 'HWM': 'Industrials', 'AME': 'Industrials',
    'OTIS': 'Industrials', 'RSG': 'Industrials', 'VRSK': 'Industrials', 'ODFL': 'Industrials',
    'IR': 'Industrials', 'DAL': 'Industrials', 'UAL': 'Industrials', 'LUV': 'Industrials',
    'AXON': 'Industrials', 'LDOS': 'Industrials', 'XYL': 'Industrials', 'VLTO': 'Industrials',
    'EFX': 'Industrials', 'HUBB': 'Industrials', 'ROK': 'Industrials', 'DOV': 'Industrials',
    'BR': 'Industrials', 'BLDR': 'Industrials', 'ALLE': 'Industrials', 'LHX': 'Industrials',
    'J': 'Industrials', 'SNA': 'Industrials', 'PNR': 'Industrials', 'DAY': 'Industrials',
    'GNRC': 'Industrials', 'IEX': 'Industrials', 'SWK': 'Industrials', 'NDSN': 'Industrials',
    'AOS': 'Industrials', 'CHRW': 'Industrials', 'JBHT': 'Industrials', 'EXPD': 'Industrials',
    'ROL': 'Industrials', 'TXT': 'Industrials', 'ALLE': 'Industrials', 'LII': 'Industrials',
    'TDY': 'Industrials', 'FTV': 'Industrials', 'GEHC': 'Industrials', 'EME': 'Industrials',
    'HII': 'Industrials', 'WAB': 'Industrials', 'ESAB': 'Industrials', 'CPRT': 'Industrials',
    'JBL': 'Industrials', 'CSGP': 'Industrials', 'MAS': 'Industrials', 'LW': 'Industrials',
    'APP': 'Industrials', 'EXE': 'Industrials',
    
    # Consumer Staples (XLP)
    'PG': 'Consumer Staples', 'COST': 'Consumer Staples', 'WMT': 'Consumer Staples',
    'KO': 'Consumer Staples', 'PEP': 'Consumer Staples', 'PM': 'Consumer Staples',
    'MO': 'Consumer Staples', 'MDLZ': 'Consumer Staples', 'CL': 'Consumer Staples',
    'KMB': 'Consumer Staples', 'GIS': 'Consumer Staples', 'STZ': 'Consumer Staples',
    'KHC': 'Consumer Staples', 'SYY': 'Consumer Staples', 'HSY': 'Consumer Staples',
    'MNST': 'Consumer Staples', 'K': 'Consumer Staples', 'CHD': 'Consumer Staples',
    'CLX': 'Consumer Staples', 'TSN': 'Consumer Staples', 'MKC': 'Consumer Staples',
    'CAG': 'Consumer Staples', 'SJM': 'Consumer Staples', 'HRL': 'Consumer Staples',
    'TAP': 'Consumer Staples', 'CPB': 'Consumer Staples', 'KDP': 'Consumer Staples',
    'BF-B': 'Consumer Staples', 'KVUE': 'Consumer Staples', 'EL': 'Consumer Staples',
    'DG': 'Consumer Staples', 'DLTR': 'Consumer Staples', 'KR': 'Consumer Staples',
    'BG': 'Consumer Staples', 'ADM': 'Consumer Staples', 'CAH': 'Consumer Staples',
    
    # Energy (XLE)
    'XOM': 'Energy', 'CVX': 'Energy', 'COP': 'Energy', 'EOG': 'Energy',
    'SLB': 'Energy', 'MPC': 'Energy', 'PSX': 'Energy', 'VLO': 'Energy',
    'OXY': 'Energy', 'WMB': 'Energy', 'HES': 'Energy', 'FANG': 'Energy',
    'OKE': 'Energy', 'KMI': 'Energy', 'TRGP': 'Energy', 'DVN': 'Energy',
    'HAL': 'Energy', 'BKR': 'Energy', 'EQT': 'Energy', 'CTRA': 'Energy',
    'APA': 'Energy', 'MRO': 'Energy', 'LNG': 'Energy', 'CHRD': 'Energy',
    'FSLR': 'Energy', 'EG': 'Energy', 'SOLS': 'Energy',
    
    # Utilities (XLU)
    'NEE': 'Utilities', 'SO': 'Utilities', 'DUK': 'Utilities', 'CEG': 'Utilities',
    'SRE': 'Utilities', 'AEP': 'Utilities', 'VST': 'Utilities', 'D': 'Utilities',
    'PEG': 'Utilities', 'EXC': 'Utilities', 'XEL': 'Utilities', 'ED': 'Utilities',
    'ETR': 'Utilities', 'WEC': 'Utilities', 'AWK': 'Utilities', 'DTE': 'Utilities',
    'DTE': 'Utilities', 'PPL': 'Utilities', 'ES': 'Utilities', 'FE': 'Utilities', 'AEE': 'Utilities',
    'EIX': 'Utilities', 'CMS': 'Utilities', 'CNP': 'Utilities', 'NRG': 'Utilities',
    'NI': 'Utilities', 'LNT': 'Utilities', 'EVRG': 'Utilities', 'AES': 'Utilities',
    'PNW': 'Utilities', 'PCG': 'Utilities', 'IDA': 'Utilities', 'ATO': 'Utilities',
    
    # Real Estate (XLRE)
    'PLD': 'Real Estate', 'AMT': 'Real Estate', 'EQIX': 'Real Estate', 'PSA': 'Real Estate',
    'SPG': 'Real Estate', 'WELL': 'Real Estate', 'DLR': 'Real Estate', 'O': 'Real Estate',
    'CCI': 'Real Estate', 'VICI': 'Real Estate', 'SBAC': 'Real Estate', 'EQR': 'Real Estate',
    'AVB': 'Real Estate', 'INVH': 'Real Estate', 'WY': 'Real Estate', 'MAA': 'Real Estate',
    'ARE': 'Real Estate', 'DOC': 'Real Estate', 'ESS': 'Real Estate', 'CPT': 'Real Estate',
    'VTR': 'Real Estate', 'UDR': 'Real Estate', 'EXR': 'Real Estate', 'CBRE': 'Real Estate',
    'HST': 'Real Estate', 'FRT': 'Real Estate', 'KIM': 'Real Estate', 'REG': 'Real Estate',
    'BXP': 'Real Estate', 'IRM': 'Real Estate', 'PEAK': 'Real Estate', 'AIV': 'Real Estate',
    'PSKY': 'Real Estate', 'TPL': 'Real Estate',
    
    # Materials (XLB)
    'LIN': 'Materials', 'SHW': 'Materials', 'APD': 'Materials', 'FCX': 'Materials',
    'ECL': 'Materials', 'NEM': 'Materials', 'CTVA': 'Materials', 'VMC': 'Materials',
    'MLM': 'Materials', 'NUE': 'Materials', 'DD': 'Materials', 'DOW': 'Materials',
    'PPG': 'Materials', 'ALB': 'Materials', 'STLD': 'Materials', 'BALL': 'Materials',
    'AVY': 'Materials', 'AMCR': 'Materials', 'PKG': 'Materials', 'IP': 'Materials',
    'MOS': 'Materials', 'CF': 'Materials', 'CE': 'Materials', 'EMN': 'Materials',
    'FMC': 'Materials', 'SW': 'Materials', 'IFF': 'Materials', 'LYB': 'Materials',
}

# Sector to ETF mapping
SECTOR_TO_ETF = {
    'Information Technology': 'XLK',
    'Health Care': 'XLV',
    'Financials': 'XLF',
    'Consumer Discretionary': 'XLY',
    'Communication Services': 'XLC',
    'Industrials': 'XLI',
    'Consumer Staples': 'XLP',
    'Energy': 'XLE',
    'Utilities': 'XLU',
    'Real Estate': 'XLRE',
    'Materials': 'XLB'
}

# ETF to Sector mapping (reverse)
ETF_TO_SECTOR = {v: k for k, v in SECTOR_TO_ETF.items()}


def get_sector(ticker: str) -> str:
    """
    Get the GICS sector for a ticker.
    
    Args:
        ticker: Stock ticker symbol
        
    Returns:
        GICS sector name or 'Unknown' if not found
    """
    t = normalize_ticker(ticker)
    if not t:
        return 'Unknown'

    # Prefer CSV enrichment when available for consistency.
    csv_sector = _get_sector_from_csv(t)
    if csv_sector:
        return csv_sector

    return TICKER_TO_SECTOR.get(t, 'Unknown')


def get_etf_ticker(sector: str) -> str:
    """
    Get the ETF ticker for a sector.
    
    Args:
        sector: GICS sector name
        
    Returns:
        ETF ticker or empty string if not found
    """
    return SECTOR_TO_ETF.get(sector, '')


def get_tickers_by_sector(sector: str) -> list[str]:
    """
    Get all tickers in a specific sector.
    
    Args:
        sector: GICS sector name
        
    Returns:
        List of ticker symbols in the sector
    """
    return [ticker for ticker, sec in TICKER_TO_SECTOR.items() if sec == sector]


def get_sector_stats() -> dict:
    """
    Get statistics about sector distribution.
    
    Returns:
        Dictionary with sector statistics
    """
    stats = {}
    for sector in SECTOR_TO_ETF.keys():
        tickers = get_tickers_by_sector(sector)
        stats[sector] = {
            'etf': SECTOR_TO_ETF[sector],
            'ticker_count': len(tickers),
            'tickers': sorted(tickers)
        }
    return stats


if __name__ == "__main__":
    # Print sector statistics
    print("S&P 500 Sector Distribution")
    print("=" * 70)
    
    stats = get_sector_stats()
    total = 0
    
    for sector, info in sorted(stats.items(), key=lambda x: -x[1]['ticker_count']):
        etf = info['etf']
        count = info['ticker_count']
        total += count
        print(f"{etf:6s} {sector:30s}: {count:3d} stocks")
    
    print("=" * 70)
    print(f"{'':6s} {'TOTAL':30s}: {total:3d} stocks")
