"""Fixed New York times survive daylight saving changes without hand-edited crons.

Gated workflows schedule both UTC hours; scripts/ny_hour_gate.py lets exactly
one of them through each day and the publish job skips for the other.
"""

import importlib.util
import re
import shlex
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
GATED = ["analyst-trends.yml", "support-resistence.yml"]

spec = importlib.util.spec_from_file_location("ny_hour_gate", REPO_ROOT / "scripts" / "ny_hour_gate.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

UTC = timezone.utc
EST_DAY = (2026, 1, 13)   # Tuesday, standard time (UTC-5)
EDT_DAY = (2026, 7, 14)   # Tuesday, daylight time (UTC-4)


@pytest.mark.parametrize("day,schedule,expected", [
    (EST_DAY, "0 3 * * 2-6", True),    # 03:00 UTC = 22:00 EST
    (EST_DAY, "0 2 * * 2-6", False),   # 02:00 UTC = 21:00 EST
    (EDT_DAY, "0 2 * * 2-6", True),    # 02:00 UTC = 22:00 EDT
    (EDT_DAY, "0 3 * * 2-6", False),   # 03:00 UTC = 23:00 EDT
])
def test_only_the_cron_on_the_local_hour_proceeds(day, schedule, expected):
    hour = int(schedule.split()[1])
    now = datetime(*day, hour, 4, tzinfo=UTC)
    assert gate.should_run("schedule", schedule, now, local_hour=22) is expected


def test_late_start_is_judged_by_the_scheduled_time_not_the_clock():
    # The EDT run scheduled for 02:00 UTC started 95 minutes late (23:35 EDT): still the right run.
    late = datetime(*EDT_DAY, 3, 35, tzinfo=UTC)
    assert gate.should_run("schedule", "0 2 * * 2-6", late, local_hour=22)
    assert not gate.should_run("schedule", "0 3 * * 2-6", late, local_hour=22)


def test_late_start_past_midnight_utc_maps_back_to_previous_day():
    late = datetime(2026, 7, 15, 0, 20, tzinfo=UTC)  # 23:00 UTC run started after midnight
    assert gate.scheduled_instant("0 23 * * *", late) == datetime(2026, 7, 14, 23, 0, tzinfo=UTC)


@pytest.mark.parametrize("event", ["workflow_dispatch", "push"])
def test_non_scheduled_runs_always_proceed(event):
    assert gate.should_run(event, "", datetime(*EST_DAY, 12, tzinfo=UTC), local_hour=5)


def test_unknown_schedule_falls_back_to_the_clock():
    assert gate.should_run("schedule", "", datetime(*EDT_DAY, 9, 1, tzinfo=UTC), local_hour=5)
    assert not gate.should_run("schedule", "", datetime(*EDT_DAY, 10, 1, tzinfo=UTC), local_hour=5)


def test_main_writes_step_output(tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    assert gate.main(["--local-hour", "5"]) == 0
    assert out.read_text() == "proceed=true\n"


# --- the gated workflows, end to end over a calendar year -----------------

def _dow_matches(field, day):
    cron_dow = (day.weekday() + 1) % 7  # cron: 0 = Sunday
    for part in field.split(","):
        lo, _, hi = part.partition("-")
        if part == "*" or int(lo) <= cron_dow <= int(hi or lo):
            return True
    return False


def _gated(name):
    doc = yaml.safe_load((WORKFLOWS / name).read_text())
    crons = [entry["cron"] for entry in doc[True]["schedule"]]  # PyYAML reads `on` as True
    gate_job = next((n, j) for n, j in doc["jobs"].items()
                    if any("ny_hour_gate.py" in str(s.get("run", "")) for s in j["steps"]))
    run = next(str(s["run"]) for s in gate_job[1]["steps"] if "ny_hour_gate.py" in str(s.get("run", "")))
    words = shlex.split(run)
    hour = int(words[words.index("--local-hour") + 1])
    return doc, crons, gate_job[0], hour


@pytest.mark.parametrize("name", GATED)
def test_exactly_one_run_per_scheduled_day_lands_on_the_local_hour(name):
    _, crons, _, hour = _gated(name)
    day = date(2026, 1, 1)
    while day.year == 2026:
        proceeding = []
        for cron in crons:
            minute, utc_hour, _, _, dow = cron.split()
            if not _dow_matches(dow, day):
                continue
            fired = datetime(day.year, day.month, day.day, int(utc_hour), int(minute), tzinfo=UTC)
            if gate.should_run("schedule", cron, fired + timedelta(minutes=7), hour):
                proceeding.append(fired)
        if any(_dow_matches(c.split()[4], day) for c in crons):
            assert len(proceeding) == 1, f"{name} on {day}: {proceeding}"
            local = proceeding[0].astimezone(gate.NEW_YORK)
            assert local.hour == hour and local.weekday() < 5, f"{name} on {day}: {local}"
        day += timedelta(days=1)


@pytest.mark.parametrize("name", GATED)
def test_publishing_jobs_wait_for_the_gate(name):
    doc, _, gate_name, _ = _gated(name)
    for job_name, job in doc["jobs"].items():
        if job_name == gate_name:
            continue
        needs = job.get("needs")
        needs = [needs] if isinstance(needs, str) else needs or []
        assert gate_name in needs, job_name
        assert re.search(rf"needs\.{gate_name}\.outputs\.proceed\s*==\s*'true'", str(job.get("if", ""))), job_name


def test_no_workflow_keeps_a_commented_out_cron_to_toggle_by_hand():
    offenders = [p.name for p in WORKFLOWS.glob("*.y*ml")
                 if re.search(r"^\s*#\s*-\s*cron:", p.read_text(), re.MULTILINE)]
    assert offenders == []
