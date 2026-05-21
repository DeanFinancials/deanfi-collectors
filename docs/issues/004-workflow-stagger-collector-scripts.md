# Workflow stagger between collector scripts in `market-data-10min.yml`

### Parent PRD

`PRD-yfinance-rate-limit-resilience.md` — "Remaining work: Workflow stagger (optional, low priority)"

### Type

AFK

### What to build

Add a `sleep 30` between each of the 6 scripts in the "Fetch all index data" shell block in `.github/workflows/market-data-10min.yml`. This spreads the request bursts across ~3 minutes without requiring any Python changes, providing an additional layer of rate-limit protection on top of the existing `with_429_retry` helpers.

No Python code changes. No new files. One targeted edit to the workflow YAML.

### Acceptance criteria

- [ ] A `sleep 30` (or equivalent) appears between each consecutive script invocation in the "Fetch all index data" step
- [ ] The total added latency is ≤ 150s (5 sleeps × 30s), within the 10-minute workflow `timeout-minutes` budget
- [ ] The workflow still runs all 6 scripts sequentially in the same step (no restructuring)
- [ ] A CI run with all 6 scripts completing successfully still produces a valid commit

### User stories addressed

- Referenced in PRD "Remaining work" as an optional defence-in-depth measure

### Requirements addressed

- PRD Solution point 5 (defence-in-depth against rate limit cascade)
- PRD Implementation Decisions — Remaining work: "Workflow stagger (optional, low priority)"

### Blocked by

None — can start immediately. Independent of issues 001, 002, and 003.

### Implementation notes

- The "Fetch all index data" step in `market-data-10min.yml` currently runs the 6 scripts sequentially in a single `run:` block — locate that block and insert `sleep 30` between each `python` invocation
- The step uses `continue-on-error: true` on the job level, so a failure in one script does not block subsequent scripts or the sleep — the stagger behaviour is preserved even on partial failures
- 30s is chosen to match the `with_429_retry` default sleep, so a rate-limited burst during script N has time to recover before script N+1 starts
- Do not add a sleep after the final script (no benefit, wastes time)

### Testing notes

No automated tests. Verify manually:

- Trigger the `market-data-10min` workflow and confirm the "Fetch all index data" step takes ~3 minutes longer than before (the 5 × 30s sleeps appear in the step log)
- Confirm the step still exits 0 and all output files are produced

### Risks and review notes

- Low risk: the only change is added latency in a non-critical path
- If the workflow's `timeout-minutes: 10` is already tight, the 150s overhead could cause timeouts — verify the typical step runtime before merging and increase `timeout-minutes` if needed
- This is defence-in-depth; it does not replace the fixes in issues 001, 002, and 003. Pick it up after those are merged
