"""Every remote GitHub Action is pinned to a commit SHA; Dependabot bumps the pins monthly."""

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
USES = re.compile(r"^\s*-?\s*uses:\s*['\"]?([^'\"\s#]+)", re.MULTILINE)


def test_every_remote_action_is_sha_pinned():
    unpinned = []
    for workflow in sorted((REPO_ROOT / ".github" / "workflows").glob("*.y*ml")):
        for ref in USES.findall(workflow.read_text()):
            if ref.startswith(("./", "docker://")):
                continue
            if not re.search(r"@[0-9a-f]{40}$", ref):
                unpinned.append(f"{workflow.name}: {ref}")
    assert unpinned == []


def test_dependabot_groups_github_actions_updates():
    config = yaml.safe_load((REPO_ROOT / ".github" / "dependabot.yml").read_text())
    updates = [u for u in config["updates"] if u["package-ecosystem"] == "github-actions"]
    assert len(updates) == 1
    assert updates[0]["groups"]
