# DeanFi Collectors — Domain Context

## Glossary

### Collector
A Python script (and its enclosing directory) that fetches data from one external source and writes one or more JSON files to disk. Each collector is independent: its failure must not prevent other collectors from running or committing.

### Run
One execution of a GitHub Actions workflow job. A run succeeds if it commits at least one updated data file to the data repo. A run that commits nothing — even if all steps exited 0 — is equivalent to a failed run from the website's perspective.

### Data Freshness
How recently a given JSON file in `deanfi-data` was last successfully written. Freshness is tracked per-section (not per-workflow) via `data_freshness.json`.

### Staleness Threshold
The maximum age of a data file before it is considered stale. **1 hour** for high-frequency (10-min) data. Nightly data (earnings, economy, analyst trends, sp-growth) has a 24-hour threshold — one missed nightly run is recovered by the next night.

### Heartbeat
A `data_freshness.json` file written to the data repo by each workflow run, recording the `last_updated` timestamp per data section. The website reads this to display per-section freshness and optionally surface a "data may be delayed" banner.

### Market Pulse Input
A deterministic, writer-ready JSON package for one market date. It is built upstream from collected data, synced to R2, and consumed by the website's Market Pulse automation as the canonical market-data contract for AI drafting and validation. It should contain the numbers, source links, optional context statuses, and ranked catalysts needed to write the article without redoing heavy collection inside the website workflow. Editorial continuity summaries are owned by the website repo and merged later by the website workflow.

### Market Pulse Core Dataset
The required datapoints for automated Market Pulse generation: major index closes and daily changes, five-session index returns, breadth and five-session breadth lookback, moving-average participation, sector leaders and laggards, VIX and five-session VIX lookback, major ETF implied volatility, SPY technical levels and five-session SMA table, and ranked catalysts. Economy, earnings, fund flows, options whales, and stock whales are optional context modules unless a specific article run requires them.

### Optional Context Module
A non-blocking context block that may enrich a Market Pulse article when populated and relevant. Optional modules must declare whether they are included, omitted because stale, omitted because empty, or omitted because low relevance. The article may only cite optional modules marked included.

### Market Catalyst
A dated news, policy, earnings, macro, rates, commodity, or geopolitical item that plausibly explains the day's market behavior. Catalysts are collected and scored before article generation so the writing model receives a small ranked set instead of a raw news dump.

### Catalyst Ranker
An optional low-token AI classification step that ranks candidate Market Catalysts against the day's actual market moves. It does not write the article and does not invent facts; it only chooses which already-collected headlines best explain the session.

### Catalyst Completeness
The minimum catalyst quality bar for automated Market Pulse publishing. A normal daily article requires at least three ranked catalysts, while a Friday or weekly-wrap article requires at least five. If an official macro or policy release occurred that day, at least one ranked catalyst should come from an official source. Every ranked catalyst must include title, source, URL, publication time, category, relevance score, and a short explanation of why it matters.

### Market Hours Window
8:00am–5:00pm Eastern Time, Monday–Friday. High-frequency collectors must guard against running outside this window. The guard lives in the workflow YAML (a bash step that checks the current UTC time and exits 0 if outside the window) so the cron schedule itself can be timezone-agnostic.

### Concurrency Group
All workflows that write to `deanfi-data` share the group `deanfi-data-repo` with `cancel-in-progress: false`. This serialises pushes. A hung workflow blocks the entire queue — hence per-workflow timeouts are required.

---

## Reliability Decisions

### Collector Isolation
Each collector step in every workflow uses `continue-on-error: true`. The final copy step uses `cp ... 2>/dev/null || true` so missing output files from failed collectors do not abort the commit. One commit per workflow run captures all successfully produced files.

**Why:** A single transient yfinance or API error was killing entire runs, leaving all collectors' data stale even when they would have succeeded. With a 1-hour staleness threshold, partial updates are always preferable to no update.

### Single Resilient Commit Per Run
Each workflow does one `git add / commit / pull --rebase / push` at the end, committing whatever files were successfully produced. There is no per-collector commit.

**Why:** Per-collector commits would create 4–5 commits per 10-min run (~200/day) and increase rebase pressure on the shared concurrency group. With a 1-hour staleness tolerance, batching within a single run is acceptable.

### Timezone-Agnostic Scheduling
High-frequency crons use `5-55/10 12-21 * * 1-5` (UTC), covering both EST and EDT offsets year-round. A market-hours guard in the workflow exits cleanly (code 0) if the run fires outside 8am–5pm ET.

**Why:** Manual comment-toggling twice a year for DST transitions was a silent failure risk. Widening the window and guarding in code eliminates the manual step entirely.

### Per-Workflow Timeouts
| Workflow | `timeout-minutes` |
|---|---|
| market-data-10min | 10 |
| economy-indicators | 10 |
| earnings | 10 |
| analyst-trends | 10 |
| sp-growth | 30 |
| options-whales | 20 |
| stock-whales | 20 |
| etf-fund-flows | 15 |

**Why:** GitHub Actions defaults to 6 hours. A hung yfinance call in the 10-min workflow would block the entire `deanfi-data-repo` concurrency queue for hours, starving every other workflow.
