"""An old publication retry must never replace a newer options snapshot."""

import json
import os
from pathlib import Path
import subprocess

import pytest
import yaml


@pytest.mark.parametrize(
    "previous, expected",
    [
        (None, True),
        ("invalid", True),
        ("2026-09-09T19:39:00Z", True),
        ("2026-09-09T19:40:00Z", False),
        ("2026-09-09T19:41:00Z", False),
    ],
)
def test_publication_retry_keeps_newer_snapshot(tmp_path, previous, expected):
    workflow = yaml.safe_load(
        (Path(__file__).parents[1] / ".github/workflows/options-whales.yml").read_text()
    )
    steps = workflow["jobs"]["publish-options-whales"]["steps"]
    check = next(step for step in steps if step.get("id") == "snapshot")
    (tmp_path / "optionswhales").mkdir()
    (tmp_path / "data-cache").mkdir()
    (tmp_path / "optionswhales/options_whale_summary.json").write_text(
        json.dumps({"metadata": {"generated_at": "2026-09-09T19:40:00Z"}})
    )
    freshness = {"sections": {"options-whales": {"last_updated": previous}}}
    data_file = tmp_path / "data-cache/data_freshness.json"
    data_file.write_text(json.dumps(freshness))
    output = tmp_path / "output"
    subprocess.run(
        ["bash", "-e", "-c", check["run"]], cwd=tmp_path, check=True,
        env={**os.environ, "GITHUB_OUTPUT": str(output)}, capture_output=True, text=True,
    )
    assert output.read_text() == f"publish={str(expected).lower()}\n"
    assert json.loads(data_file.read_text()) == freshness
    for name in ("Copy output to data repo", "Update data freshness", "Commit and push to data repo"):
        step = next(step for step in steps if step.get("name") == name)
        assert step["if"] == "steps.snapshot.outputs.publish == 'true'"
