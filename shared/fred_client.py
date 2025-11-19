#!/usr/bin/env python3
"""
FRED API Client
Handles all interactions with the Federal Reserve Economic Data (FRED) API.
"""
import os
import time
import requests
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import pandas as pd
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class FREDClient:
    """Client for interacting with FRED API."""
    
    BASE_URL = "https://api.stlouisfed.org/fred"
    
    def __init__(self, api_key: Optional[str] = None, rate_limit: float = 0.1):
        """
        Initialize FRED API client.
        
        Args:
            api_key: FRED API key (if None, reads from FRED_API_KEY env var)
            rate_limit: Minimum seconds between API requests (default 0.1)
        """
        self.api_key = api_key or os.getenv("FRED_API_KEY")
        if not self.api_key:
            raise ValueError(
                "FRED API key required. Set FRED_API_KEY environment variable "
                "or pass api_key parameter."
            )
        
        self.rate_limit = rate_limit
        self._last_request_time = 0
        self.session = requests.Session()
    
    def _rate_limit_wait(self):
        """Enforce rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        self._last_request_time = time.time()
    
    def _make_request(
        self, 
        endpoint: str, 
        params: Dict[str, Any],
        timeout: int = 30
    ) -> Dict[str, Any]:
        """
        Make a request to FRED API with rate limiting.
        
        Args:
            endpoint: API endpoint (e.g., 'series/observations')
            params: Query parameters
            timeout: Request timeout in seconds
            
        Returns:
            JSON response as dictionary
            
        Raises:
            requests.RequestException: On API errors
        """
        self._rate_limit_wait()
        
        url = f"{self.BASE_URL}/{endpoint}"
        params["api_key"] = self.api_key
        params["file_type"] = "json"
        
        response = self.session.get(url, params=params, timeout=timeout)
        response.raise_for_status()
        
        return response.json()
    
    def get_series_info(self, series_id: str) -> Dict[str, Any]:
        """
        Get metadata about a FRED series.
        
        Args:
            series_id: FRED series ID (e.g., 'GDPC1')
            
        Returns:
            Dictionary with series information
        """
        result = self._make_request("series", {"series_id": series_id})
        return result.get("seriess", [{}])[0]
    
    def get_series_observations(
        self,
        series_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        observation_start: Optional[str] = None,
        observation_end: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Get observations (data points) for a FRED series.
        
        Args:
            series_id: FRED series ID (e.g., 'GDPC1')
            start_date: Start date (YYYY-MM-DD), defaults to series start
            end_date: End date (YYYY-MM-DD), defaults to today
            observation_start: Alternative parameter name for start_date
            observation_end: Alternative parameter name for end_date
            
        Returns:
            DataFrame with 'date' and 'value' columns
        """
        params = {"series_id": series_id}
        
        if observation_start or start_date:
            params["observation_start"] = observation_start or start_date
        if observation_end or end_date:
            params["observation_end"] = observation_end or end_date
        
        result = self._make_request("series/observations", params)
        observations = result.get("observations", [])
        
        if not observations:
            return pd.DataFrame(columns=["date", "value"])
        
        # Convert to DataFrame
        df = pd.DataFrame(observations)
        
        # Convert date to datetime
        df["date"] = pd.to_datetime(df["date"])
        
        # Convert value to numeric (handle '.' for missing values)
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        
        # Keep only date and value columns
        df = df[["date", "value"]].copy()
        
        # Sort by date
        df = df.sort_values("date").reset_index(drop=True)
        
        return df
    
    def get_latest_observation(self, series_id: str) -> Optional[float]:
        """
        Get the most recent observation for a series.
        
        Args:
            series_id: FRED series ID
            
        Returns:
            Latest value, or None if no data available
        """
        df = self.get_series_observations(series_id)
        if df.empty:
            return None
        
        # Get last non-null value
        valid_data = df.dropna(subset=["value"])
        if valid_data.empty:
            return None
        
        return valid_data.iloc[-1]["value"]
    
    def get_series_range(
        self,
        series_id: str,
        start_date: str,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Get observations for a specific date range.
        
        Args:
            series_id: FRED series ID
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD), defaults to today
            
        Returns:
            DataFrame with date and value columns
        """
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")
        
        return self.get_series_observations(
            series_id,
            observation_start=start_date,
            observation_end=end_date
        )
    
    def get_multiple_series(
        self,
        series_ids: List[str],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict[str, pd.DataFrame]:
        """
        Get observations for multiple series.
        
        Args:
            series_ids: List of FRED series IDs
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            
        Returns:
            Dictionary mapping series_id to DataFrame
        """
        results = {}
        for series_id in series_ids:
            try:
                df = self.get_series_observations(
                    series_id,
                    observation_start=start_date,
                    observation_end=end_date
                )
                results[series_id] = df
            except Exception as e:
                print(f"Warning: Failed to fetch {series_id}: {e}")
                results[series_id] = pd.DataFrame(columns=["date", "value"])
        
        return results
    
    def calculate_percent_change(
        self,
        series_id: str,
        periods: int = 1,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        Calculate percent change for a series.
        
        Args:
            series_id: FRED series ID
            periods: Number of periods for change calculation
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            
        Returns:
            DataFrame with date, value, and pct_change columns
        """
        df = self.get_series_observations(
            series_id,
            observation_start=start_date,
            observation_end=end_date
        )
        
        if not df.empty:
            df["pct_change"] = df["value"].pct_change(periods=periods) * 100
        
        return df
