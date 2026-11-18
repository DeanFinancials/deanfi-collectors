"""Every remote GitHub Action is pinned to a full commit SHA (supply-chain guard)."""

import re
from pathlib import Path

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
    assert unpinned == [], "pin these actions to a 40-char commit SHA"

