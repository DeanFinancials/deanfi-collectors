# Domain Context

Glossary of terms used across the collectors, workflows and the downstream `deanfi-data` and website repos. How the pieces fit together is in `docs/architecture.md`.

### Collector
A Python script (and its directory) that fetches data from one external source and writes one or more JSON files to disk. Collectors are listed in `docs/collectors.md`.

### Run
One execution of a GitHub Actions workflow job. From the website's point of view a run that commits nothing is the same as a failed run, even if every step exited 0.

### Section
A top-level directory in `deanfi-data` (for example `major-indexes/`) that one workflow owns and publishes.

### Data Freshness
How recently a section was last successfully written, recorded per section as `sections.<section>.last_updated` in `data_freshness.json` at the root of `deanfi-data`. The website reads it from R2 to show per-section freshness and a "data may be delayed" banner.

### Staleness Threshold
The maximum age before the website's freshness banner treats a section as stale: 55 minutes for intraday market sections, 26 hours for nightly sections (defined in the website repo). One missed intraday run stays well inside the limit, and a missed nightly run is recovered by the next night.

### Market Hours Window
Weekdays 08:00–17:00 America/New_York. Intraday market collection only runs inside it; `scripts/check_market_collection.py` applies the window in code so cron can stay in UTC year-round.

### Handoff
A `market-data-intraday.yml` run dispatched by the previous run's timer job rather than by cron. See `scheduler/README.md`.

### Concurrency Group
`deanfi-data-repo`: the GitHub Actions concurrency group every pushing job shares, so pushes to `deanfi-data` are serialised. A hung job blocks the queue, which is why every job has a timeout.

### Fetch Guard
The rule that a collector exits non-zero instead of writing a payload when zero tickers succeeded (`shared/fetch_guard.py`), so the previous good file survives.

### Snapshot Validator
`scripts/validate_snapshots.py`: the commit-time check that refuses to replace a non-empty market snapshot with an empty, null or malformed one.

### Market Pulse Input
A deterministic, writer-ready JSON package for one market date. The deanfi-data workflow combine-daily-snapshots.yml builds it from collected data; it syncs to R2 and the website's Market Pulse automation uses it as the canonical market-data contract for AI drafting and validation. It carries the numbers, source links, optional context statuses and ranked catalysts needed to write the article. Editorial continuity summaries are owned by the website and merged there.

### Market Pulse Core Dataset
The datapoints Market Pulse generation requires: major index closes and daily changes, five-session index returns, breadth and its five-session lookback, moving-average participation, sector leaders and laggards, VIX and its five-session lookback, major ETF implied volatility, SPY technical levels and five-session SMA table, and ranked catalysts. Economy, earnings, fund flows, options whales and stock whales are optional context modules.

### Optional Context Module
A non-blocking block that may enrich a Market Pulse article. Each declares whether it is included, or omitted because stale, empty or low relevance. Articles may only cite modules marked included.

### Market Catalyst
A dated news, policy, earnings, macro, rates, commodity or geopolitical item that plausibly explains the day's market moves. `dailynews/collect_catalysts.py` collects Finnhub news and official RSS feeds, deduplicates and scores them, and writes `daily-news/market_catalysts.json`, so the writing model gets a small ranked set instead of a raw news dump.

### Catalyst Ranker
An optional low-token AI step in `deanfi-data` that ranks candidate catalysts against the day's market moves. It does not write the article or invent facts.

### Catalyst Completeness
The minimum catalyst bar for automated Market Pulse publishing: at least three ranked catalysts on a normal day, five for a Friday or weekly wrap (`expected_min_catalysts` in `dailynews/collect_catalysts.py`). If an official macro or policy release occurred that day, at least one ranked catalyst should come from an official source. Every ranked catalyst needs title, source, URL, publication time, category, relevance score and a short reason it matters.
