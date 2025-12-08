#!/usr/bin/env python3
"""
SP100 Growth Extractor - SEC EDGAR data extractor for annual & quarterly financials.

Pulls annual (10-K) and quarterly (10-Q) revenue and EPS data from SEC EDGAR,
with multi-source fallback for complete data coverage. Calculates YoY growth, TTM, and CAGR.

This collector fetches fundamental growth metrics for S&P 100 companies:
- Annual revenue and EPS (from 10-K filings)
- Quarterly revenue and EPS (from 10-Q filings)
- Year-over-Year growth rates
- Trailing Twelve Months (TTM) metrics
- 3-year and 5-year CAGR

Data Sources (in priority order):
- SEC EDGAR: Primary source for all annual and quarterly data
- yfinance (Yahoo Finance): First fallback for annual data
- Alpha Vantage API: Second fallback for annual data
- Finnhub "Financials As Reported": Third fallback (raw SEC XBRL data, great for banks/REITs)
- Finnhub API: Fallback for quarterly data when SEC is incomplete

The fallback hierarchy ensures maximum data coverage, especially for:
- Financial sector companies (banks use different revenue concepts)
- REITs (use rental/lease income instead of standard revenue)
- Companies with non-standard SEC filings
- Recent quarters before SEC filings are available

Usage:
    python fetch_sp100_growth.py                    # Use S&P 100 universe
    python fetch_sp100_growth.py --output ./output  # Custom output directory
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field
from datetime import datetime

import requests
import yaml
import pandas as pd

# Use the secedgar library
from secedgar.cik_lookup import get_cik_map
from secedgar.core.rest import get_company_facts

try:
    from secedgar.exceptions import EDGARQueryError
except ImportError:
    class EDGARQueryError(Exception):
        pass

# Add parent directory to path for shared imports
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import S&P 100 universe from shared module
from shared.sp100_universe import fetch_sp100_tickers
from shared.sector_mapping import get_sector


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class ValidationResult:
    """Result of cross-validating a value across multiple fallback sources."""
    value: Optional[float] = None
    status: str = "none"  # "validated", "averaged", "discrepancy", "single_source", "none"
    sources_compared: List[str] = field(default_factory=list)
    source_values: Dict[str, float] = field(default_factory=dict)
    discrepancy_pct: Optional[float] = None  # Max percentage difference between sources


@dataclass
class AnnualRecord:
    """Single year of financial data."""
    fiscal_year_end: str
    revenue: Optional[float] = None
    eps_diluted: Optional[float] = None
    revenue_concept: Optional[str] = None
    eps_concept: Optional[str] = None
    # Validation fields for fallback data
    revenue_validation: Optional[str] = None  # "validated", "averaged", "discrepancy", "single_source", None
    eps_validation: Optional[str] = None
    revenue_sources: Optional[List[str]] = None  # Sources compared for revenue
    eps_sources: Optional[List[str]] = None  # Sources compared for EPS
    revenue_discrepancy_pct: Optional[float] = None  # Max % diff between sources
    eps_discrepancy_pct: Optional[float] = None


@dataclass
class QuarterlyRecord:
    """Single quarter of financial data."""
    fiscal_quarter_end: str
    revenue: Optional[float] = None
    eps_diluted: Optional[float] = None
    source: str = "sec"  # "sec" or "finnhub"


@dataclass
class TTMMetrics:
    """Trailing Twelve Months metrics calculated from quarterly data."""
    revenue: Optional[float] = None
    eps_diluted: Optional[float] = None
    revenue_yoy: Optional[float] = None  # TTM vs TTM from 4 quarters ago
    eps_yoy: Optional[float] = None
    as_of_quarter: Optional[str] = None  # End date of most recent quarter
    source: str = "sec"  # "sec", "finnhub", or "annual_fallback"


@dataclass
class GrowthMetrics:
    """Year-over-year growth calculations."""
    revenue_yoy: Dict[str, Optional[float]]  # {"2024": 0.05, "2023": 0.08}
    eps_yoy: Dict[str, Optional[float]]
    ttm: Optional[TTMMetrics] = None
    revenue_cagr_3yr: Optional[float] = None
    eps_cagr_3yr: Optional[float] = None
    revenue_cagr_5yr: Optional[float] = None
    eps_cagr_5yr: Optional[float] = None


@dataclass
class CompanyData:
    """Complete extracted data for one company."""
    ticker: str
    cik: str
    company_name: Optional[str]
    extracted_at: str
    annual_data: List[AnnualRecord]
    quarterly_data: List[QuarterlyRecord]
    growth: GrowthMetrics
    errors: List[str]


# ============================================================================
# Configuration
# ============================================================================

@dataclass
class Config:
    user_agent: str
    years_to_fetch: int
    quarters_to_fetch: int
    concepts: Dict[str, List[str]]
    output_dir: Path
    output_filename: str
    indent: int
    finnhub_enabled: bool
    finnhub_api_key: str
    finnhub_as_reported_enabled: bool  # Finnhub "Financials As Reported" (SEC filings)
    yfinance_enabled: bool
    alphavantage_enabled: bool
    alphavantage_api_key: str
    fmp_enabled: bool  # Financial Modeling Prep (tiebreaker for discrepancies)
    fmp_api_key: str

    @staticmethod
    def from_yaml(path: str) -> "Config":
        with open(path, "r") as f:
            raw = yaml.safe_load(f)
        
        sec = raw.get("sec", {})
        output = raw.get("output", {})
        finnhub = raw.get("finnhub", {})
        finnhub_as_reported = raw.get("finnhub_as_reported", {})
        yfinance = raw.get("yfinance", {})
        alphavantage = raw.get("alphavantage", {})
        fmp = raw.get("fmp", {})
        
        # Read API keys from environment variables (standard pattern)
        finnhub_api_key = os.environ.get("FINNHUB_API_KEY", "")
        alphavantage_api_key = os.environ.get("ALPHA_VANTAGE_API_KEY", "")
        fmp_api_key = os.environ.get("FMP_API_KEY", "")
        
        return Config(
            user_agent=sec.get("user_agent", ""),
            years_to_fetch=raw.get("years_to_fetch", 6),
            quarters_to_fetch=raw.get("quarters_to_fetch", 8),
            concepts=raw.get("concepts", {}),
            output_dir=Path(output.get("directory", "./output")),
            output_filename=output.get("filename", "sp100growth.json"),
            indent=output.get("indent", 2),
            finnhub_enabled=finnhub.get("enabled", False),
            finnhub_api_key=finnhub_api_key,
            finnhub_as_reported_enabled=finnhub_as_reported.get("enabled", True),  # Enabled by default (free, no rate limit)
            yfinance_enabled=yfinance.get("enabled", True),
            alphavantage_enabled=alphavantage.get("enabled", False),
            alphavantage_api_key=alphavantage_api_key,
            fmp_enabled=fmp.get("enabled", False),  # Disabled by default - only enable when needed
            fmp_api_key=fmp_api_key,
        )


# ============================================================================
# SEC Data Fetching
# ============================================================================

def load_ticker_to_cik(user_agent: str) -> Dict[str, str]:
    """Load ticker -> CIK mapping from SEC."""
    try:
        m = get_cik_map(user_agent=user_agent)["ticker"]
        return {t.upper(): str(cik).zfill(10) for t, cik in m.items() if t and cik}
    except Exception as e:
        print(f"[warn] Failed to load CIK map: {e}")
        return {}


def fetch_company_facts(ticker: str, user_agent: str) -> Optional[dict]:
    """Fetch company facts JSON from SEC EDGAR."""
    try:
        facts_map = get_company_facts(lookups=[ticker], user_agent=user_agent)
        return facts_map.get(ticker) or facts_map.get(ticker.upper()) or next(iter(facts_map.values()), None)
    except EDGARQueryError as e:
        print(f"[warn] SEC query error for {ticker}: {e}")
        return None
    except Exception as e:
        print(f"[warn] Failed to fetch {ticker}: {e}")
        return None


# ============================================================================
# Finnhub Fallback
# ============================================================================

def finnhub_quarterly_financials(symbol: str, api_key: str, timeout: int = 15) -> pd.DataFrame:
    """Fetch quarterly revenue and EPS from Finnhub."""
    if not api_key:
        return pd.DataFrame(columns=["end", "revenue", "eps_diluted"])
    
    base = "https://finnhub.io/api/v1"
    rows = {}
    
    # Income statement for revenue and EPS
    try:
        url = f"{base}/stock/financials?symbol={symbol}&statement=ic&freq=quarterly&token={api_key}"
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            js = r.json() or {}
            for item in (js.get("data") or []):
                end = item.get("period") or item.get("endDate") or item.get("end")
                if not end:
                    continue
                rec = rows.setdefault(end, {"end": end})
                
                # Revenue
                rev = item.get("revenue") or item.get("totalRevenue") or item.get("Revenue")
                if rev is not None:
                    try:
                        rec["revenue"] = float(rev)
                    except:
                        pass
                
                # EPS Diluted
                eps = item.get("epsdiluted") or item.get("epsDiluted") or item.get("EPSDiluted")
                if eps is not None:
                    try:
                        rec["eps_diluted"] = float(eps)
                    except:
                        pass
    except Exception:
        pass
    
    # Also try earnings calendar for EPS if not found
    if not any("eps_diluted" in r for r in rows.values()):
        try:
            url = f"{base}/calendar/earnings?symbol={symbol}&from=2020-01-01&to=2100-01-01&token={api_key}"
            r = requests.get(url, timeout=timeout)
            if r.status_code == 200:
                js = r.json() or {}
                for it in (js.get("earningsCalendar") or []):
                    end = it.get("date") or it.get("period")
                    eps = it.get("epsActual") or it.get("reportedEPS")
                    if end and eps is not None:
                        rec = rows.setdefault(end, {"end": end})
                        try:
                            rec["eps_diluted"] = float(eps)
                        except:
                            pass
        except Exception:
            pass
    
    if not rows:
        return pd.DataFrame(columns=["end", "revenue", "eps_diluted"])
    
    df = pd.DataFrame(list(rows.values()))
    df = df.sort_values("end", ascending=False).drop_duplicates("end", keep="first")
    return df


def finnhub_as_reported_quarterly_financials(symbol: str, api_key: str, quarters_to_fetch: int = 12, timeout: int = 15) -> pd.DataFrame:
    """
    Fetch quarterly revenue and EPS from Finnhub As Reported SEC filings.
    
    This function uses Finnhub's SEC filings endpoint which provides actual 10-Q data.
    The data is reported as Year-to-Date (YTD) values, so we convert to quarterly by
    subtracting the previous quarter's YTD from the current quarter's YTD.
    
    Why this is needed:
    - Standard Finnhub API returns no quarterly data for some major companies (BLK, GOOGL, V)
    - yfinance only has ~5-6 quarters of history
    - This provides 12+ quarters of data directly from SEC filings
    
    The function:
    1. Fetches SEC quarterly filings from Finnhub
    2. Extracts Revenue YTD and calculates quarterly Revenue by subtraction
    3. For EPS, tries multiple approaches:
       a. If reported EPS is already quarterly (not YTD), use it directly
       b. Otherwise, calculate from Net Income / Shares (YTD-to-quarterly conversion)
    
    Special handling:
    - GOOGL: Uses reported EPS directly (no share count in filing)
    - V (Visa): Calculates EPS from Net Income/Shares (reported EPS is YTD cumulative)
    - BRK-B: Revenue only (Class A EPS not convertible)
    
    Returns DataFrame with columns: end, revenue, eps_diluted, source
    """
    if not api_key:
        return pd.DataFrame(columns=["end", "revenue", "eps_diluted", "source"])
    
    try:
        url = f"https://finnhub.io/api/v1/stock/financials-reported?symbol={symbol}&freq=quarterly&token={api_key}"
        r = requests.get(url, timeout=timeout)
        if r.status_code != 200:
            return pd.DataFrame(columns=["end", "revenue", "eps_diluted", "source"])
        
        data = r.json()
        reports = data.get("data", [])
        
        if not reports:
            return pd.DataFrame(columns=["end", "revenue", "eps_diluted", "source"])
        
        # Sort reports by fiscal year and quarter
        sorted_reports = sorted(reports, key=lambda x: (x.get("year", 0), x.get("quarter", 0)))
        
        # Extract YTD values for each quarter
        quarterly_ytd = []
        for report in sorted_reports:
            year = report.get("year")
            quarter = report.get("quarter")
            end_date = report.get("endDate", "")
            if " " in end_date:
                end_date = end_date.split(" ")[0]  # Clean up datetime format
            
            ic = report.get("report", {}).get("ic", [])
            
            # Extract values from income statement
            revenue_ytd = None
            net_income_ytd = None
            shares_diluted = None
            shares_basic = None
            eps_reported_ytd = None
            eps_basic_ytd = None  # Fallback for Class A shares (BRK-B)
            # Bank-specific revenue components
            net_interest_income_ytd = None
            noninterest_income_ytd = None
            
            for item in ic:
                concept = item.get("concept", "")
                value = item.get("value")
                
                # Revenue - try multiple XBRL concepts
                if revenue_ytd is None:
                    if concept in [
                        "us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax",
                        "us-gaap_Revenues",
                        "us-gaap_Revenue",
                        "us-gaap_TotalRevenuesAndOtherIncome",
                        "us-gaap_SalesRevenueNet",
                        "us-gaap_RevenueFromContractWithCustomerIncludingAssessedTax",
                        "us-gaap_InterestAndDividendIncomeOperating",  # For financial companies
                    ]:
                        if value is not None:
                            try:
                                revenue_ytd = float(value)
                            except (ValueError, TypeError):
                                pass
                
                # Bank-specific revenue: Net Interest Income + Noninterest Income
                # Banks like USB, JPM, BAC use these instead of standard Revenue
                if net_interest_income_ytd is None:
                    if concept in [
                        "us-gaap_InterestIncomeExpenseNet",
                        "us-gaap_NetInterestIncome",
                    ]:
                        if value is not None:
                            try:
                                net_interest_income_ytd = float(value)
                            except (ValueError, TypeError):
                                pass
                
                if noninterest_income_ytd is None:
                    if concept == "us-gaap_NoninterestIncome":
                        if value is not None:
                            try:
                                noninterest_income_ytd = float(value)
                            except (ValueError, TypeError):
                                pass
                
                # Net Income - for EPS calculation
                if net_income_ytd is None:
                    if concept in [
                        "us-gaap_ProfitLoss",
                        "us-gaap_NetIncomeLoss",
                        "us-gaap_NetIncomeLossAvailableToCommonStockholdersBasic",
                    ]:
                        if value is not None:
                            try:
                                net_income_ytd = float(value)
                            except (ValueError, TypeError):
                                pass
                
                # Diluted shares - for EPS calculation
                if shares_diluted is None:
                    if concept == "us-gaap_WeightedAverageNumberOfDilutedSharesOutstanding":
                        if value is not None:
                            try:
                                shares_diluted = float(value)
                            except (ValueError, TypeError):
                                pass
                
                # Basic shares - fallback for EPS calculation
                if shares_basic is None:
                    if concept == "us-gaap_WeightedAverageNumberOfSharesOutstandingBasic":
                        if value is not None:
                            try:
                                shares_basic = float(value)
                            except (ValueError, TypeError):
                                pass
                
                # Reported EPS - use directly if share count is unavailable
                if eps_reported_ytd is None:
                    if concept == "us-gaap_EarningsPerShareDiluted":
                        if value is not None:
                            try:
                                eps_reported_ytd = float(value)
                            except (ValueError, TypeError):
                                pass
                
                # Basic EPS fallback (for BRK-B which only reports Class A EPS)
                if eps_basic_ytd is None:
                    if concept == "us-gaap_EarningsPerShareBasic":
                        if value is not None:
                            try:
                                eps_basic_ytd = float(value)
                            except (ValueError, TypeError):
                                pass
            
            # Special handling for banks: If no standard revenue, use NetInterestIncome + NoninterestIncome
            if revenue_ytd is None and (net_interest_income_ytd is not None or noninterest_income_ytd is not None):
                revenue_ytd = (net_interest_income_ytd or 0) + (noninterest_income_ytd or 0)
            
            # Use diluted shares if available, otherwise basic shares
            shares = shares_diluted if shares_diluted is not None else shares_basic
            
            quarterly_ytd.append({
                "year": year,
                "quarter": quarter,
                "end_date": end_date,
                "revenue_ytd": revenue_ytd,
                "net_income_ytd": net_income_ytd,
                "shares": shares,
                "eps_reported_ytd": eps_reported_ytd,
                "eps_basic_ytd": eps_basic_ytd,
                "net_interest_income_ytd": net_interest_income_ytd,
                "noninterest_income_ytd": noninterest_income_ytd,
            })
        
        # Detect if EPS is quarterly or YTD based on pattern
        # If Q1 EPS is very different from Q2 EPS (Q2 should be ~2x Q1 if YTD),
        # then EPS is likely already quarterly
        eps_is_ytd = True  # Default assumption
        if len(quarterly_ytd) >= 3:
            # Find Q1 and Q2 in same fiscal year
            for i, q in enumerate(quarterly_ytd):
                if q["quarter"] == 1 and q["eps_reported_ytd"] is not None:
                    for j in range(i + 1, len(quarterly_ytd)):
                        q2 = quarterly_ytd[j]
                        if q2["year"] == q["year"] and q2["quarter"] == 2 and q2["eps_reported_ytd"] is not None:
                            ratio = q2["eps_reported_ytd"] / q["eps_reported_ytd"] if q["eps_reported_ytd"] != 0 else 0
                            # If ratio is ~2x, it's YTD; if ~1x, it's quarterly
                            if 0.5 < ratio < 1.5:
                                eps_is_ytd = False  # EPS is already quarterly
                            break
                    break
        
        # Convert YTD to Quarterly values
        rows = []
        for i, curr in enumerate(quarterly_ytd):
            if not curr["end_date"]:
                continue
            
            # Revenue: Convert YTD to quarterly
            quarterly_revenue = None
            if curr["revenue_ytd"] is not None:
                if curr["quarter"] == 1:
                    # Q1 YTD = Q1 (first quarter of fiscal year)
                    quarterly_revenue = curr["revenue_ytd"]
                else:
                    # Find previous quarter in same fiscal year
                    for j in range(i - 1, -1, -1):
                        prev = quarterly_ytd[j]
                        if prev["year"] == curr["year"] and prev["quarter"] == curr["quarter"] - 1:
                            if prev["revenue_ytd"] is not None:
                                quarterly_revenue = curr["revenue_ytd"] - prev["revenue_ytd"]
                            break
            
            # EPS: Multiple strategies depending on data availability
            quarterly_eps = None
            
            # Strategy 1: If no share count, use reported EPS (works for GOOGL)
            if curr["shares"] is None and curr["eps_reported_ytd"] is not None:
                if eps_is_ytd:
                    # Convert YTD EPS to quarterly
                    if curr["quarter"] == 1:
                        quarterly_eps = curr["eps_reported_ytd"]
                    else:
                        for j in range(i - 1, -1, -1):
                            prev = quarterly_ytd[j]
                            if prev["year"] == curr["year"] and prev["quarter"] == curr["quarter"] - 1:
                                if prev["eps_reported_ytd"] is not None:
                                    quarterly_eps = curr["eps_reported_ytd"] - prev["eps_reported_ytd"]
                                break
                else:
                    # EPS is already quarterly
                    quarterly_eps = curr["eps_reported_ytd"]
            
            # Strategy 2: Calculate from Net Income / Shares (preferred when shares available)
            elif curr["net_income_ytd"] is not None and curr["shares"]:
                # Convert Net Income YTD to quarterly
                quarterly_net_income = None
                if curr["quarter"] == 1:
                    quarterly_net_income = curr["net_income_ytd"]
                else:
                    for j in range(i - 1, -1, -1):
                        prev = quarterly_ytd[j]
                        if prev["year"] == curr["year"] and prev["quarter"] == curr["quarter"] - 1:
                            if prev["net_income_ytd"] is not None:
                                quarterly_net_income = curr["net_income_ytd"] - prev["net_income_ytd"]
                            break
                
                # Calculate EPS = Net Income / Diluted Shares
                if quarterly_net_income is not None:
                    quarterly_eps = quarterly_net_income / curr["shares"]
            
            # Strategy 3: Use Basic EPS for BRK-B (Class A EPS / 1500 = Class B EPS)
            # Berkshire Hathaway only reports Class A shares and EPS, but BRK-B = BRK-A / 1500
            if quarterly_eps is None and curr["eps_basic_ytd"] is not None:
                # Check if this is likely a Class A share situation (EPS > $1000)
                # BRK-A has EPS in thousands, need to convert to BRK-B equivalent
                if abs(curr["eps_basic_ytd"]) > 1000:  # Class A shares
                    brk_class_a_to_b_ratio = 1500  # 1 BRK-A = 1500 BRK-B
                    if eps_is_ytd:
                        if curr["quarter"] == 1:
                            quarterly_eps = curr["eps_basic_ytd"] / brk_class_a_to_b_ratio
                        else:
                            for j in range(i - 1, -1, -1):
                                prev = quarterly_ytd[j]
                                if prev["year"] == curr["year"] and prev["quarter"] == curr["quarter"] - 1:
                                    if prev.get("eps_basic_ytd") is not None:
                                        quarterly_eps = (curr["eps_basic_ytd"] - prev["eps_basic_ytd"]) / brk_class_a_to_b_ratio
                                    break
                    else:
                        quarterly_eps = curr["eps_basic_ytd"] / brk_class_a_to_b_ratio
                else:
                    # Normal Basic EPS, use as-is (YTD to quarterly conversion)
                    if eps_is_ytd:
                        if curr["quarter"] == 1:
                            quarterly_eps = curr["eps_basic_ytd"]
                        else:
                            for j in range(i - 1, -1, -1):
                                prev = quarterly_ytd[j]
                                if prev["year"] == curr["year"] and prev["quarter"] == curr["quarter"] - 1:
                                    if prev.get("eps_basic_ytd") is not None:
                                        quarterly_eps = curr["eps_basic_ytd"] - prev["eps_basic_ytd"]
                                    break
                    else:
                        quarterly_eps = curr["eps_basic_ytd"]
            
            if quarterly_revenue is not None or quarterly_eps is not None:
                rows.append({
                    "end": curr["end_date"],
                    "revenue": quarterly_revenue,
                    "eps_diluted": quarterly_eps,
                    "source": "finnhub_as_reported",
                })
        
        if not rows:
            return pd.DataFrame(columns=["end", "revenue", "eps_diluted", "source"])
        
        df = pd.DataFrame(rows)
        df = df.sort_values("end", ascending=False).drop_duplicates("end", keep="first")
        return df.head(quarters_to_fetch)
        
    except Exception as e:
        print(f"[warn] Finnhub As Reported quarterly error for {symbol}: {e}")
        return pd.DataFrame(columns=["end", "revenue", "eps_diluted", "source"])


# ============================================================================
# Multi-Source Validation (Consensus-Based)
# ============================================================================

def _values_match(v1: float, v2: float, tolerance_pct: float) -> bool:
    """Check if two values are within tolerance percentage of each other."""
    if v1 == 0 and v2 == 0:
        return True
    if v1 == 0 or v2 == 0:
        return False
    max_val = max(abs(v1), abs(v2))
    diff_pct = abs(v1 - v2) / max_val * 100
    return diff_pct <= tolerance_pct


def validate_across_sources(
    source_values: Dict[str, Optional[float]],
    tolerance_pct: float = 5.0
) -> ValidationResult:
    """
    Cross-validate a value using consensus-based voting.
    
    Logic:
    - If 2+ sources agree (within tolerance): Use the consensus value, status = "validated"
    - If all sources differ: Average all values, status = "discrepancy"
    - If only 1 source: Use that value, status = "single_source"
    
    Args:
        source_values: Dict mapping source name to value (e.g., {"yfinance": 10.2, "alphavantage": 10.3, "fmp": 10.2})
        tolerance_pct: Maximum percentage difference to consider values as "matching" (default 5%)
    
    Returns:
        ValidationResult with consensus value and validation status
    """
    # Filter out None values
    valid_sources = {k: v for k, v in source_values.items() if v is not None}
    
    if not valid_sources:
        return ValidationResult(status="none")
    
    if len(valid_sources) == 1:
        source_name, value = list(valid_sources.items())[0]
        return ValidationResult(
            value=value,
            status="single_source",
            sources_compared=[source_name],
            source_values=valid_sources
        )
    
    # Calculate overall discrepancy for reporting
    values = list(valid_sources.values())
    max_val = max(values)
    min_val = min(values)
    discrepancy_pct = ((max_val - min_val) / max_val) * 100 if max_val > 0 else 0
    
    # With only 2 sources, check if they match
    if len(valid_sources) == 2:
        source_names = list(valid_sources.keys())
        v1, v2 = values[0], values[1]
        if _values_match(v1, v2, tolerance_pct):
            return ValidationResult(
                value=v1,  # Use first source
                status="validated",
                sources_compared=source_names,
                source_values=valid_sources,
                discrepancy_pct=round(discrepancy_pct, 2)
            )
        else:
            # 2 sources disagree - average and flag
            avg_value = sum(values) / len(values)
            return ValidationResult(
                value=avg_value,
                status="discrepancy",
                sources_compared=source_names,
                source_values=valid_sources,
                discrepancy_pct=round(discrepancy_pct, 2)
            )
    
    # With 3+ sources, find consensus (2+ sources that agree)
    source_names = list(valid_sources.keys())
    
    # Check all pairs to find consensus groups
    for i, (name1, val1) in enumerate(valid_sources.items()):
        matching_sources = [name1]
        matching_values = [val1]
        
        for j, (name2, val2) in enumerate(valid_sources.items()):
            if i != j and _values_match(val1, val2, tolerance_pct):
                matching_sources.append(name2)
                matching_values.append(val2)
        
        # If 2+ sources agree, we have consensus
        if len(matching_sources) >= 2:
            # Use the average of matching values for precision
            consensus_value = sum(matching_values) / len(matching_values)
            return ValidationResult(
                value=consensus_value,
                status="validated",
                sources_compared=source_names,
                source_values=valid_sources,
                discrepancy_pct=round(discrepancy_pct, 2)
            )
    
    # No consensus found - all sources differ, average and flag as discrepancy
    avg_value = sum(values) / len(values)
    return ValidationResult(
        value=avg_value,
        status="discrepancy",
        sources_compared=source_names,
        source_values=valid_sources,
        discrepancy_pct=round(discrepancy_pct, 2)
    )


def gather_all_fallback_data(
    ticker: str, 
    config,
    years_to_fetch: int = 6
) -> Dict[str, pd.DataFrame]:
    """
    Fetch data from fallback sources in priority order.
    
    Priority order:
    1. yfinance: Free, no API key required (primary fallback)
    2. Alpha Vantage: Requires ALPHA_VANTAGE_API_KEY (secondary fallback)
    3. Finnhub As Reported: Free SEC filings data (tertiary fallback, excellent for banks/REITs)
    
    FMP is disabled by default due to API limits (250 calls/day).
    Standard Finnhub is reserved for quarterly fallback only.
    
    Returns dict mapping source name to DataFrame with columns: end, revenue, eps_diluted
    """
    all_sources = {}
    
    # yfinance (primary fallback - free, no API key needed)
    if config.yfinance_enabled:
        yf_df = yfinance_annual_financials(ticker, years_to_fetch)
        if not yf_df.empty:
            all_sources["yfinance"] = yf_df
    
    # Alpha Vantage (secondary fallback)
    if config.alphavantage_enabled and config.alphavantage_api_key:
        av_df = alphavantage_annual_financials(ticker, config.alphavantage_api_key, years_to_fetch)
        if not av_df.empty:
            all_sources["alphavantage"] = av_df
    
    # Finnhub As Reported (tertiary fallback - free, uses SEC XBRL data)
    # Excellent for banks, REITs, and financial companies with non-standard revenue concepts
    if config.finnhub_as_reported_enabled and config.finnhub_api_key:
        far_df = finnhub_as_reported_annual_financials(ticker, config.finnhub_api_key, years_to_fetch)
        if not far_df.empty:
            all_sources["finnhub_as_reported"] = far_df
    
    # FMP is optional - disabled by default due to 250 calls/day limit
    # Only enable if you have a premium FMP account
    if config.fmp_enabled and config.fmp_api_key:
        fmp_df = fmp_annual_financials(ticker, config.fmp_api_key, years_to_fetch)
        if not fmp_df.empty:
            all_sources["fmp"] = fmp_df
    
    return all_sources


def get_fallback_value(
    year_date: str,
    all_sources: Dict[str, pd.DataFrame],
    metric: str,  # "revenue" or "eps_diluted"
) -> ValidationResult:
    """
    Get a value from fallback sources using priority order.
    
    Priority: yfinance > alphavantage > finnhub_as_reported > fmp
    
    If only one source has data, use it (status = "single_source").
    If multiple sources have data and agree (within 5%), use yfinance (status = "validated").
    If multiple sources disagree (>5% diff), use yfinance but flag as "discrepancy".
    
    Args:
        year_date: Fiscal year end date (e.g., "2024-12-31")
        all_sources: Dict from gather_all_fallback_data()
        metric: "revenue" or "eps_diluted"
    
    Returns:
        ValidationResult with value and status
    """
    year_prefix = year_date[:4]  # Extract year for fuzzy matching
    source_values = {}
    
    # Collect values from all sources
    for source_name, df in all_sources.items():
        # Try exact match first
        match = df[df["end"] == year_date]
        if match.empty:
            # Try year match (handles different fiscal year endings)
            match = df[df["end"].str.startswith(year_prefix)]
        
        if not match.empty:
            val = match.iloc[0].get(metric)
            if pd.notna(val):
                source_values[source_name] = float(val)
    
    if not source_values:
        return ValidationResult(status="none")
    
    # Priority order for selecting the value
    # yfinance first (most reliable for standard companies)
    # alphavantage second (good coverage)
    # finnhub_as_reported third (excellent for banks/REITs, uses raw SEC data)
    # fmp last (rate limited)
    priority_order = ["yfinance", "alphavantage", "finnhub_as_reported", "fmp"]
    selected_source = None
    selected_value = None
    
    for source in priority_order:
        if source in source_values:
            selected_source = source
            selected_value = source_values[source]
            break
    
    if selected_value is None:
        return ValidationResult(status="none")
    
    # Determine validation status
    source_names = list(source_values.keys())
    
    if len(source_values) == 1:
        # Only one source has data
        return ValidationResult(
            value=selected_value,
            status="single_source",
            sources_compared=source_names,
            source_values=source_values
        )
    
    # Multiple sources - check if they agree
    values = list(source_values.values())
    max_val = max(values)
    min_val = min(values)
    discrepancy_pct = ((max_val - min_val) / max_val) * 100 if max_val > 0 else 0
    
    if discrepancy_pct <= 5.0:
        # Sources agree - use primary source (yfinance)
        return ValidationResult(
            value=selected_value,
            status="validated",
            sources_compared=source_names,
            source_values=source_values,
            discrepancy_pct=round(discrepancy_pct, 2)
        )
    else:
        # Sources disagree - use primary source but flag as discrepancy
        return ValidationResult(
            value=selected_value,
            status="discrepancy",
            sources_compared=source_names,
            source_values=source_values,
            discrepancy_pct=round(discrepancy_pct, 2)
        )


def cross_validate_fallback_year(
    year_date: str,
    all_sources: Dict[str, pd.DataFrame],
    metric: str,  # "revenue" or "eps_diluted"
    tolerance_pct: float = 5.0
) -> ValidationResult:
    """
    Get a value from fallback sources with status tracking.
    
    This is a wrapper around get_fallback_value() for backward compatibility.
    Uses yfinance as primary, Alpha Vantage as secondary.
    """
    return get_fallback_value(year_date, all_sources, metric)


# ============================================================================
# yfinance Fallback (Annual)
# ============================================================================

def yfinance_annual_financials(symbol: str, years_to_fetch: int = 6) -> pd.DataFrame:
    """
    Fetch annual revenue and EPS from Yahoo Finance.
    Returns DataFrame with columns: end, revenue, eps_diluted, source
    """
    try:
        import yfinance as yf
    except ImportError:
        print(f"[warn] yfinance not installed, skipping yfinance fallback")
        return pd.DataFrame(columns=["end", "revenue", "eps_diluted", "source"])
    
    try:
        ticker = yf.Ticker(symbol)
        income_stmt = ticker.income_stmt
        
        if income_stmt is None or income_stmt.empty:
            return pd.DataFrame(columns=["end", "revenue", "eps_diluted", "source"])
        
        rows = []
        for col in income_stmt.columns[:years_to_fetch]:
            # col is a Timestamp for the fiscal year end
            end_date = col.strftime("%Y-%m-%d")
            
            # Revenue - try multiple field names
            revenue = None
            for rev_field in ["Total Revenue", "Revenue", "Total Operating Revenue", "Gross Revenue"]:
                if rev_field in income_stmt.index:
                    val = income_stmt.loc[rev_field, col]
                    if pd.notna(val):
                        revenue = float(val)
                        break
            
            # EPS Diluted - try multiple field names
            eps = None
            for eps_field in ["Diluted EPS", "Basic EPS", "EPS"]:
                if eps_field in income_stmt.index:
                    val = income_stmt.loc[eps_field, col]
                    if pd.notna(val):
                        eps = float(val)
                        break
            
            if revenue is not None or eps is not None:
                rows.append({
                    "end": end_date,
                    "revenue": revenue,
                    "eps_diluted": eps,
                    "source": "yfinance"
                })
        
        if not rows:
            return pd.DataFrame(columns=["end", "revenue", "eps_diluted", "source"])
        
        df = pd.DataFrame(rows)
        df = df.sort_values("end", ascending=False).drop_duplicates("end", keep="first")
        return df
        
    except Exception as e:
        print(f"[warn] yfinance error for {symbol}: {e}")
        return pd.DataFrame(columns=["end", "revenue", "eps_diluted", "source"])


# ============================================================================
# yfinance Fallback (Quarterly)
# ============================================================================

def yfinance_quarterly_financials(symbol: str, quarters_to_fetch: int = 8) -> pd.DataFrame:
    """
    Fetch quarterly revenue and EPS from Yahoo Finance.
    Returns DataFrame with columns: end, revenue, eps_diluted, source
    
    This is a key fallback for quarterly data when SEC EDGAR is missing values.
    yfinance provides quarterly data for most companies including:
    - Revenue (Total Revenue)
    - Diluted EPS
    
    Example companies that benefit: GOOGL, V (Visa), BRK-B
    """
    try:
        import yfinance as yf
    except ImportError:
        print(f"[warn] yfinance not installed, skipping yfinance quarterly fallback")
        return pd.DataFrame(columns=["end", "revenue", "eps_diluted", "source"])
    
    try:
        ticker = yf.Ticker(symbol)
        q_income = ticker.quarterly_income_stmt
        
        if q_income is None or q_income.empty:
            return pd.DataFrame(columns=["end", "revenue", "eps_diluted", "source"])
        
        rows = []
        for col in q_income.columns[:quarters_to_fetch]:
            # col is a Timestamp for the fiscal quarter end
            end_date = col.strftime("%Y-%m-%d")
            
            # Revenue - try multiple field names
            revenue = None
            for rev_field in ["Total Revenue", "Revenue", "Total Operating Revenue", "Gross Revenue"]:
                if rev_field in q_income.index:
                    val = q_income.loc[rev_field, col]
                    if pd.notna(val):
                        revenue = float(val)
                        break
            
            # EPS Diluted - try multiple field names
            eps = None
            for eps_field in ["Diluted EPS", "Basic EPS", "EPS"]:
                if eps_field in q_income.index:
                    val = q_income.loc[eps_field, col]
                    if pd.notna(val):
                        eps = float(val)
                        break
            
            if revenue is not None or eps is not None:
                rows.append({
                    "end": end_date,
                    "revenue": revenue,
                    "eps_diluted": eps,
                    "source": "yfinance"
                })
        
        if not rows:
            return pd.DataFrame(columns=["end", "revenue", "eps_diluted", "source"])
        
        df = pd.DataFrame(rows)
        df = df.sort_values("end", ascending=False).drop_duplicates("end", keep="first")
        return df
        
    except Exception as e:
        print(f"[warn] yfinance quarterly error for {symbol}: {e}")
        return pd.DataFrame(columns=["end", "revenue", "eps_diluted", "source"])


# ============================================================================
# Alpha Vantage Fallback (Annual)
# ============================================================================

def alphavantage_annual_financials(symbol: str, api_key: str, years_to_fetch: int = 6, timeout: int = 15) -> pd.DataFrame:
    """
    Fetch annual revenue and EPS from Alpha Vantage.
    Returns DataFrame with columns: end, revenue, eps_diluted, source
    """
    if not api_key:
        return pd.DataFrame(columns=["end", "revenue", "eps_diluted", "source"])
    
    base = "https://www.alphavantage.co/query"
    rows = {}
    
    # Income statement for revenue and EPS
    try:
        url = f"{base}?function=INCOME_STATEMENT&symbol={symbol}&apikey={api_key}"
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            js = r.json()
            for report in (js.get("annualReports") or [])[:years_to_fetch]:
                fiscal_end = report.get("fiscalDateEnding")
                if not fiscal_end:
                    continue
                
                rec = rows.setdefault(fiscal_end, {"end": fiscal_end, "source": "alphavantage"})
                
                # Revenue
                rev = report.get("totalRevenue")
                if rev and rev != "None":
                    try:
                        rec["revenue"] = float(rev)
                    except:
                        pass
                
                # EPS (Alpha Vantage earnings endpoint)
    except Exception as e:
        print(f"[warn] Alpha Vantage income statement error for {symbol}: {e}")
    
    # Also fetch earnings for EPS
    try:
        url = f"{base}?function=EARNINGS&symbol={symbol}&apikey={api_key}"
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            js = r.json()
            for report in (js.get("annualEarnings") or [])[:years_to_fetch]:
                fiscal_end = report.get("fiscalDateEnding")
                if not fiscal_end:
                    continue
                
                rec = rows.setdefault(fiscal_end, {"end": fiscal_end, "source": "alphavantage"})
                
                eps = report.get("reportedEPS")
                if eps and eps != "None":
                    try:
                        rec["eps_diluted"] = float(eps)
                    except:
                        pass
    except Exception as e:
        print(f"[warn] Alpha Vantage earnings error for {symbol}: {e}")
    
    if not rows:
        return pd.DataFrame(columns=["end", "revenue", "eps_diluted", "source"])
    
    df = pd.DataFrame(list(rows.values()))
    df = df.sort_values("end", ascending=False).drop_duplicates("end", keep="first")
    
    # Filter out records where revenue is NULL - these are typically TTM/LTM values
    # from the EARNINGS endpoint that don't have corresponding annual revenue data.
    # This prevents phantom records like "2025-09-30" with EPS but no revenue.
    df = df[df["revenue"].notna()].copy()
    
    return df


# ============================================================================
# Finnhub Annual Fallback
# ============================================================================

def finnhub_annual_financials(symbol: str, api_key: str, years_to_fetch: int = 6, timeout: int = 15) -> pd.DataFrame:
    """
    Fetch annual revenue and EPS from Finnhub.
    Returns DataFrame with columns: end, revenue, eps_diluted, source
    """
    if not api_key:
        return pd.DataFrame(columns=["end", "revenue", "eps_diluted", "source"])
    
    base = "https://finnhub.io/api/v1"
    rows = {}
    
    # Income statement for revenue (annual frequency)
    try:
        url = f"{base}/stock/financials?symbol={symbol}&statement=ic&freq=annual&token={api_key}"
        r = requests.get(url, timeout=timeout)
        if r.status_code == 200:
            js = r.json() or {}
            for item in (js.get("data") or [])[:years_to_fetch]:
                end = item.get("period") or item.get("endDate") or item.get("end")
                if not end:
                    continue
                rec = rows.setdefault(end, {"end": end, "source": "finnhub"})
                
                # Revenue
                rev = item.get("revenue") or item.get("totalRevenue") or item.get("Revenue")
                if rev is not None:
                    try:
                        rec["revenue"] = float(rev)
                    except:
                        pass
                
                # EPS Diluted
                eps = item.get("epsdiluted") or item.get("epsDiluted") or item.get("EPSDiluted")
                if eps is not None:
                    try:
                        rec["eps_diluted"] = float(eps)
                    except:
                        pass
    except Exception:
        pass
    
    if not rows:
        return pd.DataFrame(columns=["end", "revenue", "eps_diluted", "source"])
    
    df = pd.DataFrame(list(rows.values()))
    df = df.sort_values("end", ascending=False).drop_duplicates("end", keep="first")
    return df


# ============================================================================
# Finnhub "Financials As Reported" - SEC Filings Data (FREE endpoint)
# ============================================================================

def finnhub_as_reported_annual_financials(symbol: str, api_key: str, years_to_fetch: int = 6, timeout: int = 15) -> pd.DataFrame:
    """
    Fetch annual revenue and EPS from Finnhub's "Financials As Reported" endpoint.
    
    This endpoint provides raw SEC filing data (10-K/10-Q) parsed directly from 
    EDGAR XBRL filings. It's FREE and has no rate limits beyond standard Finnhub limits.
    
    This is particularly valuable for:
    - Financial sector companies (banks, insurance) that use different revenue concepts
    - REITs that use rental income instead of standard revenue
    - Companies where standardized APIs fail to map fields correctly
    
    The function handles multiple revenue/EPS concept names used by different industries:
    - Standard companies: us-gaap_Revenue, us-gaap_RevenueFromContractWithCustomer
    - Banks: us-gaap_InterestAndDividendIncomeOperating + us-gaap_NoninterestIncome
    - REITs: Revenues, OperatingLeaseLeaseIncome
    
    Returns DataFrame with columns: end, revenue, eps_diluted, source
    """
    if not api_key:
        return pd.DataFrame(columns=["end", "revenue", "eps_diluted", "source"])
    
    url = f"https://finnhub.io/api/v1/stock/financials-reported?symbol={symbol}&freq=annual&token={api_key}"
    
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code != 200:
            return pd.DataFrame(columns=["end", "revenue", "eps_diluted", "source"])
        
        data = r.json()
        if not data.get("data"):
            return pd.DataFrame(columns=["end", "revenue", "eps_diluted", "source"])
        
        rows = []
        
        # Process only 10-K filings (annual reports)
        filings = [f for f in data["data"] if f.get("form") == "10-K"]
        filings = sorted(filings, key=lambda x: x.get("year", 0), reverse=True)[:years_to_fetch]
        
        for filing in filings:
            year = filing.get("year")
            report = filing.get("report", {})
            
            if not report or "ic" not in report:
                continue
            
            ic = report["ic"]  # Income statement is a list of concept/value dicts
            
            # Build lookup dict for quick access
            ic_lookup = {}
            if isinstance(ic, list):
                for item in ic:
                    concept = item.get("concept", "").lower()
                    value = item.get("value")
                    if concept and value is not None:
                        ic_lookup[concept] = value
            
            # Extract revenue - try multiple concepts (industry-specific)
            revenue = None
            
            # Standard revenue concepts (most companies)
            revenue_concepts = [
                "us-gaap_revenuefromcontractwithcustomerexcludingassessedtax",
                "us-gaap_revenuefromcontractwithcustomerincludingassessedtax",
                "us-gaap_revenues",
                "revenues",
                "us-gaap_totalrevenue",
                "us-gaap_salesrevenuenet",
                "us-gaap_revenuesnetofinterestexpense",  # Banks
                "us-gaap_interestincome",  # Financial services
            ]
            
            for concept in revenue_concepts:
                if concept in ic_lookup:
                    revenue = ic_lookup[concept]
                    break
            
            # Special handling for banks: Interest + Non-interest income
            if revenue is None:
                interest_income = ic_lookup.get("us-gaap_interestanddividendincomeoperating", 0)
                noninterest_income = ic_lookup.get("us-gaap_noninterestincome", 0)
                if interest_income or noninterest_income:
                    revenue = (interest_income or 0) + (noninterest_income or 0)
            
            # Special handling for REITs: Operating lease income
            if revenue is None:
                lease_income = ic_lookup.get("operatingleaselearincome") or ic_lookup.get("revenues")
                if lease_income:
                    revenue = lease_income
            
            # Extract EPS - first try direct EPS fields, then calculate from net income / shares
            eps_diluted = None
            
            # Direct EPS fields (preferred)
            eps_concepts = [
                "us-gaap_earningspersharediluted",
                "earningspersharediluted",
                "us-gaap_earningspersharebasicanddiluted",
                "earningspersharebasicanddiluted",
                "us-gaap_incomelossattributabletoparentperdilutedshare",
                "us-gaap_earningspersharebasic",
                "earningspersharebasic",
            ]
            
            for concept in eps_concepts:
                if concept in ic_lookup:
                    eps_diluted = ic_lookup[concept]
                    break
            
            # If no direct EPS, calculate from net income and shares
            if eps_diluted is None:
                # Extract net income
                net_income = None
                net_income_concepts = [
                    "us-gaap_netincomeloss",
                    "us-gaap_profitloss",
                    "profitloss",
                    "us-gaap_netincomelossavailabletocommonstockholdersbasic",
                    "us-gaap_netincomelossattributabletoparent",
                ]
                
                for concept in net_income_concepts:
                    if concept in ic_lookup:
                        net_income = ic_lookup[concept]
                        break
                
                # Extract diluted shares for EPS calculation
                shares_diluted = None
                shares_concepts = [
                    "us-gaap_weightedaveragenumberofdilutedsharesoutstanding",
                    "us-gaap_weightedaveragenumberofsharesoutstandingdiluted",
                    "us-gaap_weightedaveragenumberofsharesoutstandingbasic",
                ]
                
                for concept in shares_concepts:
                    if concept in ic_lookup:
                        shares_diluted = ic_lookup[concept]
                        break
                
                # Calculate EPS if we have net income and shares
                if net_income is not None and shares_diluted and shares_diluted > 0:
                    eps_diluted = net_income / shares_diluted
            
            # Create fiscal year end date
            fiscal_year_end = f"{year}-12-31"  # Default to Dec 31
            
            # Try to get more accurate end date from filing
            if filing.get("endDate"):
                fiscal_year_end = filing["endDate"][:10]  # Take YYYY-MM-DD part
            
            if revenue is not None or eps_diluted is not None:
                rows.append({
                    "end": fiscal_year_end,
                    "revenue": revenue,
                    "eps_diluted": eps_diluted,
                    "source": "finnhub_as_reported"
                })
        
        if not rows:
            return pd.DataFrame(columns=["end", "revenue", "eps_diluted", "source"])
        
        df = pd.DataFrame(rows)
        df = df.sort_values("end", ascending=False).drop_duplicates("end", keep="first")
        return df
        
    except Exception as e:
        print(f"[warn] Finnhub As Reported error for {symbol}: {e}")
        return pd.DataFrame(columns=["end", "revenue", "eps_diluted", "source"])


# ============================================================================
# Financial Modeling Prep (FMP) - Primary Validation Source
# ============================================================================

def fmp_annual_financials(symbol: str, api_key: str, years_to_fetch: int = 6, timeout: int = 15) -> pd.DataFrame:
    """
    Fetch annual revenue and EPS from Financial Modeling Prep API.
    
    FMP serves as the final fallback in the data source chain. It provides 5 years
    of annual data for most major tickers on the free tier.
    
    Free Tier Limitations:
    - 250 API calls/day
    - Some tickers require premium (402 error) - silently skipped
    - Coverage: ~90% of SP100, excludes some mid-cap and specialty companies
    
    Uses the /stable/ API endpoint (v2024+).
    
    Returns DataFrame with columns: end, revenue, eps_diluted, source
    """
    if not api_key:
        return pd.DataFrame(columns=["end", "revenue", "eps_diluted", "source"])
    
    base = "https://financialmodelingprep.com/stable"
    rows = {}
    
    try:
        # Income statement endpoint provides revenue, net income, and EPS
        url = f"{base}/income-statement?symbol={symbol}&apikey={api_key}"
        r = requests.get(url, timeout=timeout)
        
        if r.status_code == 200:
            data = r.json()
            
            # Response is a list of annual reports, most recent first
            for item in (data or [])[:years_to_fetch]:
                # Only process annual (FY) periods
                period = item.get("period", "")
                if period != "FY":
                    continue
                
                # Get fiscal year end date
                end = item.get("date")  # Format: "2025-09-30"
                if not end:
                    continue
                
                rec = rows.setdefault(end, {"end": end, "source": "fmp"})
                
                # Revenue
                rev = item.get("revenue")
                if rev is not None:
                    try:
                        rec["revenue"] = float(rev)
                    except:
                        pass
                
                # EPS Diluted
                eps = item.get("epsDiluted")
                if eps is not None:
                    try:
                        rec["eps_diluted"] = float(eps)
                    except:
                        pass
        elif r.status_code == 402:
            # Premium required for this ticker - silently skip (expected for some tickers)
            pass
        elif r.status_code == 429:
            print(f"[warn] FMP rate limit reached for {symbol}")
        elif r.status_code >= 500:
            print(f"[warn] FMP server error for {symbol}: HTTP {r.status_code}")
        # Note: 4xx errors (except 402/429) are silently skipped as they indicate
        # the ticker is not available on FMP free tier
            
    except Exception as e:
        print(f"[warn] FMP error for {symbol}: {e}")
    
    if not rows:
        return pd.DataFrame(columns=["end", "revenue", "eps_diluted", "source"])
    
    df = pd.DataFrame(list(rows.values()))
    df = df.sort_values("end", ascending=False).drop_duplicates("end", keep="first")
    return df


# ============================================================================
# Data Extraction Helpers
# ============================================================================

def is_annual_10k(row: dict) -> bool:
    """
    Check if a row is from an annual 10-K filing with full-year duration.
    
    This filters out restated quarterly values that appear in 10-K filings.
    A true annual record should have a period duration of approximately 12 months
    (at least 300 days to account for variations).
    """
    form = str(row.get("form", "")).upper()
    fp = str(row.get("fp", "")).upper()
    
    # Must be 10-K form with FY fiscal period
    if not (form.startswith("10-K") and (fp in ("FY", "") or fp.startswith("Q4"))):
        return False
    
    # Additionally check period duration (start to end)
    # Annual reports should cover ~12 months (at least 300 days)
    start = row.get("start")
    end = row.get("end")
    if start and end:
        try:
            from datetime import datetime
            start_dt = datetime.strptime(start, "%Y-%m-%d")
            end_dt = datetime.strptime(end, "%Y-%m-%d")
            days = (end_dt - start_dt).days
            # Must be at least 300 days (covers ~10-12 month fiscal years)
            if days < 300:
                return False
        except:
            pass
    
    return True


def is_quarterly_10q(row: dict) -> bool:
    """Check if a row is from a quarterly 10-Q filing."""
    form = str(row.get("form", "")).upper()
    fp = str(row.get("fp", "")).upper()
    return form.startswith("10-Q") and fp.startswith("Q")


def _is_eps_unit(k: str) -> bool:
    """Check if unit key is for per-share metrics."""
    s = k.lower().replace(" ", "").replace("-", "").replace("_", "")
    has_share = any(x in s for x in ["share", "shares", "shr", "shs", "/sh", "pershare"])
    has_usd = "usd" in s or "iso4217:usd" in s
    return has_share and has_usd


def _dedupe_by_end(rows: List[dict]) -> List[dict]:
    """Keep only the latest filing for each fiscal period end."""
    by_end = {}
    for r in rows:
        end = r.get("end")
        if not end:
            continue
        cur = by_end.get(end)
        if cur is None or r.get("filed", "") >= cur.get("filed", ""):
            by_end[end] = r
    
    result = sorted(by_end.values(), key=lambda x: x.get("end", ""), reverse=True)
    return result


def extract_concept_values(
    companyfacts: dict,
    concept_names: List[str],
    is_eps: bool = False,
    filter_func=None
) -> List[dict]:
    """
    Extract values for a list of concept names, selecting the concept with 
    the most recent data (not first match).
    
    This fixes issues where older concepts (like RevenueFromContractWithCustomer
    ExcludingAssessedTax) are listed first but have outdated data, while newer
    concepts (like Revenues) have current data.
    
    Returns list of {end, val, concept, filed} dicts.
    """
    facts = companyfacts.get("facts", {}) or {}
    
    # Collect data from ALL matching concepts, then pick best one
    all_concept_results = []
    
    for taxonomy in ("us-gaap", "dei"):
        sec = facts.get(taxonomy, {}) or {}
        for concept_name in concept_names:
            if concept_name not in sec:
                continue
            
            node = sec[concept_name]
            units = node.get("units", {}) or {}
            
            if is_eps:
                unit_keys = [k for k in units.keys() if _is_eps_unit(k)]
                if not unit_keys and "USD" in units:
                    unit_keys = ["USD"]
            else:
                unit_keys = ["USD"] if "USD" in units else []
            
            for unit_key in unit_keys:
                rows = units.get(unit_key, [])
                filtered_rows = []
                for r in rows:
                    if not r.get("start") or not r.get("end"):
                        continue  # Skip instant facts
                    if filter_func and not filter_func(r):
                        continue
                    filtered_rows.append({
                        "end": r.get("end"),
                        "val": r.get("val"),
                        "concept": concept_name,
                        "filed": r.get("filed", ""),
                    })
                
                if filtered_rows:
                    deduped = _dedupe_by_end(filtered_rows)
                    # Track the most recent end date for this concept
                    most_recent_end = max(r.get("end", "") for r in deduped)
                    all_concept_results.append({
                        "concept": concept_name,
                        "most_recent_end": most_recent_end,
                        "data": deduped
                    })
    
    if not all_concept_results:
        return []
    
    # Select the concept with the most recent fiscal year end date
    best_concept = max(all_concept_results, key=lambda x: x["most_recent_end"])
    
    # Log selection if we had multiple options
    if len(all_concept_results) > 1:
        logging.debug(
            f"Selected concept '{best_concept['concept']}' with most recent data "
            f"({best_concept['most_recent_end']}) over {len(all_concept_results)-1} other concepts"
        )
    
    return best_concept["data"]


# ============================================================================
# Growth Calculations
# ============================================================================

def calculate_yoy_growth(values: List[Optional[float]], is_eps: bool = False) -> Dict[str, Optional[float]]:
    """
    Calculate YoY growth for consecutive periods.
    
    Returns percentage change as a decimal (0.10 = 10%).
    
    Args:
        values: List of metric values (most recent first)
        is_eps: If True, applies stricter rules for EPS (skips when either value is negative)
    
    Edge case handling:
    - Returns None when prior value is zero (division by zero)
    - Caps extreme values at ±9.9999 (±999.99%) for very large swings
    - For EPS (is_eps=True): Returns None if either value is negative
      (percentage math produces confusing/misleading results with negative earnings)
    """
    # Maximum absolute YoY value (999.99%)
    MAX_YOY = 9.9999
    
    result = {}
    for i in range(len(values) - 1):
        cur = values[i]
        prev = values[i + 1]
        
        year_label = f"period_{i}"
        
        if cur is not None and prev is not None and prev != 0:
            # For EPS: skip if either value is negative (math gets confusing)
            if is_eps and (cur < 0 or prev < 0):
                result[year_label] = None
                continue
            
            yoy = (cur / prev) - 1
            
            # Cap extreme values
            if yoy > MAX_YOY:
                yoy = MAX_YOY
            elif yoy < -MAX_YOY:
                yoy = -MAX_YOY
            result[year_label] = round(yoy, 4)
        else:
            result[year_label] = None
    
    return result


def calculate_cagr(start_val: Optional[float], end_val: Optional[float], years: int) -> Optional[float]:
    """
    Calculate Compound Annual Growth Rate.
    
    When standard CAGR can't be computed (negative/zero values), falls back to
    Linear Annualized Rate: (end - start) / abs(start) / years
    
    This provides a meaningful growth metric even for companies with losses.
    """
    if start_val is None or end_val is None or years <= 0:
        return None
    
    # Standard CAGR when both values are positive
    if start_val > 0 and end_val > 0:
        try:
            return round((end_val / start_val) ** (1 / years) - 1, 4)
        except Exception:
            return None
    
    # Fallback to Linear Annualized Rate for negative/zero values
    # Formula: (end - start) / abs(start) / years
    # This shows the average annual change as a percentage of the absolute starting value
    if start_val != 0:
        try:
            linear_rate = (end_val - start_val) / abs(start_val) / years
            return round(linear_rate, 4)
        except Exception:
            return None
    
    return None


def calculate_ttm(quarters: List[QuarterlyRecord], metric: str) -> Optional[float]:
    """Sum the most recent 4 quarters for a metric."""
    if len(quarters) < 4:
        return None
    
    vals = []
    for q in quarters[:4]:
        v = getattr(q, metric, None)
        if v is None:
            return None
        vals.append(v)
    
    return sum(vals)


def calculate_ttm_yoy(quarters: List[QuarterlyRecord], metric: str, is_eps: bool = False) -> Optional[float]:
    """
    Calculate TTM YoY growth.
    Compares sum of quarters 0-3 (most recent TTM) to sum of quarters 4-7 (prior TTM).
    
    Args:
        quarters: List of quarterly records (most recent first)
        metric: The metric to calculate ('revenue' or 'eps_diluted')
        is_eps: If True, returns None when either TTM sum is negative
    
    Edge case handling:
    - Returns None when prior TTM is zero (division by zero)
    - Caps extreme values at ±9.9999 (±999.99%)
    - For EPS (is_eps=True): Returns None if either TTM is negative
      (percentage math produces confusing/misleading results with negative earnings)
    """
    # Maximum absolute YoY value (999.99%)
    MAX_YOY = 9.9999
    
    if len(quarters) < 8:
        return None
    
    current_ttm = []
    prior_ttm = []
    
    for i, q in enumerate(quarters[:8]):
        v = getattr(q, metric, None)
        if v is None:
            return None
        if i < 4:
            current_ttm.append(v)
        else:
            prior_ttm.append(v)
    
    if len(current_ttm) < 4 or len(prior_ttm) < 4:
        return None
    
    current_sum = sum(current_ttm)
    prior_sum = sum(prior_ttm)
    
    if prior_sum == 0:
        return None
    
    # For EPS: skip if either TTM is negative (math gets confusing)
    if is_eps and (current_sum < 0 or prior_sum < 0):
        return None
    
    yoy = (current_sum / prior_sum) - 1
    
    # Cap extreme values
    if yoy > MAX_YOY:
        yoy = MAX_YOY
    elif yoy < -MAX_YOY:
        yoy = -MAX_YOY
    
    return round(yoy, 4)


# ============================================================================
# Main Extraction Logic
# ============================================================================

def extract_company_data(
    ticker: str,
    cik: str,
    companyfacts: dict,
    config: Config
) -> CompanyData:
    """Extract annual and quarterly financial data for a single company."""
    errors = []
    extracted_at = datetime.utcnow().isoformat() + "Z"
    
    # Get company name
    company_name = companyfacts.get("entityName") if companyfacts else None
    
    # ========== ANNUAL DATA (10-K) ==========
    revenue_rows = extract_concept_values(
        companyfacts,
        config.concepts.get("revenue", []),
        is_eps=False,
        filter_func=is_annual_10k
    )
    
    eps_rows = extract_concept_values(
        companyfacts,
        config.concepts.get("eps_diluted", []),
        is_eps=True,
        filter_func=is_annual_10k
    )
    
    revenue_rows = revenue_rows[:config.years_to_fetch]
    eps_rows = eps_rows[:config.years_to_fetch]
    
    if not revenue_rows:
        errors.append("No annual revenue data found")
    if not eps_rows:
        errors.append("No annual EPS data found")
    
    # Build annual records
    all_ends = set()
    revenue_by_end = {r["end"]: r for r in revenue_rows}
    eps_by_end = {r["end"]: r for r in eps_rows}
    all_ends.update(revenue_by_end.keys())
    all_ends.update(eps_by_end.keys())
    
    sorted_ends = sorted(all_ends, reverse=True)[:config.years_to_fetch]
    
    annual_data = []
    for end in sorted_ends:
        rev_rec = revenue_by_end.get(end)
        eps_rec = eps_by_end.get(end)
        
        annual_data.append(AnnualRecord(
            fiscal_year_end=end,
            revenue=rev_rec["val"] if rev_rec else None,
            eps_diluted=eps_rec["val"] if eps_rec else None,
            revenue_concept=rev_rec["concept"] if rev_rec else None,
            eps_concept=eps_rec["concept"] if eps_rec else None,
        ))
    
    # ========== ANNUAL FALLBACK WITH CROSS-VALIDATION ==========
    # Count how many annual records have null revenue or EPS
    annual_null_revenue = sum(1 for a in annual_data if a.revenue is None)
    annual_null_eps = sum(1 for a in annual_data if a.eps_diluted is None)
    # Also need fallback if we don't have enough years of data
    need_more_years = len(annual_data) < config.years_to_fetch
    need_annual_fallback = (annual_null_revenue > 0 or annual_null_eps > 0 or len(annual_data) == 0 or need_more_years)
    
    if need_annual_fallback:
        # Gather data from ALL available fallback sources for consensus-based validation
        # FMP is now included upfront for 2-out-of-3 consensus voting
        all_fallback_sources = gather_all_fallback_data(ticker, config, config.years_to_fetch)
        
        if all_fallback_sources:
            # For each annual record that needs fallback data, cross-validate
            for a in annual_data:
                # Revenue cross-validation
                if a.revenue is None:
                    rev_validation = cross_validate_fallback_year(
                        a.fiscal_year_end, 
                        all_fallback_sources, 
                        "revenue",
                        tolerance_pct=5.0
                    )
                    if rev_validation.value is not None:
                        a.revenue = rev_validation.value
                        a.revenue_concept = f"fallback:{','.join(rev_validation.sources_compared)}"
                        a.revenue_validation = rev_validation.status
                        a.revenue_sources = rev_validation.sources_compared
                        a.revenue_discrepancy_pct = rev_validation.discrepancy_pct
                
                # EPS cross-validation
                if a.eps_diluted is None:
                    eps_validation = cross_validate_fallback_year(
                        a.fiscal_year_end, 
                        all_fallback_sources, 
                        "eps_diluted",
                        tolerance_pct=5.0
                    )
                    if eps_validation.value is not None:
                        a.eps_diluted = eps_validation.value
                        a.eps_concept = f"fallback:{','.join(eps_validation.sources_compared)}"
                        a.eps_validation = eps_validation.status
                        a.eps_sources = eps_validation.sources_compared
                        a.eps_discrepancy_pct = eps_validation.discrepancy_pct
            
            # Add new years from fallback sources that we're missing entirely
            existing_years = {a.fiscal_year_end[:4] for a in annual_data}
            
            # Collect all unique year dates from all sources
            all_year_dates = {}
            for source_name, df in all_fallback_sources.items():
                for _, row in df.iterrows():
                    end = row.get("end")
                    if end:
                        year = end[:4]
                        if year not in existing_years:
                            all_year_dates[year] = end
            
            # Add missing years with cross-validation (consensus-based)
            for year, year_date in all_year_dates.items():
                if year not in existing_years:
                    rev_validation = cross_validate_fallback_year(year_date, all_fallback_sources, "revenue", 5.0)
                    eps_validation = cross_validate_fallback_year(year_date, all_fallback_sources, "eps_diluted", 5.0)
                    
                    if rev_validation.value is not None or eps_validation.value is not None:
                        annual_data.append(AnnualRecord(
                            fiscal_year_end=year_date,
                            revenue=rev_validation.value,
                            eps_diluted=eps_validation.value,
                            revenue_concept=f"fallback:{','.join(rev_validation.sources_compared)}" if rev_validation.sources_compared else None,
                            eps_concept=f"fallback:{','.join(eps_validation.sources_compared)}" if eps_validation.sources_compared else None,
                            revenue_validation=rev_validation.status if rev_validation.value else None,
                            eps_validation=eps_validation.status if eps_validation.value else None,
                            revenue_sources=rev_validation.sources_compared if rev_validation.value else None,
                            eps_sources=eps_validation.sources_compared if eps_validation.value else None,
                            revenue_discrepancy_pct=rev_validation.discrepancy_pct,
                            eps_discrepancy_pct=eps_validation.discrepancy_pct,
                        ))
                        existing_years.add(year)
            
            # Re-sort and limit
            annual_data.sort(key=lambda x: x.fiscal_year_end, reverse=True)
            annual_data = annual_data[:config.years_to_fetch]
    
    # ========== QUARTERLY DATA (10-Q) ==========
    quarterly_data = []
    quarterly_source = "sec"
    
    # Try SEC first
    q_revenue_rows = extract_concept_values(
        companyfacts,
        config.concepts.get("revenue", []),
        is_eps=False,
        filter_func=is_quarterly_10q
    )
    
    q_eps_rows = extract_concept_values(
        companyfacts,
        config.concepts.get("eps_diluted", []),
        is_eps=True,
        filter_func=is_quarterly_10q
    )
    
    q_revenue_rows = q_revenue_rows[:config.quarters_to_fetch]
    q_eps_rows = q_eps_rows[:config.quarters_to_fetch]
    
    # Build quarterly from SEC
    q_all_ends = set()
    q_revenue_by_end = {r["end"]: r for r in q_revenue_rows}
    q_eps_by_end = {r["end"]: r for r in q_eps_rows}
    q_all_ends.update(q_revenue_by_end.keys())
    q_all_ends.update(q_eps_by_end.keys())
    
    q_sorted_ends = sorted(q_all_ends, reverse=True)[:config.quarters_to_fetch]
    
    for end in q_sorted_ends:
        rev_rec = q_revenue_by_end.get(end)
        eps_rec = q_eps_by_end.get(end)
        
        quarterly_data.append(QuarterlyRecord(
            fiscal_quarter_end=end,
            revenue=rev_rec["val"] if rev_rec else None,
            eps_diluted=eps_rec["val"] if eps_rec else None,
            source="sec",
        ))
    
    # ========== QUARTERLY FALLBACK (yfinance first, then Finnhub) ==========
    # Check if SEC quarterly data is incomplete for TTM calculation.
    # We need the MOST RECENT 4 quarters to have both revenue and EPS for TTM.
    # We need 8 quarters for TTM YoY calculation.
    # Also trigger fallback if ANY quarter in the top 8 is missing data.
    recent_4 = quarterly_data[:4] if len(quarterly_data) >= 4 else quarterly_data
    recent_4_revenue = sum(1 for q in recent_4 if q.revenue is not None)
    recent_4_eps = sum(1 for q in recent_4 if q.eps_diluted is not None)
    
    # For TTM YoY, we need 8 quarters with complete data
    recent_8 = quarterly_data[:8] if len(quarterly_data) >= 8 else quarterly_data
    recent_8_revenue = sum(1 for q in recent_8 if q.revenue is not None)
    recent_8_eps = sum(1 for q in recent_8 if q.eps_diluted is not None)
    
    any_null_revenue = any(q.revenue is None for q in quarterly_data)
    any_null_eps = any(q.eps_diluted is None for q in quarterly_data)
    
    # Trigger fallback if:
    # 1. Most recent 4 quarters are incomplete (for basic TTM)
    # 2. Any quarter has nulls
    # 3. We have fewer than 8 quarters (needed for TTM YoY)
    need_quarterly_fallback = (
        recent_4_revenue < 4 or 
        recent_4_eps < 4 or 
        any_null_revenue or 
        any_null_eps or
        len(quarterly_data) < 8 or  # Need 8 quarters for TTM YoY
        recent_8_revenue < 8 or     # Need 8 quarters with revenue for full TTM YoY
        recent_8_eps < 8            # Need 8 quarters with EPS for full TTM YoY
    )
    quarterly_source = "sec"
    
    def check_need_more_quarters():
        """Check if we still need more quarterly data for TTM YoY calculation."""
        current_8 = quarterly_data[:8] if len(quarterly_data) >= 8 else quarterly_data
        rev_count = sum(1 for q in current_8 if q.revenue is not None)
        eps_count = sum(1 for q in current_8 if q.eps_diluted is not None)
        # Need 8 quarters with data for full TTM YoY
        return len(quarterly_data) < 8 or rev_count < 8 or eps_count < 8
    
    def merge_quarterly_fallback(df: pd.DataFrame, source_name: str):
        """Helper to merge fallback data into quarterly_data."""
        nonlocal quarterly_source
        if df.empty:
            return
        
        # Build lookup by date
        fb_by_end = {}
        for _, row in df.iterrows():
            end = row.get("end")
            if end:
                fb_by_end[end] = row
        
        # Fill gaps in existing quarters
        for q in quarterly_data:
            fb_rec = fb_by_end.get(q.fiscal_quarter_end)
            if fb_rec is not None:
                if q.revenue is None and pd.notna(fb_rec.get("revenue")):
                    q.revenue = float(fb_rec["revenue"])
                    q.source = source_name
                    quarterly_source = "mixed"
                if q.eps_diluted is None and pd.notna(fb_rec.get("eps_diluted")):
                    q.eps_diluted = float(fb_rec["eps_diluted"])
                    q.source = source_name
                    quarterly_source = "mixed"
        
        # Add any new quarters not in SEC
        existing_ends = {q.fiscal_quarter_end for q in quarterly_data}
        for end, row in fb_by_end.items():
            if end not in existing_ends:
                quarterly_data.append(QuarterlyRecord(
                    fiscal_quarter_end=end,
                    revenue=float(row["revenue"]) if pd.notna(row.get("revenue")) else None,
                    eps_diluted=float(row["eps_diluted"]) if pd.notna(row.get("eps_diluted")) else None,
                    source=source_name,
                ))
                quarterly_source = "mixed"
    
    if need_quarterly_fallback:
        # 1. Try yfinance first (free, no API key needed)
        if config.yfinance_enabled:
            yf_quarterly = yfinance_quarterly_financials(ticker, config.quarters_to_fetch)
            merge_quarterly_fallback(yf_quarterly, "yfinance")
        
        # Recheck if still need more data for TTM YoY (requires 8 quarters)
        still_need_fallback = check_need_more_quarters()
        
        # 2. Try standard Finnhub if still incomplete
        if still_need_fallback and config.finnhub_enabled and config.finnhub_api_key:
            finnhub_df = finnhub_quarterly_financials(ticker, config.finnhub_api_key)
            merge_quarterly_fallback(finnhub_df, "finnhub")
        
        # Recheck again
        still_need_fallback = check_need_more_quarters()
        
        # 3. Try Finnhub As Reported (SEC XBRL data with YTD-to-quarterly conversion)
        # This provides 12+ quarters of data for companies where other sources have gaps
        if still_need_fallback and config.finnhub_as_reported_enabled and config.finnhub_api_key:
            far_quarterly = finnhub_as_reported_quarterly_financials(ticker, config.finnhub_api_key, config.quarters_to_fetch)
            merge_quarterly_fallback(far_quarterly, "finnhub_as_reported")
        
        # Re-sort and limit
        quarterly_data.sort(key=lambda x: x.fiscal_quarter_end, reverse=True)
        quarterly_data = quarterly_data[:config.quarters_to_fetch]
    
    # ========== GROWTH METRICS ==========
    revenues = [a.revenue for a in annual_data]
    eps_values = [a.eps_diluted for a in annual_data]
    
    revenue_yoy = calculate_yoy_growth(revenues, is_eps=False)
    eps_yoy = calculate_yoy_growth(eps_values, is_eps=True)
    
    # Relabel with actual years
    def relabel_yoy(yoy_dict: dict, records: List[AnnualRecord]) -> Dict[str, Optional[float]]:
        result = {}
        for i, (key, val) in enumerate(yoy_dict.items()):
            if i < len(records):
                year = records[i].fiscal_year_end[:4]
                result[year] = val
        return result
    
    revenue_yoy = relabel_yoy(revenue_yoy, annual_data)
    eps_yoy = relabel_yoy(eps_yoy, annual_data)
    
    # ========== TTM METRICS (from quarterly) ==========
    ttm = None
    
    if len(quarterly_data) >= 4:
        ttm_revenue = calculate_ttm(quarterly_data, "revenue")
        ttm_eps = calculate_ttm(quarterly_data, "eps_diluted")
        ttm_revenue_yoy = calculate_ttm_yoy(quarterly_data, "revenue", is_eps=False)
        ttm_eps_yoy = calculate_ttm_yoy(quarterly_data, "eps_diluted", is_eps=True)
        
        # Determine source
        sources = set(q.source for q in quarterly_data[:4])
        fallback_sources = {"finnhub", "finnhub_as_reported", "yfinance"}
        if sources & fallback_sources and "sec" in sources:
            ttm_source = "mixed"
        elif sources & fallback_sources:
            ttm_source = "mixed"  # Multiple fallback sources
        else:
            ttm_source = "sec"
        
        ttm = TTMMetrics(
            revenue=ttm_revenue,
            eps_diluted=ttm_eps,
            revenue_yoy=ttm_revenue_yoy,
            eps_yoy=ttm_eps_yoy,
            as_of_quarter=quarterly_data[0].fiscal_quarter_end if quarterly_data else None,
            source=ttm_source,
        )
    elif annual_data:
        # Fallback: use most recent annual as TTM approximation
        # Maximum absolute YoY value (999.99%)
        MAX_YOY = 9.9999
        
        ttm_revenue_yoy = None
        ttm_eps_yoy = None
        
        # Revenue YoY (revenue is always positive, so just cap extremes)
        if len(revenues) >= 2 and revenues[0] is not None and revenues[1] is not None and revenues[1] > 0:
            yoy = (revenues[0] / revenues[1]) - 1
            ttm_revenue_yoy = round(max(-MAX_YOY, min(MAX_YOY, yoy)), 4)
        
        # EPS YoY (only calculate when both values are positive to avoid confusing percentages)
        if len(eps_values) >= 2 and eps_values[0] is not None and eps_values[1] is not None:
            if eps_values[0] >= 0 and eps_values[1] > 0:
                yoy = (eps_values[0] / eps_values[1]) - 1
                ttm_eps_yoy = round(max(-MAX_YOY, min(MAX_YOY, yoy)), 4)
        
        ttm = TTMMetrics(
            revenue=revenues[0] if revenues else None,
            eps_diluted=eps_values[0] if eps_values else None,
            revenue_yoy=ttm_revenue_yoy,
            eps_yoy=ttm_eps_yoy,
            as_of_quarter=annual_data[0].fiscal_year_end if annual_data else None,
            source="annual_fallback",
        )
    
    # ========== CAGR ==========
    revenue_cagr_3yr = None
    eps_cagr_3yr = None
    if len(revenues) >= 4 and revenues[0] is not None and revenues[3] is not None:
        revenue_cagr_3yr = calculate_cagr(revenues[3], revenues[0], 3)
    if len(eps_values) >= 4 and eps_values[0] is not None and eps_values[3] is not None:
        eps_cagr_3yr = calculate_cagr(eps_values[3], eps_values[0], 3)
    
    revenue_cagr_5yr = None
    eps_cagr_5yr = None
    if len(revenues) >= 6 and revenues[0] is not None and revenues[5] is not None:
        revenue_cagr_5yr = calculate_cagr(revenues[5], revenues[0], 5)
    if len(eps_values) >= 6 and eps_values[0] is not None and eps_values[5] is not None:
        eps_cagr_5yr = calculate_cagr(eps_values[5], eps_values[0], 5)
    
    growth = GrowthMetrics(
        revenue_yoy=revenue_yoy,
        eps_yoy=eps_yoy,
        ttm=ttm,
        revenue_cagr_3yr=revenue_cagr_3yr,
        eps_cagr_3yr=eps_cagr_3yr,
        revenue_cagr_5yr=revenue_cagr_5yr,
        eps_cagr_5yr=eps_cagr_5yr,
    )
    
    return CompanyData(
        ticker=ticker,
        cik=cik,
        company_name=company_name,
        extracted_at=extracted_at,
        annual_data=annual_data,
        quarterly_data=quarterly_data,
        growth=growth,
        errors=errors,
    )


def company_data_to_dict(data: CompanyData) -> dict:
    """Convert CompanyData to JSON-serializable dict."""
    # Build annual values dict: {"2024": {"revenue": 123456, "eps": 1.23}, ...}
    annual_values = {}
    for a in data.annual_data:
        year = a.fiscal_year_end[:4]
        annual_values[year] = {
            "revenue": a.revenue,
            "eps": a.eps_diluted,
        }
    
    # Build quarterly values dict: {"2024-Q3": {"revenue": 123456, "eps": 0.45}, ...}
    quarterly_values = {}
    for q in data.quarterly_data:
        # Convert date to quarter label (e.g., "2024-09-30" -> "2024-Q3")
        try:
            date_parts = q.fiscal_quarter_end.split("-")
            if len(date_parts) >= 2:
                year = date_parts[0]
                month = int(date_parts[1])
                quarter = (month - 1) // 3 + 1
                quarter_label = f"{year}-Q{quarter}"
            else:
                quarter_label = q.fiscal_quarter_end
        except (ValueError, AttributeError):
            quarter_label = q.fiscal_quarter_end
        
        quarterly_values[quarter_label] = {
            "revenue": q.revenue,
            "eps": q.eps_diluted,
        }
    
    return {
        "ticker": data.ticker,
        "sector": get_sector(data.ticker),
        "cik": data.cik,
        "company_name": data.company_name,
        "extracted_at": data.extracted_at,
        "annual_values": annual_values,
        "quarterly_values": quarterly_values,
        "growth": {
            "revenue_yoy": data.growth.revenue_yoy,
            "eps_yoy": data.growth.eps_yoy,
            "ttm": asdict(data.growth.ttm) if data.growth.ttm else None,
            "revenue_cagr_3yr": data.growth.revenue_cagr_3yr,
            "eps_cagr_3yr": data.growth.eps_cagr_3yr,
            "revenue_cagr_5yr": data.growth.revenue_cagr_5yr,
            "eps_cagr_5yr": data.growth.eps_cagr_5yr,
        },
        "errors": data.errors,
    }


# ============================================================================
# I/O
# ============================================================================

def save_json(data: dict, path: Path, indent: int = 2):
    """Save dict to JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=indent)


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Extract annual & quarterly revenue/EPS from SEC EDGAR for S&P 100 companies."
    )
    parser.add_argument("--config", "-c", default=None, help="Path to config.yml")
    parser.add_argument("--output", "-o", default=None, help="Output directory")
    args = parser.parse_args()
    
    # Load config
    cwd = Path(__file__).parent
    config_path = Path(args.config) if args.config else (cwd / "config.yml")
    if not config_path.exists():
        raise SystemExit(f"Config not found: {config_path}")
    
    config = Config.from_yaml(str(config_path))
    
    if args.output:
        config.output_dir = Path(args.output)
    
    # Get S&P 100 tickers from universe
    print("[info] Fetching S&P 100 universe...")
    tickers = fetch_sp100_tickers()
    
    if not tickers:
        raise SystemExit("No tickers to process - S&P 100 universe is empty")
    
    print(f"[info] Processing {len(tickers)} S&P 100 ticker(s)")
    print(f"[info] Output: {config.output_dir / config.output_filename}")
    print(f"[info] Annual fallbacks: yfinance={'enabled' if config.yfinance_enabled else 'disabled'}, Alpha Vantage={'enabled' if config.alphavantage_enabled and config.alphavantage_api_key else 'disabled'}, Finnhub={'enabled' if config.finnhub_enabled and config.finnhub_api_key else 'disabled'}")
    print(f"[info] Quarterly fallback: Finnhub={'enabled' if config.finnhub_enabled and config.finnhub_api_key else 'disabled'}")
    
    # Load CIK mapping
    print("[info] Loading SEC CIK mapping...")
    ticker_to_cik = load_ticker_to_cik(config.user_agent)
    
    # Process tickers
    results = []
    success_count = 0
    
    for i, ticker in enumerate(tickers, 1):
        print(f"[{i}/{len(tickers)}] {ticker}...", end=" ", flush=True)
        
        cik = ticker_to_cik.get(ticker, "")
        if not cik:
            print("no CIK found, skipping")
            results.append(CompanyData(
                ticker=ticker, cik="", company_name=None,
                extracted_at=datetime.utcnow().isoformat() + "Z",
                annual_data=[], quarterly_data=[],
                growth=GrowthMetrics({}, {}),
                errors=["CIK not found"],
            ))
            continue
        
        facts = fetch_company_facts(ticker, config.user_agent)
        if not facts:
            print("no SEC data, skipping")
            results.append(CompanyData(
                ticker=ticker, cik=cik, company_name=None,
                extracted_at=datetime.utcnow().isoformat() + "Z",
                annual_data=[], quarterly_data=[],
                growth=GrowthMetrics({}, {}),
                errors=["Failed to fetch SEC data"],
            ))
            continue
        
        company_data = extract_company_data(ticker, cik, facts, config)
        results.append(company_data)
        
        if company_data.annual_data:
            success_count += 1
            years = len(company_data.annual_data)
            quarters = len(company_data.quarterly_data)
            q_source = company_data.growth.ttm.source if company_data.growth.ttm else "none"
            print(f"OK ({years} years, {quarters} quarters, TTM: {q_source})")
        else:
            print("no data found")
    
    # Save output
    config.output_dir.mkdir(parents=True, exist_ok=True)
    
    # Build _README section (following project standards)
    readme_section = {
        "title": "S&P 100 Growth Metrics",
        "description": "Financial growth metrics extracted from SEC EDGAR filings for S&P 100 companies",
        "purpose": "Track revenue and EPS growth for the largest US companies",
        "data_sources": {
            "primary": "SEC EDGAR (10-K and 10-Q filings)",
            "annual_fallbacks": [
                "yfinance (Yahoo Finance)",
                "Alpha Vantage API",
                "Finnhub API"
            ],
            "quarterly_fallback": "Finnhub API"
        },
        "metrics_explained": {
            "sector": {
                "description": "GICS sector classification for the company",
                "format": "String (e.g., 'Information Technology', 'Health Care', 'Financials')",
                "source": "shared/sector_mapping.py - comprehensive S&P 500 sector mapping"
            },
            "annual_values": {
                "description": "Actual annual revenue and EPS values for each fiscal year",
                "format": "Object keyed by year (e.g., '2024', '2023')",
                "fields": {
                    "revenue": "Annual revenue in USD",
                    "eps": "Annual diluted EPS in USD per share"
                },
                "years_available": f"{config.years_to_fetch} years of data"
            },
            "quarterly_values": {
                "description": "Actual quarterly revenue and EPS values",
                "format": "Object keyed by quarter (e.g., '2024-Q3', '2024-Q2')",
                "fields": {
                    "revenue": "Quarterly revenue in USD",
                    "eps": "Quarterly diluted EPS in USD per share"
                },
                "quarters_available": f"{config.quarters_to_fetch} quarters of data"
            },
            "revenue_yoy": {
                "description": "Year-over-year revenue growth rate",
                "format": "Decimal (0.05 = 5% growth, -0.03 = 3% decline)",
                "calculation": "(current_year_revenue / prior_year_revenue) - 1"
            },
            "eps_yoy": {
                "description": "Year-over-year diluted EPS growth rate",
                "format": "Decimal (0.10 = 10% growth)",
                "calculation": "(current_year_eps / prior_year_eps) - 1"
            },
            "ttm": {
                "description": "Trailing Twelve Months metrics from the most recent 4 quarters",
                "fields": {
                    "revenue": "Sum of revenue from the last 4 quarters (USD)",
                    "eps_diluted": "Sum of diluted EPS from the last 4 quarters",
                    "revenue_yoy": "TTM revenue growth vs prior TTM",
                    "eps_yoy": "TTM EPS growth vs prior TTM",
                    "source": "'sec', 'finnhub', 'mixed', or 'annual_fallback'"
                }
            },
            "cagr_3yr": {
                "description": "3-year Compound Annual Growth Rate",
                "calculation": "(end_value / start_value)^(1/3) - 1"
            },
            "cagr_5yr": {
                "description": "5-year Compound Annual Growth Rate",
                "calculation": "(end_value / start_value)^(1/5) - 1"
            }
        },
        "concept_sources": {
            "sec": "Direct SEC XBRL concept extraction",
            "fallback:yfinance": "Yahoo Finance annual data via yfinance",
            "fallback:alphavantage": "Alpha Vantage fundamental data API",
            "fallback:finnhub": "Finnhub stock fundamentals API"
        },
        "trading_applications": {
            "growth_screening": "Filter companies by revenue/EPS growth rates",
            "momentum_analysis": "Track acceleration/deceleration in fundamentals",
            "valuation_context": "Compare growth rates to P/E ratios",
            "sector_comparison": "Identify growth leaders within sectors"
        },
        "notes": [
            "All growth rates are decimals (multiply by 100 for percentage)",
            "Null values indicate insufficient data from all sources",
            "Revenue figures are in USD (not scaled)",
            "Fiscal year end dates vary by company",
            "revenue_concept and eps_concept fields indicate data source"
        ]
    }
    
    # Build metadata
    metadata = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "data_sources": "SEC EDGAR + yfinance + Alpha Vantage + Finnhub",
        "ticker_count": len(results),
        "successful_extractions": success_count,
        "universe": "S&P 100"
    }
    
    # Build companies dict keyed by ticker
    companies = {}
    for result in results:
        companies[result.ticker] = company_data_to_dict(result)
    
    combined = {
        "_README": readme_section,
        "metadata": metadata,
        "companies": companies,
    }
    
    out_path = config.output_dir / config.output_filename
    save_json(combined, out_path, config.indent)
    print(f"\n[ok] Wrote output to {out_path}")
    
    print(f"[ok] Successfully extracted data for {success_count}/{len(tickers)} tickers")


if __name__ == "__main__":
    main()
