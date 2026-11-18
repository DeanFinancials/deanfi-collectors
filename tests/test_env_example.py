"""
.env.example is the local-run template: every credential a collector reads from
the environment must be listed there, or a local run fails on a key the
contributor never knew to set.
"""
import ast
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent

# scripts/ holds workflow glue that only runs inside GitHub Actions.
CI_ONLY_DIRS = {"scripts"}
# GITHUB_* is set by the runner. These two are a workflow input and a path the
# workflow sets (optional locally), not credentials.
NOT_LOCAL_CONFIG = {"MARKET_PULSE_WEEKLY_OVERRIDE", "IV_PRIOR_SNAPSHOT_DIR"}
# Alpaca SDK-style aliases accepted as fallbacks for ALPACA_API_KEY/SECRET.
ALIASES = {"APCA-API-KEY-ID", "APCA-API-SECRET-KEY"}


def _collector_sources():
    for path in REPO.rglob("*.py"):
        rel = path.relative_to(REPO)
        if rel.parts[0] in {"tests", ".git"} | CI_ONLY_DIRS or "tests" in rel.parts or "site-packages" in rel.parts:
            continue
        yield path


def _env_reads_in_code():
    names = set()
    for path in _collector_sources():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            target = None
            if isinstance(node, ast.Call) and node.args:
                func = ast.unparse(node.func)
                if func in {"os.getenv", "os.environ.get", "getenv", "environ.get"}:
                    target = node.args[0]
            elif isinstance(node, ast.Subscript) and ast.unparse(node.value) in {"os.environ", "environ"}:
                target = node.slice
            if isinstance(target, ast.Constant) and isinstance(target.value, str):
                names.add(target.value)
            elif isinstance(target, ast.Name):
                # Module constant holding the env var name (e.g. PRIOR_SNAPSHOT_DIR_ENV).
                for assign in ast.walk(tree):
                    if (isinstance(assign, ast.Assign) and isinstance(assign.value, ast.Constant)
                            and any(isinstance(t, ast.Name) and t.id == target.id for t in assign.targets)):
                        names.add(assign.value.value)
    return names


def _env_names_in_configs():
    """Env var names that config.yml files point collectors at."""
    names = set()

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(key, str) and key.endswith("_env") and isinstance(value, str):
                    names.add(value)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, str):
            names.update(re.findall(r"^\$\{([A-Z0-9_]+)(?::[^}]*)?\}$", node))

    for path in REPO.glob("*/config.yml"):
        walk(yaml.safe_load(path.read_text()))
    return names


def _env_example_names():
    names = set()
    for line in (REPO / ".env.example").read_text().splitlines():
        match = re.match(r"^([A-Z][A-Z0-9_]*)=", line)
        if match:
            names.add(match.group(1))
    return names


def test_every_env_var_collectors_read_is_in_env_example():
    read = {
        name for name in _env_reads_in_code() | _env_names_in_configs()
        if not name.startswith("GITHUB_")
    } - NOT_LOCAL_CONFIG - ALIASES
    assert read, "scanner found no env reads; the scan itself is broken"
    missing = sorted(read - _env_example_names())
    assert not missing, f".env.example is missing: {missing}"
