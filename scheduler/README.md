# Intraday collection handoffs

GitHub's scheduled events can arrive hours late or be dropped. After each
intraday collector run, a separate job dispatches the next run directly through
the GitHub API. This keeps an active session moving without waiting for another
cron event. No external scheduler or additional secret is required.

## Operation

- The timer continues across nights, weekends, and date boundaries. Cron remains
  a recovery path if a chain fails or is cancelled; normal daily startup no
  longer waits for a scheduled event.
- Handoffs set `collect_data=false` outside weekdays 08:00 to 17:00
  America/New_York. Those runs skip the entire collection job, including its
  runner, dependencies, API requests, and data-repository lock. Only the slim
  timer runs until the next collection window, including daylight saving time.
- The next run targets 15 minutes after the current run was created. A timer
  waits at most 13 minutes to fit the ubuntu-slim runner's 15-minute job limit.
  Quick skipped collections may therefore hand off slightly sooner.
- A newer cron, push, manual, or handoff run takes ownership. The timer checks
  again immediately before dispatch to suppress overlapping chains.
- Collection and timers have separate concurrency groups. Waiting never holds
  the shared deanfi-data repository write lock. A recent-publication guard skips
  collection when all four intraday sections were updated within ten minutes.
- The timer runs after collection failures too, so a transient source error
  does not stop the next attempt. The timer also runs when collection is skipped.
  Cancellation or the disable variable stops the handoff; newer runs take over
  from older attempts.
- Only the timer job receives `actions: write`; it dispatches the fixed main
  branch workflow using its short-lived `GITHUB_TOKEN`. No data-repository token
  is exposed to the scheduler.

Set the repository variable `MARKET_INTRADAY_CHAIN_DISABLED=true` to stop
handoffs. Cron and manual collection remain available. Remove the variable or
set it to `false`, then manually run `Market Data Collection (15-min)` on main
to restart immediately. The next cron run also restarts it.

## Limits and cost

GitHub still controls runner availability. The continuous timer removes normal
daily cron dependence, but cannot guarantee execution during a GitHub outage. An API failure ends that handoff with a visible
failed job; the next cron or manual run recovers the chain. Dispatches are not
blindly retried after ambiguous network failures.

Waiting consumes Actions minutes. The timer uses the lower-cost ubuntu-slim
runner. At $0.002/minute, continuous operation is approximately $90/month for
31 days, before included minutes and per-job rounding differences. Collection
jobs consume their usual minutes separately; outside collection hours those
jobs are skipped. This cost buys independence from delayed daily cron startup.
Check GitHub's current runner pricing and the organization's spending limits.

## Validation

Run `node --test scheduler/next-run.test.mjs` for handoff, duplicate, API error,
disable-switch, overnight handoffs, and daylight-saving boundary tests. Run
`python -m pytest tests/test_market_collection_schedule.py -q` for collection
hours and freshness guards. In Actions, verify successive `Market data (handoff)`
runs, successful data publication, and the existing deanfi-data R2 sync workflow.
