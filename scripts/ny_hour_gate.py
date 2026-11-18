#!/usr/bin/env python3
"""Decide whether a scheduled run is the one meant for a given New York hour.

GitHub cron is UTC, so a job meant for a fixed Eastern time is scheduled at
both UTC hours (EST and EDT) and this gate lets through only the run whose
scheduled time falls on the intended local hour. It judges the cron that fired
(EVENT_SCHEDULE), not the clock, because GitHub often starts scheduled
runs late; the wall clock is the fallback when the schedule is unknown.
Every other event (workflow_dispatch, push) proceeds.

Usage in a workflow:
    python3 scripts/ny_hour_gate.py --local-hour 22
with EVENT_SCHEDULE set to ${{ github.event.schedule }} (GitHub sets
GITHUB_EVENT_NAME itself); writes
proceed=true|false to GITHUB_OUTPUT.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")


def scheduled_instant(schedule: str, now_utc: datetime) -> Optional[datetime]:
    """Most recent UTC time at or before now matching the cron's fixed minute and hour."""
    fields = (schedule or "").split()
    if len(fields) != 5 or not (fields[0].isdigit() and fields[1].isdigit()):
        return None
    minute, hour = int(fields[0]), int(fields[1])
    if minute > 59 or hour > 23:
        return None
    instant = now_utc.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if instant > now_utc:
        instant -= timedelta(days=1)
    return instant


def should_run(event_name: str, schedule: str, now_utc: datetime, local_hour: int,
               tz: ZoneInfo = NEW_YORK) -> bool:
    if event_name != "schedule":
        return True
    when = scheduled_instant(schedule, now_utc) or now_utc
    return when.astimezone(tz).hour == local_hour


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--local-hour", type=int, required=True, choices=range(24),
                        metavar="0-23", help="intended America/New_York hour")
    args = parser.parse_args(argv)

    event = os.environ.get("GITHUB_EVENT_NAME", "")
    schedule = os.environ.get("EVENT_SCHEDULE", "")
    now = datetime.now(timezone.utc)
    proceed = should_run(event, schedule, now, args.local_hour)

    if proceed:
        print(f"Proceeding ({event or 'unknown event'}, schedule {schedule!r})")
    else:
        print(f"Skipping: schedule {schedule!r} is not {args.local_hour:02d}:00 America/New_York today; "
              "the other UTC cron covers it")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as fh:
            fh.write(f"proceed={str(proceed).lower()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
