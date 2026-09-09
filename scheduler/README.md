# Market collection scheduler

Cloudflare Cron Triggers dispatch `market-data-intraday.yml` on `main` at minutes
7, 22, 37, and 52 during the existing weekday collection window, 08:00 to 17:00
America/New_York. The UTC cron covers daylight saving changes. GitHub's original
cron remains a backup because its scheduled events have arrived hours apart.

The Worker only starts the existing collector. Data collection, validation,
publication to deanfi-data, and the subsequent R2 sync remain in their current
workflows. No public HTTP endpoint is enabled. No third party runtime dependencies
are needed.

## Deployment

`Deploy Market Scheduler` runs after scheduler changes on main or by manual
dispatch. It runs the Node tests, checks access, uploads the Worker and its secret
binding, sets the cron, and reads the schedule back to verify it.

Required GitHub secrets in this repository:

* `CLOUDFLARE_API_TOKEN`: account token with Workers Scripts Edit permission.
* `CLOUDFLARE_ACCOUNT_ID`: existing DeanFi account.
* `MARKET_SCHEDULER_GITHUB_TOKEN`: GitHub token with Actions read/write permission
  for DeanFinancials/deanfi-collectors. If absent, deployment uses the existing
  `DATA_REPO_TOKEN`, which must also be able to dispatch that workflow.

The GitHub token is uploaded directly as a Cloudflare encrypted secret binding;
it is never committed, written to deployment files, or printed in logs. Rotating
the GitHub secret requires rerunning deployment to update the Worker binding.

The managed Worker is `deanfi-market-scheduler`. `deploy.mjs` owns its cron and
configuration. To roll back, remove this Worker's Cron Trigger in Cloudflare.
The original GitHub schedule continues operating. Do not delete or alter the
separate contact email Worker.

## Duplicate protection and failures

Before dispatching, the Worker checks existing runs and skips active collectors
or runs created within 12 minutes. It reports authentication, API failures, and
collectors queued or active longer than 30 minutes as errors in Cloudflare logs.
It does not retry an ambiguous dispatch request, avoiding duplicate starts.

After acquiring the existing shared data repository concurrency lock, the
collector checks its freshly checked out freshness file. If all four intraday
sections were published within 10 minutes, it skips redundant collection.
Missing, stale, invalid, or future timestamps do not suppress collection.

GitHub runner availability and upstream API availability can still delay jobs.
The dashboard freshness probe retains its existing 65 minute intraday threshold.
The Worker removes reliance on GitHub cron delivery; it does not hide stale data.

## Verification

Run `node --test scheduler/worker.test.mjs` and
`python -m pytest tests/test_market_collection_schedule.py -q`.
Tests cover dispatch, duplicate suppression, stalled runs, API rejection, New York
time boundaries, daylight saving changes, weekends, and missing freshness data.

After deployment, allow up to 15 minutes for Cloudflare Cron Trigger propagation.
Verify two automatic runs titled `Market data (cloudflare)` approximately 15
minutes apart, successful data commits and R2 syncs, then the website freshness
probe. A deployment success alone is not confirmation of automatic collection.

References: [GitHub schedule limitations](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
and [Cloudflare Cron Triggers](https://developers.cloudflare.com/workers/configuration/cron-triggers/).
