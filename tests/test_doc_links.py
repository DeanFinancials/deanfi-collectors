"""Every repo-relative path cited in backticks in AGENTS.md must exist.

AGENTS.md is the agent table of contents; a stale path there sends agents to
files that are gone. Other-repo paths (deanfi-data, the website) are written
without backticks, so anything backticked here is checked against this repo.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS = ["AGENTS.md"]
PATH_SUFFIXES = (".md", ".py", ".yml", ".yaml", ".mjs", ".json", ".txt", ".ini", ".csv")
SKIP_CHARS = (" ", "*", "<", ">", "$")


def _looks_like_path(token: str) -> bool:
    if any(ch in token for ch in SKIP_CHARS):
        return False
    if token.startswith(("@", "/")) or re.match(r"^[a-z][a-z0-9+.-]*://", token):
        return False
    return "/" in token or token.endswith(PATH_SUFFIXES)


def _cited_paths(doc: Path) -> list[str]:
    tokens = re.findall(r"`([^`\n]+)`", doc.read_text(encoding="utf-8"))
    return sorted({t for t in tokens if _looks_like_path(t)})


def test_agents_md_paths_exist():
    missing = []
    for name in DOCS:
        for rel in _cited_paths(REPO_ROOT / name):
            if not (REPO_ROOT / rel.rstrip("/")).exists():
                missing.append(f"{name}: {rel}")
    assert not missing, (
        "Backticked paths in agent docs do not exist in this repo "
        "(fix the path, or write other-repo paths without backticks):\n  "
        + "\n  ".join(missing)
    )


def test_agents_md_cites_paths():
    # Guard against the extractor silently matching nothing.
    assert len(_cited_paths(REPO_ROOT / "AGENTS.md")) >= 10
