"""A failed ETF fund flows generation publishes nothing and fails the job.

The collector upserts into month files seeded from deanfi-data, so a crash can
leave a half-written file in etffundflows/output/. Publishing after a failure
would push that file (and a fresh data_freshness timestamp) over the last good
copy.
"""

import json
import re
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "etf-fund-flows.yml"
GENERATE = "Generate ETF fund flows"
# Status functions that let a step run after an earlier step failed.
RUNS_AFTER_FAILURE = re.compile(r"\b(always|failure)\s*\(\)|!\s*cancelled\s*\(\)")


def _steps():
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]["fetch-and-publish"]["steps"]


def _writes_to_data_repo(step):
    """Copies into the data-cache checkout, rewrites its freshness file, or pushes."""
    script = str(step.get("run", ""))
    return bool(re.search(r"\bcp\s+\S+\s+data-cache/", script)) or "git push" in script or (
        "data_freshness.json" in script and "write_text" in script)


def _steps_that_run_after(steps, failed_index):
    """GitHub step semantics: once a step fails (without continue-on-error),
    later steps run only if their `if:` uses always(), failure() or !cancelled()."""
    if steps[failed_index].get("continue-on-error"):
        return steps[failed_index + 1:]
    return [s for s in steps[failed_index + 1:] if RUNS_AFTER_FAILURE.search(str(s.get("if", "")))]


def test_failed_generation_skips_every_step_that_writes_deanfi_data():
    steps = _steps()
    names = [s.get("name") for s in steps]
    after = _steps_that_run_after(steps, names.index(GENERATE))
    leaking = [s.get("name") for s in after if _writes_to_data_repo(s)]
    assert leaking == [], "a failed generation must not publish partial output"


def test_publish_steps_exist_after_generation():
    # Guards the test above against passing because the publish steps moved or vanished.
    steps = _steps()
    names = [s.get("name") for s in steps]
    publish = [i for i, s in enumerate(steps) if _writes_to_data_repo(s)]
    assert publish and min(publish) > names.index(GENERATE)


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _freshness_after_copy(tmp_path, output_text):
    """Run the workflow's copy + freshness steps against a throwaway data repo."""
    steps = {s.get("name"): s for s in _steps()}
    data = tmp_path / "data-cache"
    (data / "etf-fund-flows").mkdir(parents=True)
    month = data / "etf-fund-flows" / "etf_fund_flows_2026-11.json"
    month.write_text('{"data": {"SPY": {"daily": []}}}')
    (data / "data_freshness.json").write_text(
        json.dumps({"sections": {"etf-fund-flows": {"last_updated": "2026-11-17T21:50:00Z"}}}))
    _git(data, "init", "-q")
    _git(data, "-c", "user.name=t", "-c", "user.email=t@t", "add", ".")
    _git(data, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed")

    out = tmp_path / "etffundflows" / "output"
    out.mkdir(parents=True)
    (out / month.name).write_text(output_text)

    for name in ("Copy to data repo", "Update data freshness"):
        subprocess.run(["bash", "-e", "-c", steps[name]["run"]], cwd=tmp_path, check=True,
                       capture_output=True)
    return json.loads((data / "data_freshness.json").read_text())["sections"]["etf-fund-flows"]


def test_unchanged_seeded_files_do_not_refresh_freshness(tmp_path):
    """The output dir always holds the seeded files, so their presence is not new data."""
    section = _freshness_after_copy(tmp_path, '{"data": {"SPY": {"daily": []}}}')
    assert section["last_updated"] == "2026-11-17T21:50:00Z"


def test_new_session_refreshes_freshness(tmp_path):
    section = _freshness_after_copy(tmp_path, '{"data": {"SPY": {"daily": [{"date": "2026-11-18"}]}}}')
    assert section["last_updated"] != "2026-11-17T21:50:00Z"
