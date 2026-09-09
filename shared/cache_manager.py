"""
Intelligent caching system for market data downloads.

Adapted from marketbreadth cache system to work with aimarketdata scripts.

Provides:
- Incremental downloads (only fetch new data)
- Parquet-based storage (10x faster than CSV)
- Self-healing (auto-rebuilds if corrupted)
- Metadata tracking (last update, validity checks)

Cache Strategy:
- Age < 24 hours: Download last 5 trading days (intraday updates)
- Age 24-168 hours: Download last 10 trading days (daily updates  
- Age > 168 hours: Full rebuild (weekly refresh)

Usage:
    from shared.cache_manager import CachedDataFetcher
    
    fetcher = CachedDataFetcher(cache_dir="cache")
    df = fetcher.fetch_prices(
        tickers=['AAPL', 'GOOGL'],
        start_date='2024-01-01',
        cache_name='my_data'
    )
"""

import json
import hashlib
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple
import pandas as pd
import yfinance as yf
from shared.yf_retry import with_429_retry

# Cache settings
DEFAULT_MAX_AGE_HOURS = 168  # 1 week
INTRADAY_LOOKBACK_DAYS = 5
DAILY_LOOKBACK_DAYS = 10


class CacheMetadata:
    """Metadata for cached price data."""
    
    def __init__(
        self,
        last_update: datetime,
        ticker_count: int,
        data_start: str,
        data_end: str,
        source: str = "yfinance"
    ):
        self.last_update = last_update
        self.ticker_count = ticker_count
        self.data_start = data_start
        self.data_end = data_end
        self.source = source
    
    def to_dict(self) -> dict:
        return {
            "last_update": self.last_update.isoformat(),
            "ticker_count": self.ticker_count,
            "data_start": self.data_start,
            "data_end": self.data_end,
            "source": self.source
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "CacheMetadata":
        return cls(
            last_update=pd.Timestamp(data["last_update"]).to_pydatetime(),
            ticker_count=data["ticker_count"],
            data_start=data["data_start"],
            data_end=data["data_end"],
            source=data.get("source", "yfinance")
        )
    
    def age_hours(self) -> float:
        """Get cache age in hours."""
        return (datetime.now() - self.last_update).total_seconds() / 3600
    
    def is_valid(self, expected_tickers: int, max_age_hours: int = DEFAULT_MAX_AGE_HOURS) -> bool:
        """Check if cache is valid (not too old, ticker count matches)."""
        if self.age_hours() > max_age_hours:
            return False
        if self.ticker_count != expected_tickers:
            return False
        return True


class CachedDataFetcher:
    """Fetcher with intelligent caching for yfinance data."""
    
    def __init__(self, cache_dir: Optional[Path] = None):
        """
        Initialize cached data fetcher.
        
        Args:
            cache_dir: Directory for cache storage (default: ./cache)
        """
        self.cache_dir = Path(cache_dir) if cache_dir else Path("cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def fetch_prices(
        self,
        tickers: list,
        start_date: str = None,
        end_date: str = None,
        cache_name: str = "prices",
        period: str = None,
        force_refresh: bool = False,
        reuse_within_run: bool = False,
    ) -> pd.DataFrame:
        """
        Fetch price data with intelligent caching.
        
        Args:
            tickers: List of ticker symbols
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD), optional
            cache_name: Name for cache files
            period: yfinance period (e.g., '1y', '6mo'), overrides dates if provided
            force_refresh: Force full rebuild ignoring cache
            reuse_within_run: Reuse an identical successful request in this CI attempt
            
        Returns:
            DataFrame with OHLCV data for all tickers
        """
        cache_file = self.cache_dir / f"{cache_name}.parquet"
        metadata_file = self.cache_dir / f"{cache_name}_metadata.json"

        # A restored cache from another run must still be refreshed. Sharing only
        # identical requests within one attempt avoids five S&P 500 downloads.
        run_id = os.environ.get("GITHUB_RUN_ID")
        self._run_id = f"{run_id}:{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}" if run_id else None
        self._request_signature = hashlib.sha256(json.dumps(
            [sorted(set(tickers)), start_date, end_date, period]
        ).encode()).hexdigest()
        if reuse_within_run and self._run_id and not force_refresh and metadata_file.exists():
            try:
                saved = json.loads(metadata_file.read_text())
                if (saved.get("run_id") == self._run_id
                        and saved.get("request_signature") == self._request_signature):
                    cached = self._load_cache(cache_file)
                    if cached is not None and not cached.empty:
                        print(f"Reusing {cache_name} refreshed in this CI attempt", file=sys.stderr)
                        return cached
            except (OSError, ValueError):
                pass
        
        # Load existing metadata
        metadata = self._load_metadata(metadata_file) if not force_refresh else None
        
        # Determine download strategy
        if period:
            # Period-based download with incremental updates (matching marketbreadth)
            if metadata and cache_file.exists():
                cache_age_hours = metadata.age_hours()
                
                # Strategy based on cache age:
                # - Age < 24h: Incremental (last 5 days only)
                # - Age 24h-168h: Incremental (last 10 days only)
                # - Age > 168h (7 days): Full rebuild
                
                if cache_age_hours < 168:  # Less than 7 days - do incremental
                    # Determine lookback window
                    if cache_age_hours < 24:
                        lookback_days = 5
                        update_type = "intraday"
                    else:
                        lookback_days = 10
                        update_type = "daily"
                    
                    print(f"Cache age {cache_age_hours:.1f}h - {update_type} incremental update (last {lookback_days} days)", file=sys.stderr)
                    
                    # Download only recent data
                    from datetime import datetime, timedelta
                    incremental_start = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
                    new_df = self._download_with_dates(tickers, incremental_start, None)
                    
                    if new_df is not None and not new_df.empty:
                        # Load existing cache and merge
                        cached_df = self._load_cache(cache_file)
                        if cached_df is not None and not cached_df.empty:
                            # Merge: combine and deduplicate
                            print(f"Merging: cache={len(cached_df)} rows, new={len(new_df)} rows", file=sys.stderr)
                            combined = pd.concat([cached_df, new_df]).sort_index()
                            combined = combined[~combined.index.duplicated(keep='last')]
                            print(f"✓ Merged result: {len(combined)} rows", file=sys.stderr)
                            
                            # Save merged cache
                            self._save_cache(cache_file, combined)
                            self._save_metadata(metadata_file, combined, len(tickers))
                            return combined
                        else:
                            # Cache load failed, use new data
                            print("Warning: Cache load failed, using new data only", file=sys.stderr)
                            self._save_cache(cache_file, new_df)
                            self._save_metadata(metadata_file, new_df, len(tickers))
                            return new_df
                    else:
                        # Incremental download failed, try using stale cache
                        print("Warning: Incremental download failed, using stale cache", file=sys.stderr)
                        cached_df = self._load_cache(cache_file)
                        if cached_df is not None:
                            return cached_df
                        # Fall through to full download
                else:
                    # Weekly rebuild for stale cache
                    print(f"Cache stale ({cache_age_hours:.1f}h old > 168h), weekly rebuild...", file=sys.stderr)
            
            # Full download (no cache or weekly rebuild)
            print(f"Downloading {period} of data for {len(tickers)} symbols...", file=sys.stderr)
            df = self._download_with_period(tickers, period)
            if df is not None and not df.empty:
                self._save_cache(cache_file, df)
                self._save_metadata(metadata_file, df, len(tickers))
            return df
        
        # Date-based download with incremental logic
        download_start, download_end, is_incremental = self._determine_download_range(
            metadata, start_date, end_date
        )
        
        # Download new data
        new_df = self._download_with_dates(tickers, download_start, download_end)
        
        if new_df is None or new_df.empty:
            print("Download failed, attempting to use cached data", file=sys.stderr)
            cached_df = self._load_cache(cache_file)
            return cached_df if cached_df is not None else pd.DataFrame()
        
        # Merge with cache if incremental
        if is_incremental:
            cached_df = self._load_cache(cache_file)
            final_df = self._merge_data(cached_df, new_df, is_incremental)
        else:
            final_df = new_df
        
        # Save cache
        self._save_cache(cache_file, final_df)
        self._save_metadata(metadata_file, final_df, len(tickers))
        
        return final_df
    
    def _download_with_period(self, tickers: list, period: str):
        """Download data using yfinance period parameter."""
        try:
            data = with_429_retry(
                yf.download,
                tickers,
                retry_empty=True,
                period=period,
                progress=False,
                auto_adjust=True,
                threads=4
            )
            print(f"✓ Downloaded {period} data for {len(tickers)} symbols", file=sys.stderr)
            return data
        except Exception as e:
            print(f"✗ Download failed: {e}", file=sys.stderr)
            return None
    
    def _download_with_dates(self, tickers: list, start: str, end: str = None):
        """Download data using start/end dates."""
        try:
            print(f"Downloading data for {len(tickers)} symbols from {start}...", file=sys.stderr)
            data = with_429_retry(
                yf.download,
                tickers,
                retry_empty=True,
                start=start,
                end=end,
                progress=False,
                auto_adjust=True,
                threads=4
            )
            print(f"✓ Downloaded data for {len(tickers)} symbols", file=sys.stderr)
            return data
        except Exception as e:
            print(f"✗ Download failed: {e}", file=sys.stderr)
            return None
    
    def _determine_download_range(
        self,
        metadata,
        requested_start: str,
        requested_end: str = None
    ) -> Tuple[str, str, bool]:
        """Determine what date range to download based on cache state."""
        # No cache: full download
        if metadata is None:
            print("No cache found - full download required", file=sys.stderr)
            return requested_start, requested_end, False
        
        age_hours = metadata.age_hours()
        
        # Cache too old: full rebuild
        if age_hours > DEFAULT_MAX_AGE_HOURS:
            print(f"Cache age {age_hours:.1f}h exceeds max {DEFAULT_MAX_AGE_HOURS}h - full rebuild", file=sys.stderr)
            return requested_start, requested_end, False
        
        # Intraday update (< 24 hours)
        if age_hours < 24:
            lookback_days = INTRADAY_LOOKBACK_DAYS
            print(f"Cache age {age_hours:.1f}h - incremental update (last {lookback_days} days)", file=sys.stderr)
        else:
            # Daily update (24h - 7d)
            lookback_days = DAILY_LOOKBACK_DAYS
            print(f"Cache age {age_hours:.1f}h - incremental update (last {lookback_days} days)", file=sys.stderr)
        
        # Calculate incremental start date
        incremental_start = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
        
        return incremental_start, requested_end, True
    
    def _merge_data(self, cached_df, new_df: pd.DataFrame, is_incremental: bool) -> pd.DataFrame:
        """Merge new data with cached data."""
        if cached_df is None or cached_df.empty:
            print("No cache to merge - using fresh data", file=sys.stderr)
            return new_df
        
        if not is_incremental:
            print("Full rebuild - replacing cache", file=sys.stderr)
            return new_df
        
        # Incremental merge
        print(f"Merging: cache={len(cached_df)} rows, new={len(new_df)} rows", file=sys.stderr)
        
        # Combine and sort
        combined = pd.concat([cached_df, new_df]).sort_index()
        
        # Remove duplicate dates (keep newest)
        combined = combined[~combined.index.duplicated(keep='last')]
        
        print(f"Merged result: {len(combined)} rows", file=sys.stderr)
        
        return combined
    
    def _load_cache(self, cache_file: Path):
        """Load cached price data from parquet file."""
        if not cache_file.exists():
            return None
        
        try:
            df = pd.read_parquet(cache_file)
            print(f"Loaded cache: {len(df)} rows", file=sys.stderr)
            return df
        except Exception as e:
            print(f"Warning: Could not load cache: {e}", file=sys.stderr)
            return None
    
    def _save_cache(self, cache_file: Path, df: pd.DataFrame):
        """Save price data to parquet cache file."""
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(cache_file, engine='pyarrow', compression='snappy')
            print(f"Saved cache: {len(df)} rows", file=sys.stderr)
        except Exception as e:
            print(f"Warning: Could not save cache: {e}", file=sys.stderr)
    
    def _load_metadata(self, metadata_file: Path):
        """Load cache metadata from JSON file."""
        if not metadata_file.exists():
            return None
        
        try:
            data = json.loads(metadata_file.read_text())
            return CacheMetadata.from_dict(data)
        except Exception as e:
            print(f"Warning: Could not load cache metadata: {e}", file=sys.stderr)
            return None
    
    def _save_metadata(self, metadata_file: Path, df: pd.DataFrame, ticker_count: int):
        """Save cache metadata to JSON file."""
        try:
            metadata = CacheMetadata(
                last_update=datetime.now(),
                ticker_count=ticker_count,
                data_start=str(df.index.min().date()) if not df.empty else "",
                data_end=str(df.index.max().date()) if not df.empty else "",
                source="yfinance"
            )
            metadata_file.parent.mkdir(parents=True, exist_ok=True)
            payload = metadata.to_dict()
            payload['run_id'] = self._run_id
            payload['request_signature'] = self._request_signature
            metadata_file.write_text(json.dumps(payload, indent=2))
        except Exception as e:
            print(f"Warning: Could not save cache metadata: {e}", file=sys.stderr)
