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
