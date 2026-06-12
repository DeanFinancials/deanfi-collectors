"""
GSC topics collector — authentication, Search Analytics fetch, and topic building.

AC4 / NFR-3 compliance:
  - Access token is placed only in the Authorization: Bearer header.
  - HTTP status codes are logged on failure; token and secret values are NEVER written
    to any log message.
  - On missing credentials, SourceFetchError is raised before any API call is attempted.
"""
import datetime
import logging
import os
import time
import urllib.parse

import requests
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials

from .gsc_topics_utils import (
    SourceFetchError,
    assign_category,
    is_quality_query,
    opportunity_score,
    slugify,
)

logger = logging.getLogger(__name__)

_TOKEN_URI = "https://oauth2.googleapis.com/token"
_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
_SEARCH_ANALYTICS_URL = (
    "https://searchconsole.googleapis.com/webmasters/v3/sites/{site_url}/searchAnalytics/query"
)


def authenticate_gsc() -> str:
    """
    Return a valid short-lived access token using the stored refresh credentials.

    Raises SourceFetchError if any of the three env vars are missing or if the
    token refresh fails (e.g. invalid_grant).  The client secret and refresh token
    are never written to log output.
    """
    client_id = os.environ.get("GSC_CLIENT_ID", "")
    client_secret = os.environ.get("GSC_CLIENT_SECRET", "")
    refresh_token = os.environ.get("GSC_REFRESH_TOKEN", "")

    missing = [
        k for k, v in [
            ("GSC_CLIENT_ID", client_id),
            ("GSC_CLIENT_SECRET", client_secret),
            ("GSC_REFRESH_TOKEN", refresh_token),
        ]
        if not v
    ]
    if missing:
        raise SourceFetchError(f"GSC credentials not set: {', '.join(missing)}")

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=_TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=[_SCOPE],
    )
    try:
        creds.refresh(GoogleRequest())
    except RefreshError as exc:
        # Log error type only — never log client_secret or refresh_token values
        raise SourceFetchError(f"GSC token refresh failed: {type(exc).__name__}") from exc

    return creds.token


def fetch_search_analytics(
    access_token: str,
    site_url: str,
    window_days: int,
    excluded_prefixes: list,
    max_retries: int = 3,
    base_delay: float = 2.0,
) -> list:
    """
    Fetch Search Analytics rows, filter excluded pages, build and return topic entries.

    Rows whose page URL path starts with any excluded_prefix are dropped before
    entries are built.  Results are sorted by opportunity score descending.

    AC4 / NFR-3: HTTP status codes logged on failure; access_token never logged.
    Raises SourceFetchError on 401/403 (auth failure) or after all retries exhausted.
    """
    site_encoded = urllib.parse.quote(site_url, safe="")
    url = _SEARCH_ANALYTICS_URL.format(site_url=site_encoded)
    # access_token lives only in this header — not interpolated into any log message
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    today = datetime.date.today()
    start_date = (today - datetime.timedelta(days=window_days)).isoformat()
    body = {
        "startDate": start_date,
        "endDate": today.isoformat(),
        "dimensions": ["query", "page"],
        "rowLimit": 1000,
        "dataState": "final",
    }

    resp = None
    for attempt in range(max_retries):
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=30)
            if resp.status_code == 200:
                break
            status = resp.status_code
            # AC4 / NFR-3: log status code only, never the Bearer token value
            logger.warning(
                "GSC Search Analytics HTTP %d (attempt %d/%d)",
                status, attempt + 1, max_retries,
            )
            if status in (401, 403):
                raise SourceFetchError(f"GSC API auth error: HTTP {status}")
            # 5xx and other non-2xx: fall through to retry
        except requests.RequestException as exc:
            logger.warning(
                "GSC transport error (attempt %d/%d): %s",
                attempt + 1, max_retries, type(exc).__name__,
            )
            resp = None

        if attempt < max_retries - 1:
            time.sleep(base_delay * (2 ** attempt))
    else:
        raise SourceFetchError("GSC Search Analytics API failed after all retries")

    try:
        data = resp.json()
    except ValueError as exc:
        raise SourceFetchError(f"GSC API returned non-JSON: {exc}") from exc

    rows = data.get("rows", [])  # absent "rows" key = no impressions, not an error
    today_str = today.isoformat()
    entries = []
    dropped_noise = 0

    for row in rows:
        keys = row.get("keys", [])
        if len(keys) < 2:
            continue
        query_text = keys[0]
        page_url = keys[1]

        # Drop raw-GSC-export noise (operator/quoted/date-stamped/gibberish queries)
        # before it can become a topic the website would have to defend against.
        if not is_quality_query(query_text):
            dropped_noise += 1
            continue

        # AC2: exclude queries already served at an /insights/* page
        path = urllib.parse.urlparse(page_url).path
        if any(path.startswith(prefix) for prefix in excluded_prefixes):
            continue

        impressions = float(row.get("impressions", 0))
        clicks = float(row.get("clicks", 0))
        position = float(row.get("position", 0))

        entries.append({
            "slug": slugify(query_text),
            "title_working": query_text.title(),
            "category": assign_category(query_text),
            "vertical": None,
            "target_keyword": query_text,
            "secondary_keywords": [],
            "internal_link_targets": [],
            "facts_refs": [],
            "source": "gsc",
            "gsc_evidence": {
                "impressions": impressions,
                "avg_position": round(position, 2),
                "clicks": clicks,
                "window": f"{window_days}d",
            },
            "status": "suggested",
            "added_at": today_str,
        })

    if dropped_noise:
        logger.info("Dropped %d low-quality GSC queries (operator/quoted/date/gibberish)", dropped_noise)

    entries.sort(
        key=lambda e: opportunity_score(
            e["gsc_evidence"]["impressions"], e["gsc_evidence"]["avg_position"]
        ),
        reverse=True,
    )
    return entries


def load_seed_topics(config: dict) -> list:
    """
    Materialize curated seed topics, applying defaults so the config can stay terse.

    `added_at` is stamped with today's date on every run so curated seeds never age
    out of the freshness probe during a GSC drought; `source`/`status`/`gsc_evidence`
    get their seed defaults when omitted. Values already present in the config win.
    """
    today = datetime.date.today().isoformat()
    seeds = []
    for seed in config.get("seed_topics", []):
        entry = dict(seed)
        entry.setdefault("source", "wes")
        entry.setdefault("status", "suggested")
        entry.setdefault("added_at", today)
        if "gsc_evidence" not in entry:
            entry["gsc_evidence"] = None
        seeds.append(entry)
    return seeds


def fetch_gsc_topics(config: dict) -> list:
    """
    Return merged list of GSC-derived + seed topic entries.

    Raises SourceFetchError on missing credentials, token refresh failure,
    or GSC API failure.  Seeds are appended after GSC entries; GSC wins on
    slug collision.
    """
    site_url = config.get("site_url", "sc-domain:deanfi.com")
    window_days = int(config.get("window_days", 90))
    max_topics = int(config.get("max_topics", 50))
    min_impressions = float(config.get("min_impressions", 5))
    excluded_prefixes = config.get("excluded_page_prefixes", ["/insights/"])

    access_token = authenticate_gsc()

    gsc_entries = fetch_search_analytics(
        access_token, site_url, window_days, excluded_prefixes,
    )

    gsc_entries = [
        e for e in gsc_entries
        if e["gsc_evidence"]["impressions"] >= min_impressions
    ]
    gsc_entries = gsc_entries[:max_topics]

    seeds = load_seed_topics(config)
    gsc_slugs = {e["slug"] for e in gsc_entries}
    unique_seeds = [s for s in seeds if s.get("slug") not in gsc_slugs]

    return gsc_entries + unique_seeds
