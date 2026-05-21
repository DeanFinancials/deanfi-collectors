# R2 sync failure notifications for `deanfi-data`

### Parent PRD

`PRD-yfinance-rate-limit-resilience.md` — "Remaining work: R2 sync failure notifications (operational)"

### Type

HITL

### What to build

Enable GitHub Actions failure email notifications for the `deanfi-data` repository so that silent R2 sync failures are surfaced within minutes rather than discovered hours later when the website goes stale. Also review recent `sync-to-r2.yml` run history to determine whether silent R2 sync failures are already occurring.

No code changes required.

### Acceptance criteria

- [ ] GitHub Actions failure notification emails are enabled for the `deanfi-data` repo (Settings → Notifications → Actions → "Send email" on failure)
- [ ] `sync-to-r2.yml` run history has been reviewed for silent failures (failed steps with `continue-on-error: true`, unexpected skips, or zero-upload runs)
- [ ] Any silent failures found in the history are documented as follow-up issues or addressed

### User stories addressed

- User Story 25: R2 sync failures trigger a GitHub Actions failure email within minutes

### Requirements addressed

- PRD Solution: operational monitoring layer for R2 sync

### Blocked by

None — requires a human with admin access to the `deanfi-data` GitHub repository.

### Implementation notes

- Navigate to `deanfi-data` repo → Settings → Notifications → Actions → enable "Send email" on workflow failure for the account owner or relevant team members
- Review `sync-to-r2.yml` workflow run history in the Actions tab; look for: runs that completed green but uploaded 0 objects, steps that used `|| true` or `continue-on-error` masking a real error, or runs that were skipped unexpectedly
- If silent failures are found, check whether the R2 credentials (Cloudflare API token, bucket name, account ID) stored as GitHub secrets are still valid

### Testing notes

After enabling notifications:

- Intentionally trigger a failing condition (e.g., temporarily set an invalid R2 token in a test environment) and verify the failure email arrives
- Or simply monitor the next several `sync-to-r2.yml` runs to confirm failure emails are now received

### Risks and review notes

- This is a HITL issue: it requires a human with `deanfi-data` repo admin access to change the notification settings — it cannot be automated or completed by an agent
- Decision required: determine who should receive the failure emails (repo owner only, or a shared alias)
- If `sync-to-r2.yml` has `continue-on-error: true` on the sync step itself, notification emails may not fire even on real failures — review the workflow YAML and remove or scope `continue-on-error` on the sync step if that is the case
