"""Brief 245 — Phase 1a Unboks QA simulator: validate the scenario library
loads + has the expected shape, and the runner CLI works end-to-end.

These tests treat scenarios.json as a DATA file (the unit under test),
not as source code. Asserting on the data's shape IS the test surface."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCENARIOS_PATH = REPO_ROOT / "tools" / "unboks-qa" / "scenarios.json"
RUNNER_PATH = REPO_ROOT / "tools" / "unboks-qa" / "run_qa.py"
REPORTS_ROOT = REPO_ROOT / "tools" / "unboks-qa" / "reports"

QA_PREFIX = "[QA TEST]"
IDENTITY_RULES = ("butlerbensonagent@gmail.com", "—")


def _load_scenarios():
    with SCENARIOS_PATH.open() as f:
        return json.load(f)


def test_scenarios_json_loads_and_has_10_entries():
    """Phase 1a ships exactly 10 seed scenarios; Brief 246+ expands to 50
    and bumps this assertion."""
    data = _load_scenarios()
    assert isinstance(data, list)
    assert len(data) == 10, f"expected 10 seed scenarios, got {len(data)}"


def test_every_scenario_has_qa_test_prefix_in_messages():
    """Every customer message MUST start with [QA TEST] so any accidental
    production leak is unambiguously identifiable in logs."""
    data = _load_scenarios()
    for scenario in data:
        test_id = scenario.get("testId", "<unknown>")
        for i, msg in enumerate(scenario.get("messages", [])):
            assert msg.startswith(QA_PREFIX), (
                f"{test_id} messages[{i}] missing '{QA_PREFIX}' prefix: "
                f"{msg[:60]!r}")


def test_every_scenario_has_identity_rules_in_must_not_contain():
    """Every scenario's expected.mustNotContain MUST include the Brief 244
    identity rules — the internal sender mailbox AND the em-dash."""
    data = _load_scenarios()
    for scenario in data:
        test_id = scenario.get("testId", "<unknown>")
        must_not = scenario.get("expected", {}).get("mustNotContain", [])
        for rule in IDENTITY_RULES:
            assert rule in must_not, (
                f"{test_id} expected.mustNotContain missing identity rule "
                f"{rule!r}; has {must_not}")


def _cleanup_reports_dir():
    if REPORTS_ROOT.exists():
        shutil.rmtree(REPORTS_ROOT)


def test_runner_dry_run_produces_reports():
    """Invoke the CLI as a subprocess (real argparse, real file I/O) and
    assert summary.md + results.json exist + parse correctly."""
    _cleanup_reports_dir()
    try:
        result = subprocess.run(
            [sys.executable, str(RUNNER_PATH)],
            capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=30)
        assert result.returncode == 0, (
            f"runner exited {result.returncode}; "
            f"stdout={result.stdout!r} stderr={result.stderr!r}")
        report_dirs = sorted(REPORTS_ROOT.iterdir())
        assert len(report_dirs) == 1, f"expected 1 report dir, got {report_dirs}"
        report_dir = report_dirs[0]
        summary = report_dir / "summary.md"
        results_json = report_dir / "results.json"
        failed_txt = report_dir / "failed.txt"
        assert summary.exists() and summary.stat().st_size > 0
        assert results_json.exists()
        assert failed_txt.exists()
        # results.json parses + matches scenario count
        results = json.loads(results_json.read_text())
        assert isinstance(results, list)
        assert len(results) == 10
        # summary.md mentions Brief 245 framing
        summary_text = summary.read_text()
        assert "Unboks QA Agent Report" in summary_text
        assert "Phase 1a" in summary_text
    finally:
        _cleanup_reports_dir()


def test_runner_validate_only_passes_for_well_formed_scenarios():
    """--validate-only flag exits 0 when all scenarios pass structural
    validation; does NOT create a reports directory."""
    _cleanup_reports_dir()
    try:
        result = subprocess.run(
            [sys.executable, str(RUNNER_PATH), "--validate-only"],
            capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=30)
        assert result.returncode == 0, (
            f"validate-only exited {result.returncode}; "
            f"stdout={result.stdout!r} stderr={result.stderr!r}")
        # No report dir created in validate-only mode
        if REPORTS_ROOT.exists():
            assert not any(REPORTS_ROOT.iterdir()), (
                "validate-only must not create report dirs")
    finally:
        _cleanup_reports_dir()
