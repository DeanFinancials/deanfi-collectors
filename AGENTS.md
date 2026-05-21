# AGENTS.md — deanfi-collectors

Canonical instruction file for coding agents working in this repo.

## What This Repo Does

Runs Python data collectors as GitHub Actions workflows. Each collector fetches
financial data from an external API (Yahoo Finance/yfinance, Finnhub, Alpaca,
FRED) and writes JSON files to disk. Workflows then commit those files to the
`deanfi-data` GitHub repository, which is the single source of truth for all
dashboard data on the website.

## Data Flow (end-to-end)

```
deanfi-collectors (this repo)
  └─ GitHub Actions workflow
       └─ Python script → writes JSON to disk
            └─ git push → deanfi-data repo (GitHub)
                  └─ sync-to-r2.yml (triggers on every push with JSON changes)
                        └─ Cloudflare R2 bucket (https://r2.deanfi.com)
                              └─ fetchFromR2 utility → useR2Data hook → React dashboard
```

**Key facts for agents:**
- Data IS served from the R2 bucket at `https://r2.deanfi.com`. The `useR2Data`
  hook name is accurate — it fetches from R2 via `src/utils/r2-fetch.ts`.
- The Cloudflare Pages Function proxy at `functions/data/[[path]].ts` exists in
  the website but is NOT the active data path for dashboards. Do not route new
  dashboard data through it.
- The R2 sync (`deanfi-data/.github/workflows/sync-to-r2.yml`) is a second
  failure point. If it fails, data is in GitHub but not in R2, and the website
  sees stale data even if collectors ran fine. Check `sync-to-r2.yml` run history
  in `deanfi-data` when debugging website staleness.
- `data_freshness.json` written to `deanfi-data` is automatically synced to R2
  by `sync-to-r2.yml`. The website fetches it from
  `https://r2.deanfi.com/data_freshness.json`.
- Worst-case latency from collector run to user seeing data: ~16 minutes
  (10-min collection cycle + ~1 min R2 sync + 5-min React Query staleTime).

## Repo Layout

```
.github/workflows/    GitHub Actions automation (one file per data domain)
shared/               Shared Python utilities (caching, FRED client, universes)
<domain>/             One directory per collector (config.yml + fetch_*.py)
deanfi-data/          (not in this repo — the sibling data repo on GitHub)
```

## Workflow Architecture

- All workflows share concurrency group `deanfi-data-repo` with
  `cancel-in-progress: false`. This serialises pushes to `deanfi-data` and
  prevents git conflicts.
- The commit pattern is: collect → `git add` → `git commit` → `git pull --rebase`
  → `git push`. The rebase step handles any external pushes that happened during
  the run.
- Price cache (parquet files) is stored via `actions/cache`, not committed to
  `deanfi-data`. Do not add `cache/` back to `git add` lines.

## Key Files

- `implementation-plan.md` — active reliability improvement checklist
- `CONTEXT.md` — domain glossary and reliability decisions
- `requirements.txt` — Python dependencies
- `.env.example` — required environment variables

## Collectors Quick Reference

| Directory | Data Source | Schedule | Output → deanfi-data path |
|---|---|---|---|
| `advancedecline/` | yfinance | every 10 min (market hrs) | `advance-decline/` |
| `majorindexes/` | yfinance | every 10 min (market hrs) | `major-indexes/` |
| `meanreversion/` | yfinance | every 10 min (market hrs) | `meanreversion/` |
| `impliedvol/` | yfinance | every 10 min (market hrs) | `implied-volatility/` |
| `growthoutput/` | FRED | daily weekdays | `economy-breadth/` |
| `inflationprices/` | FRED | daily weekdays | `economy-breadth/` |
| `laboremployment/` | FRED | daily weekdays | `economy-breadth/` |
| `moneymarkets/` | FRED | daily weekdays | `economy-breadth/` |
| `consumercredit/` | FRED | daily weekdays | `consumer-credit/` |
| `housingaffordability/` | FRED | daily weekdays | `housing-affordability/` |
| `earningscalendar/` | Finnhub | nightly | `earnings-calendar/` |
| `earningssurprises/` | Finnhub | nightly | `earnings-surprises/` |
| `analysttrends/` | Finnhub | nightly | `analyst-trends/` |
| `spgrowth/` | SEC EDGAR + fallbacks | nightly | `sp100growth/`, `sp500growth/` |
| `optionswhales/` | Alpaca | twice daily | `options-whales/` |
| `stockwhales/` | Alpaca | twice daily | `stock-whales/` |
| `etffundflows/` | yfinance | daily after close | `etf-fund-flows/` |
| `supportresistence/` | Alpaca | daily 5am ET | `supportresistence/` |
| `dailynews/` | Finnhub | manual only | `daily-news/` |

<!-- BEGIN COWORKER DELEGATION -->

## Coworker Delegation Tools

Delegation tools route bulk I/O tasks to a cheap worker model, preserving expensive-model tokens for reasoning. Use these tools whenever the task is large, repetitive, or read-heavy — not when it requires judgment, debugging, or architecture decisions.

---

## Prerequisites

Before using delegation tools, ensure:

- `~/ai-scripts` is on your PATH
- `~/ai-scripts/.env` contains valid credentials (`WORKER_API_KEY`, `WORKER_BASE_URL`, `WORKER_MODEL`)
- Worker calls can take longer than ordinary shell commands. Configure your agent shell/tool timeout high enough for `ask-kimi` and `kimi-write`.
- **Network approval:** Codex may prompt for network approval on the first outbound API call from a Python script. Approve once to allow subsequent calls in the session.

---

### `ask-kimi` — Read-heavy analysis and Q&A

**When to use:** files >400 lines OR 3+ files at once. Any bulk read task where you would otherwise spend many tokens just ingesting content.

**Usage:**

```
run ask-kimi <file1> <file2> ... --question "<question>"
```

**Examples:**
- Summarise a large module: run `ask-kimi src/core.py --question "What does this module do and what are its public interfaces?"`
- Cross-file audit: run `ask-kimi src/ tests/ --question "List every place error handling is missing"`

`ask-kimi` accepts files and directories. Directories are expanded recursively while skipping common noisy paths such as `.git`, `node_modules`, `.venv`, `__pycache__`, `dist`, and `build`. Generated content prints to stdout; usage, finish reason, token counts, file count, and byte count print to stderr. Use `--dry-run` to inspect the resolved file set before calling the API.

---

### `kimi-write` — Boilerplate, tests, docs, and repetitive patterns

**When to use:** generating new files that follow a clear pattern (unit tests, docstrings, configuration stubs, changelog entries, repetitive transformations). The task must have a well-defined output format and a reference file the worker can imitate.

**Usage:**

```
run kimi-write --spec "<what to write>" --context <ref_file> --target <output_path>
```

**Examples:**
- Generate unit tests: run `kimi-write --spec "pytest unit tests for all public functions" --context src/parser.py --target tests/test_parser.py`
- Write a changelog entry: run `kimi-write --spec "CHANGELOG entry for v1.2.0 based on recent commits" --context CHANGELOG.md --target docs/changelog-entry.md`

---

### `extract-chat` — Strip JSONL transcripts to readable text

**When to use:** before passing session context to `ask-kimi` or `kimi-write` for documentation updates. Do not read raw JSONL transcripts yourself; extract them first.

**Usage:**

```
run extract-chat <transcript.jsonl> [--output <readable.txt>]
```

**Example:**
- Extract a session transcript to readable text: run `extract-chat ~/.claude/projects/my-project/session.jsonl --output /tmp/session.txt`

---

### Doc-update pipeline (MANDATORY)

**Never write documentation directly token-by-token.** Always use the extract → delegate → apply pipeline:

1. **Extract:** run `extract-chat <session.jsonl> --output context.txt` to get clean conversation text
2. **Delegate:** run `ask-kimi context.txt existing-doc.md --question "Produce the updated doc as a unified diff"` (or use `kimi-write` if generating from scratch)
3. **Apply:** apply the diff or write the output to the target file

This pipeline keeps doc-writing token costs near zero and ensures the output is grounded in the actual session transcript rather than your reconstruction of it.

---

### When NOT to delegate

Do not use delegation tools for:

- **Tasks estimable at fewer than ~2000 tokens** — the overhead of spawning a worker exceeds the savings. Just do it inline.
- **Debugging sessions** — requires tight read-modify-verify loops that the worker cannot do. Stay in-context.
- **Architecture and design decisions** — judgment about trade-offs belongs to you, not the worker.
- **Safety-critical code** — security logic, auth, cryptography, data integrity. Never delegate these writes.
- **Anything requiring exact line numbers** — the worker may paraphrase or reformat output. Use your own read for precise locations.
- **Tasks where the prompt itself requires more context than the answer** — if constructing the `--question` flag takes more work than answering it, skip the delegation.

<!-- END COWORKER DELEGATION -->
