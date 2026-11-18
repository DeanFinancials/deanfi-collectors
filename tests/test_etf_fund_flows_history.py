"""ETF fund flows need the prior session, so each run must start from the published month files."""

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "etffundflows"))

import fetch_etf_fund_flows as fff  # noqa: E402

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "etf-fund-flows.yml"


def _steps():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    return workflow["jobs"]["fetch-and-publish"]["steps"]


def test_workflow_seeds_published_month_files_before_generating(tmp_path):
    """Without the seed, a run writes a one-day month file over the published history."""
    steps = _steps()
    names = [step.get("name", "") for step in steps]
    seed = names.index("Seed existing monthly outputs from data repo")
    assert names.index("Checkout data repo") < seed < names.index("Generate ETF fund flows")

    published = tmp_path / "data-cache/etf-fund-flows/etf_fund_flows_2026-11.json"
    published.parent.mkdir(parents=True)
    published.write_text('{"data": {"SPY": {}}}')
    subprocess.run(["bash", "-e", "-c", steps[seed]["run"]], cwd=tmp_path, check=True,
                   capture_output=True)

    seeded = tmp_path / "etffundflows/output/etf_fund_flows_2026-11.json"
    assert seeded.read_text() == published.read_text()


def test_seeded_month_doc_supplies_prior_point_for_flow():
    seeded = {"data": {"SPY": {"daily": [{"date": "2026-11-17", "aum": 100.0, "nav": 10.0}]}}}

    prior = fff.get_prev_point(seeded, None, "SPY", "2026-11-18")

    assert prior is not None and prior["date"] == "2026-11-17"
    # 10% NAV gain explains 100 -> 110; anything above is creation.
    assert fff.compute_flow(115.0, prior["aum"], 1.1) == pytest.approx(5.0)


def test_empty_output_dir_has_no_prior_point():
    assert fff.get_prev_point({"data": {}}, None, "SPY", "2026-11-18") is None


def test_manual_test_mode_never_publishes_to_data_repo():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    publish_expr = workflow["env"]["PUBLISH"]
    assert "github.event_name == 'schedule'" in publish_expr
    assert "inputs.mode == 'full'" in publish_expr

    steps = {step.get("name", ""): step for step in _steps()}
    for name in ("Copy to data repo", "Update data freshness", "Commit and push"):
        assert steps[name].get("if") == "env.PUBLISH == 'true'", name
