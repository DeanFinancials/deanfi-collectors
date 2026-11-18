"""Regression: spgrowth must not publish an empty universe over good data.

When every company in a universe is filtered out (no CIK, no SEC data), the
collector used to write ``"companies": {}`` to sp100growth.json /
sp500growth.json, and the workflow copied it over the last good file. Now
``main()`` exits non-zero and writes neither file when either universe has
zero publishable companies.

Every test mocks the universe, CIK map, SEC fetch and extraction; no network.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("secedgar")  # heavy transitive dep; present in CI

from spgrowth import fetch_sp_growth as sg  # noqa: E402
from tests.test_spgrowth_publish import _good_company  # noqa: E402

SP100 = ["AAA", "BBB"]
SP500 = ["AAA", "BBB", "CCC", "DDD"]


def _run_main(monkeypatch, tmp_path: Path, *, ciks: dict, extra_args=()) -> None:
    monkeypatch.setattr(sg, "fetch_sp100_tickers", lambda: list(SP100))
    monkeypatch.setattr(sg, "fetch_spx_tickers", lambda sec_compatible=True: list(SP500))
    monkeypatch.setattr(sg, "load_ticker_to_cik", lambda user_agent: dict(ciks))
    monkeypatch.setattr(sg, "fetch_company_facts", lambda ticker, user_agent: {"facts": {}})
    monkeypatch.setattr(
        sg, "extract_company_data",
        lambda ticker, cik, facts, config: _good_company(ticker),
    )
    monkeypatch.setattr(sys, "argv", ["fetch_sp_growth.py", "--output", str(tmp_path), *extra_args])
    sg.main()


def test_zero_publishable_companies_exits_nonzero_and_writes_nothing(monkeypatch, tmp_path):
    # Last good files already in the output directory must be left untouched.
    good = {"companies": {"AAA": {}}}
    for name in ("sp100growth.json", "sp500growth.json"):
        (tmp_path / name).write_text(json.dumps(good))

    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, tmp_path, ciks={})  # no CIKs: every record unpublishable

    assert exc.value.code not in (0, None)
    for name in ("sp100growth.json", "sp500growth.json"):
        assert json.loads((tmp_path / name).read_text()) == good, f"{name} was overwritten"


def test_zero_publishable_writes_no_new_file(monkeypatch, tmp_path):
    out = tmp_path / "out"
    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, out, ciks={})
    assert exc.value.code not in (0, None)
    assert not (out / "sp100growth.json").exists()
    assert not (out / "sp500growth.json").exists()


def test_empty_sp100_blocks_both_files(monkeypatch, tmp_path):
    # S&P 500 has publishable companies but none of them is in the S&P 100.
    with pytest.raises(SystemExit) as exc:
        _run_main(monkeypatch, tmp_path, ciks={"CCC": "0000000003", "DDD": "0000000004"})
    assert exc.value.code not in (0, None)
    assert not (tmp_path / "sp100growth.json").exists()
    assert not (tmp_path / "sp500growth.json").exists()


def test_normal_run_writes_both_files(monkeypatch, tmp_path):
    ciks = {t: f"000000000{i}" for i, t in enumerate(SP500, 1)}
    _run_main(monkeypatch, tmp_path, ciks=ciks)

    sp100 = json.loads((tmp_path / "sp100growth.json").read_text())
    sp500 = json.loads((tmp_path / "sp500growth.json").read_text())
    assert set(sp100["companies"]) == set(SP100)
    assert set(sp500["companies"]) == set(SP500)
    assert sp100["metadata"]["ticker_count"] == 2
    assert sp500["metadata"]["ticker_count"] == 4


def test_partial_run_publishes_only_resolved_companies(monkeypatch, tmp_path):
    _run_main(monkeypatch, tmp_path, ciks={"AAA": "0000000001", "CCC": "0000000003"})

    assert set(json.loads((tmp_path / "sp100growth.json").read_text())["companies"]) == {"AAA"}
    assert set(json.loads((tmp_path / "sp500growth.json").read_text())["companies"]) == {"AAA", "CCC"}


def test_sp500_only_ignores_sp100(monkeypatch, tmp_path):
    _run_main(monkeypatch, tmp_path, ciks={"CCC": "0000000003"}, extra_args=["--sp500-only"])

    assert not (tmp_path / "sp100growth.json").exists()
    assert set(json.loads((tmp_path / "sp500growth.json").read_text())["companies"]) == {"CCC"}
