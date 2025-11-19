#!/usr/bin/env python3
"""
Indicator Definitions
Defines all economic indicators tracked by the system.
"""
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class IndicatorDefinition:
    """Definition of an economic indicator."""
    
    series_id: str
    name: str
    description: str
    frequency: str  # Daily, Weekly, Monthly, Quarterly
    seasonal_adjustment: str  # SA, NSA, SAAR
    unit: str  # Percent, Index, Billions, Thousands, etc.
    interpretation: str  # higher_is_better, lower_is_better, neutral
    is_derived: bool = False  # True if calculated from other series
    source_series: Optional[List[str]] = None  # For derived indicators
    
    def __post_init__(self):
        """Validate interpretation field."""
        valid_interpretations = ["higher_is_better", "lower_is_better", "neutral"]
        if self.interpretation not in valid_interpretations:
            raise ValueError(
                f"interpretation must be one of {valid_interpretations}, "
                f"got '{self.interpretation}'"
            )


# ============================================================================
# GROWTH & OUTPUT INDICATORS
# ============================================================================

GROWTH_OUTPUT_INDICATORS = [
    IndicatorDefinition(
        series_id="GDPC1",
        name="Real Gross Domestic Product",
        description="Real GDP in chained 2017 dollars",
        frequency="Quarterly",
        seasonal_adjustment="SAAR",
        unit="Billions of Chained 2017 Dollars",
        interpretation="higher_is_better"
    ),
    IndicatorDefinition(
        series_id="GDP_GROWTH",
        name="GDP Growth Rate (QoQ %)",
        description="Quarter-over-quarter GDP growth rate",
        frequency="Quarterly",
        seasonal_adjustment="SAAR",
        unit="Percent",
        interpretation="higher_is_better",
        is_derived=True,
        source_series=["GDPC1"]
    ),
    IndicatorDefinition(
        series_id="INDPRO",
        name="Industrial Production Index",
        description="Measures total real output of manufacturing, mining, and utilities",
        frequency="Monthly",
        seasonal_adjustment="SA",
        unit="Index 2017=100",
        interpretation="higher_is_better"
    ),
    IndicatorDefinition(
        series_id="TCU",
        name="Capacity Utilization (Total Industry)",
        description="Percentage of total productive capacity in use",
        frequency="Monthly",
        seasonal_adjustment="SA",
        unit="Percent",
        interpretation="higher_is_better"
    ),
    IndicatorDefinition(
        series_id="UMCSENT",
        name="University of Michigan Consumer Sentiment Index",
        description="Consumer sentiment survey measuring economic outlook",
        frequency="Monthly",
        seasonal_adjustment="NSA",
        unit="Index 1966Q1=100",
        interpretation="higher_is_better"
    ),
]


# ============================================================================
# LABOR & EMPLOYMENT INDICATORS
# ============================================================================

LABOR_EMPLOYMENT_INDICATORS = [
    IndicatorDefinition(
        series_id="UNRATE",
        name="Unemployment Rate",
        description="Headline unemployment rate (U-3)",
        frequency="Monthly",
        seasonal_adjustment="SA",
        unit="Percent",
        interpretation="lower_is_better"
    ),
    IndicatorDefinition(
        series_id="PAYEMS",
        name="Nonfarm Payroll Employment",
        description="Total nonfarm employment, in thousands",
        frequency="Monthly",
        seasonal_adjustment="SA",
        unit="Thousands of Persons",
        interpretation="higher_is_better"
    ),
    IndicatorDefinition(
        series_id="CIVPART",
        name="Labor Force Participation Rate",
        description="Share of population either working or seeking work",
        frequency="Monthly",
        seasonal_adjustment="SA",
        unit="Percent",
        interpretation="higher_is_better"
    ),
    IndicatorDefinition(
        series_id="CES0500000003",
        name="Average Hourly Earnings (Total Private)",
        description="Average hourly earnings of all private employees",
        frequency="Monthly",
        seasonal_adjustment="SA",
        unit="Dollars per Hour",
        interpretation="higher_is_better"
    ),
    IndicatorDefinition(
        series_id="JTSJOL",
        name="Job Openings (JOLTS)",
        description="Measures number of open positions across industries",
        frequency="Monthly",
        seasonal_adjustment="SA",
        unit="Thousands",
        interpretation="higher_is_better"
    ),
    IndicatorDefinition(
        series_id="ICSA",
        name="Initial Jobless Claims",
        description="Weekly new unemployment insurance claims",
        frequency="Weekly",
        seasonal_adjustment="NSA",
        unit="Thousands",
        interpretation="lower_is_better"
    ),
]


# ============================================================================
# INFLATION & PRICES INDICATORS
# ============================================================================

INFLATION_PRICES_INDICATORS = [
    IndicatorDefinition(
        series_id="CPIAUCSL",
        name="Consumer Price Index (All Items)",
        description="Headline CPI for all urban consumers",
        frequency="Monthly",
        seasonal_adjustment="SA",
        unit="Index 1982-84=100",
        interpretation="neutral"  # Context-dependent
    ),
    IndicatorDefinition(
        series_id="CPILFESL",
        name="Core CPI (Excluding Food and Energy)",
        description="Tracks underlying inflation trend",
        frequency="Monthly",
        seasonal_adjustment="SA",
        unit="Index 1982-84=100",
        interpretation="neutral"
    ),
    IndicatorDefinition(
        series_id="PCEPI",
        name="Personal Consumption Expenditures Price Index",
        description="Fed's preferred inflation measure",
        frequency="Monthly",
        seasonal_adjustment="SA",
        unit="Index 2017=100",
        interpretation="neutral"
    ),
    IndicatorDefinition(
        series_id="PCEPILFE",
        name="Core PCE Price Index",
        description="Excludes food and energy",
        frequency="Monthly",
        seasonal_adjustment="SA",
        unit="Index 2017=100",
        interpretation="neutral"
    ),
    IndicatorDefinition(
        series_id="PPIACO",
        name="Producer Price Index (Final Demand)",
        description="Measures price changes at the producer level",
        frequency="Monthly",
        seasonal_adjustment="NSA",
        unit="Index 1982=100",
        interpretation="neutral"
    ),
    IndicatorDefinition(
        series_id="T5YIE",
        name="5-Year Breakeven Inflation Rate",
        description="Derived from TIPS yields, market-based inflation expectations",
        frequency="Daily",
        seasonal_adjustment="NSA",
        unit="Percent",
        interpretation="neutral"
    ),
    IndicatorDefinition(
        series_id="CPIENGSL",
        name="Energy Price Index (CPI Energy Component)",
        description="Energy component of CPI",
        frequency="Monthly",
        seasonal_adjustment="SA",
        unit="Index 1982-84=100",
        interpretation="neutral"
    ),
]


# ============================================================================
# MONEY & MARKETS INDICATORS
# ============================================================================

MONEY_MARKETS_INDICATORS = [
    IndicatorDefinition(
        series_id="DFF",
        name="Effective Federal Funds Rate",
        description="Daily effective federal funds rate",
        frequency="Daily",
        seasonal_adjustment="NSA",
        unit="Percent",
        interpretation="neutral"
    ),
    IndicatorDefinition(
        series_id="DGS10",
        name="10-Year Treasury Constant Maturity Rate",
        description="Benchmark long-term interest rate",
        frequency="Daily",
        seasonal_adjustment="NSA",
        unit="Percent",
        interpretation="neutral"
    ),
    IndicatorDefinition(
        series_id="DGS2",
        name="2-Year Treasury Constant Maturity Rate",
        description="For yield curve analysis",
        frequency="Daily",
        seasonal_adjustment="NSA",
        unit="Percent",
        interpretation="neutral"
    ),
    IndicatorDefinition(
        series_id="YIELD_SPREAD",
        name="10Y minus 2Y Yield Spread",
        description="Common recession signal",
        frequency="Daily",
        seasonal_adjustment="NSA",
        unit="Percent",
        interpretation="higher_is_better",
        is_derived=True,
        source_series=["DGS10", "DGS2"]
    ),
    IndicatorDefinition(
        series_id="M2SL",
        name="M2 Money Stock",
        description="Broad measure of money supply",
        frequency="Monthly",
        seasonal_adjustment="SA",
        unit="Billions of Dollars",
        interpretation="neutral"
    ),
    IndicatorDefinition(
        series_id="TOTALSL",
        name="Consumer Credit Outstanding (Total)",
        description="Household and consumer debt",
        frequency="Monthly",
        seasonal_adjustment="NSA",
        unit="Billions of Dollars",
        interpretation="neutral"
    ),
    IndicatorDefinition(
        series_id="TWEXBGSMTH",
        name="Nominal Broad U.S. Dollar Index",
        description="Value of USD vs major trading partners (goods and services)",
        frequency="Monthly",
        seasonal_adjustment="NSA",
        unit="Index Jan 2006=100",
        interpretation="neutral"
    ),
]


# Category mapping
INDICATOR_CATEGORIES = {
    "growth_output": GROWTH_OUTPUT_INDICATORS,
    "labor_employment": LABOR_EMPLOYMENT_INDICATORS,
    "inflation_prices": INFLATION_PRICES_INDICATORS,
    "money_markets": MONEY_MARKETS_INDICATORS,
}


def get_indicators_by_category(category: str) -> List[IndicatorDefinition]:
    """Get all indicators for a specific category."""
    if category not in INDICATOR_CATEGORIES:
        raise ValueError(
            f"Unknown category '{category}'. "
            f"Valid categories: {list(INDICATOR_CATEGORIES.keys())}"
        )
    return INDICATOR_CATEGORIES[category]


def get_all_indicators() -> List[IndicatorDefinition]:
    """Get all indicators across all categories."""
    all_indicators = []
    for indicators in INDICATOR_CATEGORIES.values():
        all_indicators.extend(indicators)
    return all_indicators


def get_indicator_by_id(series_id: str) -> Optional[IndicatorDefinition]:
    """Find an indicator by its series ID."""
    for indicator in get_all_indicators():
        if indicator.series_id == series_id:
            return indicator
    return None


def calculate_history_days(frequency: str) -> int:
    """
    Calculate the number of days of history to fetch based on data frequency.
    
    V2 requirements:
    - All frequencies: 20 years of history (7300 days) for robust percentile calculations
    - Adaptive resampling applied after fetch to manage data volume
    
    Args:
        frequency: Data frequency (Daily, Weekly, Monthly, Quarterly)
        
    Returns:
        Number of days to fetch (always 20 years = 7300 days)
    """
    # V2: Fetch 20 years for all indicators to calculate meaningful percentiles
    # Resampling is handled separately in export scripts
    return 7300  # 20 years
