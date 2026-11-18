"""Every API key a collector reads reaches it from the workflow that runs it.

A key the collector reads but the workflow never sets is silently empty, so the
source it unlocks (for example the Alpha Vantage and FMP fallbacks in spgrowth)
never runs in production. Keys are found from the collector itself: literal
os.environ / os.getenv reads in the script and `*_env` entries in the config.yml
beside it.
"""

import ast
import importlib
import os
import shlex
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((REPO_ROOT / ".github" / "workflows").glob("*.y*ml"))
SECRET_SUFFIXES = ("_KEY", "_SECRET", "_TOKEN")


def _env_reads(script):
    names = set()
    for node in ast.walk(ast.parse(script.read_text())):
        if (isinstance(node, ast.Call) and ast.unparse(node.func) in ("os.environ.get", "os.getenv")
                and node.args and isinstance(node.args[0], ast.Constant)):
            names.add(node.args[0].value)
        elif (isinstance(node, ast.Subscript) and ast.unparse(node.value) == "os.environ"
              and isinstance(node.slice, ast.Constant)):
            names.add(node.slice.value)
    return names


def _config_env_names(config):
    if not config.exists():
        return set()
    names, stack = set(), [yaml.safe_load(config.read_text())]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                if str(key).endswith("_env") and isinstance(value, str):
                    names.add(value)
                else:
                    stack.append(value)
        elif isinstance(node, list):
            stack.extend(node)
    return names


def _collector_runs():
    """(workflow, script path, env visible to the step) for each `python x.py` a step runs."""
    for wf in WORKFLOWS:
        doc = yaml.safe_load(wf.read_text())
        for job in doc["jobs"].values():
            for step in job.get("steps", []):
                env = {**doc.get("env", {}), **job.get("env", {}), **step.get("env", {})}
                cwd = REPO_ROOT
                for line in str(step.get("run", "")).splitlines():
                    try:
                        words = shlex.split(line, comments=True)
                    except ValueError:
                        continue
                    if words[:1] == ["cd"] and len(words) > 1:
                        cwd = (cwd / words[1]).resolve()
                    for prev, word in zip(words, words[1:]):
                        if prev in ("python", "python3") and word.endswith(".py") and (cwd / word).exists():
                            yield wf.name, cwd / word, env


RUNS = list(_collector_runs())


def test_sp_growth_collector_is_discovered():
    assert any(w == "sp-growth.yml" and s.name == "fetch_sp_growth.py" for w, s, _ in RUNS)


@pytest.mark.parametrize("workflow,script,env", RUNS,
                         ids=[f"{w}:{s.relative_to(REPO_ROOT)}" for w, s, _ in RUNS])
def test_every_key_the_collector_reads_comes_from_a_secret(workflow, script, env):
    wanted = {n for n in _env_reads(script) | _config_env_names(script.parent / "config.yml")
              if n.endswith(SECRET_SUFFIXES)}
    missing = sorted(n for n in wanted if "secrets." not in str(env.get(n, "")))
    assert missing == [], f"{workflow} runs {script.name} without {missing}"


def test_sp_growth_skips_fallbacks_whose_secret_is_unset(monkeypatch):
    """An unset GitHub secret arrives as an empty string; that source must be skipped, not called."""
    sys.path.insert(0, str(REPO_ROOT / "spgrowth"))
    try:
        sp = importlib.import_module("fetch_sp_growth")
    finally:
        sys.path.remove(str(REPO_ROOT / "spgrowth"))
    for name in ("ALPHA_VANTAGE_API_KEY", "FMP_API_KEY", "FINNHUB_API_KEY"):
        monkeypatch.setenv(name, "")
    config = sp.Config.from_yaml(str(REPO_ROOT / "spgrowth" / "config.yml"))
    config.yfinance_enabled = False

    def no_network(*args, **kwargs):
        raise AssertionError("a fallback with no key made a request")

    monkeypatch.setattr(sp.requests, "get", no_network)
    assert sp.gather_all_fallback_data("AAPL", config, 6) == {}
