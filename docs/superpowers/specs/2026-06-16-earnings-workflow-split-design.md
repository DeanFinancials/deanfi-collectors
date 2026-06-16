# Earnings Workflow Split Design

Date: 2026-06-16
Repo: `deanfi-collectors`
Status: Approved design, pending implementation

## Problem

The production Earnings Sentiment Dashboard is serving stale data because the `Earnings Collection` workflow is structurally unable to complete within its configured runtime budget.

Observed production state on 2026-06-16:

- `https://r2.deanfi.com/earnings-calendar/earnings_calendar.json` still reports `metadata.generated_at = "2026-05-07 05:03:04"`.
- `https://r2.deanfi.com/earnings-surprises/earnings_surprises.json` still reports `metadata.generated_at = "2026-05-07 05:12:09"`.
- `https://r2.deanfi.com/data_freshness.json` has no `earnings-calendar` or `earnings-surprises` section entries.
- The latest scheduled `earnings.yml` GitHub Actions runs are completing with `conclusion = cancelled`, while `analyst-trends.yml` succeeds nightly and `deanfi-data` R2 sync runs succeed normally.

Root cause:

- The current [`.github/workflows/earnings.yml`](../../../.github/workflows/earnings.yml) runs both `earningscalendar/fetch_earnings_calendar.py` and `earningssurprises/fetch_earnings_surprises.py` in one job with `timeout-minutes: 10`.
- The calendar collector alone performs roughly one rate-limited Finnhub call per S&P 500 ticker. The surprises collector then performs another full ticker sweep.
- Combined runtime exceeds the job budget before copy, `data_freshness.json` update, commit, and push can occur.

## Goals

- Restore reliable nightly publication for both earnings datasets.
- Isolate `earnings-calendar` and `earnings-surprises` so one collector can fail or run long without blocking the other.
- Preserve the existing downstream contract used by `deanfi-data`, R2 sync, and `deanfi-website`.
- Make freshness reporting accurate for each earnings dataset independently.
- Update repo docs that currently imply a single `earnings.yml` path.

## Non-Goals

- No schema changes to `earnings_calendar.json` or `earnings_surprises.json`.
- No dashboard code changes in `deanfi-website` unless verification reveals a broken assumption.
- No changes to `deanfi-data` sync-to-R2 logic unless implementation uncovers a missing trigger.
- No optimization of Finnhub collector internals in this change set; the fix is workflow isolation first.

## Recommended Approach

Split the current monolithic earnings workflow into two independent workflows:

1. `earnings-calendar.yml`
2. `earnings-surprises.yml`

Each workflow will:

- check out `deanfi-collectors`
- check out `deanfi-data`
- install Python dependencies
- run exactly one collector
- copy exactly one output directory into `deanfi-data`
- update exactly one section in `data_freshness.json`
- commit and push only the affected dataset plus freshness file

Both workflows will keep the shared concurrency group `deanfi-data-repo` so writes remain serialized. Their schedules will be staggered by about 20 minutes to reduce queueing and avoid needless contention while still keeping both datasets in the same nightly update window.

## Alternatives Considered

### 1. Increase the timeout on `earnings.yml`

Pros:

- Smallest code diff.

Cons:

- Keeps calendar and surprises coupled.
- One slow collector still blocks the other collector and all downstream publish steps.
- Run history remains ambiguous because one failed job can hide which dataset actually stalled.

Rejected because it treats the symptom, not the operational weakness.

### 2. Keep one workflow file but split into two jobs

Pros:

- Better than a single long-running job.
- Smaller naming and documentation changes.

Cons:

- Run history is still grouped under one workflow.
- Scheduling and operational ownership remain less clear than separate workflows.
- Future debugging is more cumbersome because one workflow page mixes two distinct pipelines.

Rejected because separate workflows provide cleaner isolation and observability.

## Detailed Design

## Workflow Topology

Remove the current `earnings.yml` workflow and replace it with:

- `.github/workflows/earnings-calendar.yml`
- `.github/workflows/earnings-surprises.yml`

Suggested schedules:

- `earnings-calendar.yml`: `45 3 * * 2-6`
- `earnings-surprises.yml`: `5 4 * * 2-6`

Rationale:

- keeps both jobs in the same overnight Eastern window
- gives the calendar collector a head start
- reduces direct queue contention on the shared `deanfi-data-repo` concurrency group

Each workflow should have its own human-readable name so GitHub Actions history immediately shows which dataset is affected.

## Publish Contract

`earnings-calendar.yml` will publish:

- `earnings-calendar/earnings_calendar.json`
- `data_freshness.json` entry for `earnings-calendar`

`earnings-surprises.yml` will publish:

- `earnings-surprises/earnings_surprises.json`
- `data_freshness.json` entry for `earnings-surprises`

Neither workflow should touch the other earnings directory. This preserves independence and prevents one dataset from being re-committed only because the other changed.

## Failure Behavior

If one collector fails:

- its workflow run fails or skips publish
- its `data_freshness.json` section remains unchanged
- the sibling workflow can still run and publish successfully
- `deanfi-data` and R2 still receive the healthy dataset

This is the desired failure mode because it localizes operational damage and makes staleness truthful.

## Downstream Impact Assessment

### `deanfi-data`

No schema or path changes required.

Expected effects:

- more granular commits instead of a single earnings commit
- `sync-to-r2.yml` continues to trigger on pushed JSON changes
- `data_freshness.json` becomes accurate again for both earnings sections

### R2

No code changes required. R2 receives whatever `deanfi-data` pushes through the existing sync workflow.

### `deanfi-website`

No application code changes expected because the website already fetches:

- `earnings-calendar/earnings_calendar.json`
- `earnings-surprises/earnings_surprises.json`
- `analyst-trends/recommendation_trends.json`
- `analyst-trends/sector_recommendation_trends.json`

The website already merges these sources client-side. The break was stale upstream data, not a coupling assumption in the app code.

Potential website-visible improvement after the fix:

- freshness banners and “last updated” displays will begin reflecting independent earnings dataset timestamps again once production data is republished.

### Documentation / Runbooks

Update references that assume a single `earnings.yml` workflow or a unified earnings collector path. At minimum:

- workflow reference docs in `deanfi-collectors/.github/workflows/README.md`
- any runbook or repo docs referencing `earnings.yml`

## Testing And Verification Plan

Implementation verification must cover:

1. YAML validity for both new workflows.
2. Reference scan showing no stale repo references to `earnings.yml` remain where they would mislead operators.
3. Workflow logic diff review confirming:
   - each workflow copies only its own dataset
   - each workflow updates only its own `data_freshness.json` section
   - commit scopes are limited to the intended files
4. Production follow-up after merge:
   - confirm new GitHub Actions runs are `success`
   - confirm `deanfi-data` receives fresh commits for each earnings path
   - confirm R2 files advance past 2026-05-07
   - confirm `data_freshness.json` includes both earnings sections

## Risks

### Risk: stale references to removed workflow

Mitigation:

- search repo for `earnings.yml`
- update docs during the same change

### Risk: overlapping writes to `deanfi-data`

Mitigation:

- preserve shared `deanfi-data-repo` concurrency group
- stagger schedules

### Risk: one dataset still exceeds its own runtime budget

Mitigation:

- give each workflow a realistic timeout sized to one collector, not both
- if one collector still proves too slow in production, optimize that collector separately without re-coupling the workflows

## Implementation Notes

- The old `earnings.yml` should be removed to avoid duplicate scheduling and operator confusion.
- The new workflow names should be explicit enough that production failures can be diagnosed from the Actions page without reading YAML.
- Timeout values should be set per workflow based on a single collector’s expected runtime rather than copied from the old combined job.

## Success Criteria

The change is successful when all of the following are true:

- `earnings-calendar.yml` runs successfully on schedule and publishes refreshed calendar data.
- `earnings-surprises.yml` runs successfully on schedule and publishes refreshed surprises data.
- `data_freshness.json` contains current `earnings-calendar` and `earnings-surprises` entries.
- R2 serves earnings files with `generated_at` timestamps later than 2026-05-07.
- The website’s Earnings Sentiment Dashboard is no longer stuck on May 7, 2026 data.
