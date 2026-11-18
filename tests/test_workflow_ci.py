"""ci.yml runs the whole test suite on every push and pull request, read-only."""

import shlex
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# The suites AGENTS.md lists; CI must run each one.
SUITES = [
    ["python3", "-m", "pytest", "-q"],
    ["python3", "-m", "pytest", "-q", "dailynews/tests"],
    ["node", "--test", "scheduler/next-run.test.mjs"],
]


def _ci():
    return yaml.safe_load(CI.read_text())


def _commands(doc):
    for job in doc["jobs"].values():
        for step in job.get("steps", []):
            for line in str(step.get("run", "")).splitlines():
                words = shlex.split(line, comments=True)
                if words:
                    yield words


def test_ci_runs_on_push_and_pull_request():
    triggers = _ci()[True]  # PyYAML reads `on` as True
    assert "push" in triggers and "pull_request" in triggers


def test_ci_runs_every_suite():
    commands = list(_commands(_ci()))
    for suite in SUITES:
        assert suite in commands, f"ci.yml does not run {' '.join(suite)}"


def test_ci_installs_requirements_before_testing():
    commands = list(_commands(_ci()))
    install = commands.index(next(c for c in commands if "requirements.txt" in c and "install" in c))
    assert install < commands.index(SUITES[0])


def test_ci_is_read_only_bounded_and_off_the_data_repo_lock():
    doc = _ci()
    assert doc["permissions"] == {"contents": "read"}
    for name, job in doc["jobs"].items():
        assert job.get("timeout-minutes"), name
        group = str((job.get("concurrency") or doc.get("concurrency") or {}).get("group", ""))
        assert group != "deanfi-data-repo", "CI never pushes to deanfi-data, so it must not queue behind publishers"
        scripts = " ".join(str(s.get("run", "")) for s in job.get("steps", []))
        assert "git push" not in scripts and "DATA_REPO_TOKEN" not in CI.read_text()
