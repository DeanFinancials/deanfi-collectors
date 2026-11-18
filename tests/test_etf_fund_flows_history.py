"""ETF fund flows need the prior session, so each run must start from the published month files."""

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


def test_workflow_seeds_output_dir_from_data_repo_before_generating():
    names = [step.get("name", "") for step in _steps()]
    seed = names.index("Seed existing monthly outputs from data repo")
    generate = names.index("Generate ETF fund flows")
    checkout_data = names.index("Checkout data repo")
    assert checkout_data < seed < generate

    seed_run = _steps()[seed]["run"]
    assert "data-cache/etf-fund-flows/etf_fund_flows_" in seed_run
    assert "etffundflows/output" in seed_run


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

    artifact = steps["Upload test-mode outputs as artifact"]
    assert artifact.get("if") == "env.PUBLISH != 'true'"
    assert artifact["uses"].startswith("actions/upload-artifact@")
    assert "etffundflows/output" in artifact["with"]["path"]
