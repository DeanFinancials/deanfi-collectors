#!/usr/bin/env python3
"""
SP100 Growth Extractor - SEC EDGAR data extractor for annual & quarterly financials.

Pulls annual (10-K) and quarterly (10-Q) revenue and EPS data from SEC EDGAR,
with Finnhub fallback for quarterly data. Calculates YoY growth, TTM, and CAGR.

This collector fetches fundamental growth metrics for S&P 100 companies:
- Annual revenue and EPS (from 10-K filings)
- Quarterly revenue and EPS (from 10-Q filings, with Finnhub fallback)
- Year-over-Year growth rates
- Trailing Twelve Months (TTM) metrics
- 3-year and 5-year CAGR

Data Sources:
- SEC EDGAR: Primary source for all annual and quarterly data
- Finnhub API: Fallback for quarterly data when SEC data is incomplete

Usage:
    python fetch_sp100_growth.py                    # Use S&P 100 universe
    python fetch_sp100_growth.py --output ./output  # Custom output directory
"""
from __future__ import annotations

import argparse
import json
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


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class AnnualRecord:
    """Single year of financial data."""
    fiscal_year_end: str
    revenue: Optional[float] = None
    eps_diluted: Optional[float] = None
    revenue_concept: Optional[str] = None
    eps_concept: Optional[str] = None


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

    @staticmethod
    def from_yaml(path: str) -> "Config":
        with open(path, "r") as f:
            raw = yaml.safe_load(f)
        
        sec = raw.get("sec", {})
        output = raw.get("output", {})
        finnhub = raw.get("finnhub", {})
        
        # Read Finnhub API key from environment variable (standard pattern)
        finnhub_api_key = os.environ.get("FINNHUB_API_KEY", "")
        
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


# ============================================================================
# Data Extraction Helpers
# ============================================================================

def is_annual_10k(row: dict) -> bool:
    """Check if a row is from an annual 10-K filing."""
    form = str(row.get("form", "")).upper()
    fp = str(row.get("fp", "")).upper()
    return form.startswith("10-K") and (fp in ("FY", "") or fp.startswith("Q4"))


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
    Extract values for a list of concept names (first match wins).
    Returns list of {end, val, concept, filed} dicts.
    """
    facts = companyfacts.get("facts", {}) or {}
    
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
                    return deduped
    
    return []


# ============================================================================
# Growth Calculations
# ============================================================================

def calculate_yoy_growth(values: List[Optional[float]]) -> Dict[str, Optional[float]]:
    """Calculate YoY growth for consecutive periods."""
    result = {}
    for i in range(len(values) - 1):
        cur = values[i]
        prev = values[i + 1]
        
        year_label = f"period_{i}"
        
        if cur is not None and prev is not None and prev != 0:
            result[year_label] = round((cur / prev) - 1, 4)
        else:
            result[year_label] = None
    
    return result


def calculate_cagr(start_val: Optional[float], end_val: Optional[float], years: int) -> Optional[float]:
    """Calculate Compound Annual Growth Rate."""
    if start_val is None or end_val is None or start_val <= 0 or years <= 0:
        return None
    try:
        return round((end_val / start_val) ** (1 / years) - 1, 4)
    except Exception:
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


def calculate_ttm_yoy(quarters: List[QuarterlyRecord], metric: str) -> Optional[float]:
    """
    Calculate TTM YoY growth.
    Compares sum of quarters 0-3 (most recent TTM) to sum of quarters 4-7 (prior TTM).
    """
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
    
    return round((current_sum / prior_sum) - 1, 4)


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
    
    # Fallback to Finnhub if SEC quarterly data is incomplete
    sec_quarters_with_revenue = sum(1 for q in quarterly_data if q.revenue is not None)
    sec_quarters_with_eps = sum(1 for q in quarterly_data if q.eps_diluted is not None)
    
    need_finnhub = (sec_quarters_with_revenue < 4 or sec_quarters_with_eps < 4)
    
    if need_finnhub and config.finnhub_enabled and config.finnhub_api_key:
        finnhub_df = finnhub_quarterly_financials(ticker, config.finnhub_api_key)
        
        if not finnhub_df.empty:
            # Merge Finnhub data into quarterly records
            fh_by_end = {}
            for _, row in finnhub_df.iterrows():
                end = row.get("end")
                if end:
                    fh_by_end[end] = row
            
            # Fill gaps in existing quarters
            for q in quarterly_data:
                fh_rec = fh_by_end.get(q.fiscal_quarter_end)
                if fh_rec is not None:
                    if q.revenue is None and pd.notna(fh_rec.get("revenue")):
                        q.revenue = fh_rec["revenue"]
                        q.source = "finnhub"
                    if q.eps_diluted is None and pd.notna(fh_rec.get("eps_diluted")):
                        q.eps_diluted = fh_rec["eps_diluted"]
                        q.source = "finnhub"
            
            # Add any new quarters from Finnhub not in SEC
            existing_ends = {q.fiscal_quarter_end for q in quarterly_data}
            for end, row in fh_by_end.items():
                if end not in existing_ends:
                    quarterly_data.append(QuarterlyRecord(
                        fiscal_quarter_end=end,
                        revenue=row.get("revenue") if pd.notna(row.get("revenue")) else None,
                        eps_diluted=row.get("eps_diluted") if pd.notna(row.get("eps_diluted")) else None,
                        source="finnhub",
                    ))
            
            # Re-sort and limit
            quarterly_data.sort(key=lambda x: x.fiscal_quarter_end, reverse=True)
            quarterly_data = quarterly_data[:config.quarters_to_fetch]
            quarterly_source = "mixed"
    
    # ========== GROWTH METRICS ==========
    revenues = [a.revenue for a in annual_data]
    eps_values = [a.eps_diluted for a in annual_data]
    
    revenue_yoy = calculate_yoy_growth(revenues)
    eps_yoy = calculate_yoy_growth(eps_values)
    
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
        ttm_revenue_yoy = calculate_ttm_yoy(quarterly_data, "revenue")
        ttm_eps_yoy = calculate_ttm_yoy(quarterly_data, "eps_diluted")
        
        # Determine source
        sources = set(q.source for q in quarterly_data[:4])
        if "finnhub" in sources and "sec" in sources:
            ttm_source = "mixed"
        elif "finnhub" in sources:
            ttm_source = "finnhub"
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
        ttm_revenue_yoy = None
        ttm_eps_yoy = None
        if len(revenues) >= 2 and revenues[0] is not None and revenues[1] is not None and revenues[1] != 0:
            ttm_revenue_yoy = round((revenues[0] / revenues[1]) - 1, 4)
        if len(eps_values) >= 2 and eps_values[0] is not None and eps_values[1] is not None and eps_values[1] != 0:
            ttm_eps_yoy = round((eps_values[0] / eps_values[1]) - 1, 4)
        
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
    return {
        "ticker": data.ticker,
        "cik": data.cik,
        "company_name": data.company_name,
        "extracted_at": data.extracted_at,
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
    print(f"[info] Finnhub fallback: {'enabled' if config.finnhub_enabled and config.finnhub_api_key else 'disabled'}")
    
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
            "fallback": "Finnhub API (for quarterly data when SEC is incomplete)"
        },
        "metrics_explained": {
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
        "trading_applications": {
            "growth_screening": "Filter companies by revenue/EPS growth rates",
            "momentum_analysis": "Track acceleration/deceleration in fundamentals",
            "valuation_context": "Compare growth rates to P/E ratios",
            "sector_comparison": "Identify growth leaders within sectors"
        },
        "notes": [
            "All growth rates are decimals (multiply by 100 for percentage)",
            "Null values indicate insufficient data",
            "Revenue figures are in USD (not scaled)",
            "Fiscal year end dates vary by company"
        ]
    }
    
    # Build metadata
    metadata = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "data_source": "SEC EDGAR + Finnhub",
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
