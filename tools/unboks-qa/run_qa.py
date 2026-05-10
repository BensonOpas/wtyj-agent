#!/usr/bin/env python3
"""Phase 1a Unboks QA/customer simulator runner.

Loads tools/unboks-qa/scenarios.json, validates each scenario's structure,
and writes console + JSON + markdown reports. **Dry-run only** — does NOT
contact real customers, does NOT mutate production data, does NOT call
Marina or any production endpoint. Phase 2 (live execution) is a separate
brief.

Usage:
    run_qa.py                       # dry-run all scenarios, write reports
    run_qa.py --filter <category>   # dry-run scenarios in one category
    run_qa.py --filter <testId>     # dry-run a single scenario by id
    run_qa.py --validate-only       # only validate JSON shape; no report
    run_qa.py --live                # NOT IMPLEMENTED — exits with code 2
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SCENARIOS_PATH = SCRIPT_DIR / "scenarios.json"
REPORTS_ROOT = SCRIPT_DIR / "reports"

VALID_CATEGORIES = {
    "booking", "faq", "escalation",
    "reply_thread", "dashboard_action", "edge_case",
}
VALID_CHANNELS = {"email", "whatsapp", "instagram", "facebook", "messenger"}
QA_PREFIX = "[QA TEST]"
IDENTITY_RULES = ("butlerbensonagent@gmail.com", "—")

CRITICAL_CATEGORIES = {"escalation", "dashboard_action"}
HIGH_CATEGORIES = {"booking", "reply_thread"}
MEDIUM_CATEGORIES = {"faq"}
LOW_CATEGORIES = {"edge_case"}


def load_scenarios():
    """Read scenarios.json, return parsed list. Raises SystemExit on error."""
    if not SCENARIOS_PATH.exists():
        print(f"ERROR: scenarios file missing: {SCENARIOS_PATH}",
              file=sys.stderr)
        sys.exit(1)
    try:
        with SCENARIOS_PATH.open() as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        print(f"ERROR: scenarios.json is not valid JSON: {exc}",
              file=sys.stderr)
        sys.exit(1)
    if not isinstance(data, list):
        print(f"ERROR: scenarios.json must be a JSON array, got {type(data).__name__}",
              file=sys.stderr)
        sys.exit(1)
    return data


def validate_scenario(scenario):
    """Return (status, failure_reason) tuple per Brief 245 Step 1 constraints.

    status is 'PASS_DRYRUN' (with "" reason) or 'FAIL_DRYRUN' (with reason).
    """
    if not isinstance(scenario, dict):
        return "FAIL_DRYRUN", "scenario is not a JSON object"

    test_id = scenario.get("testId")
    if not isinstance(test_id, str) or not test_id:
        return "FAIL_DRYRUN", "missing or empty testId"
    if test_id != test_id.upper():
        return "FAIL_DRYRUN", f"testId '{test_id}' must be ALL CAPS"

    category = scenario.get("category")
    if category not in VALID_CATEGORIES:
        return "FAIL_DRYRUN", f"invalid category '{category}' (must be one of {sorted(VALID_CATEGORIES)})"

    channel = scenario.get("channel")
    if channel not in VALID_CHANNELS:
        return "FAIL_DRYRUN", f"invalid channel '{channel}' (must be one of {sorted(VALID_CHANNELS)})"

    if channel == "email" and not scenario.get("senderEmail"):
        return "FAIL_DRYRUN", "channel=email requires senderEmail"

    messages = scenario.get("messages")
    if not isinstance(messages, list) or not messages:
        return "FAIL_DRYRUN", "messages must be a non-empty array"
    for i, msg in enumerate(messages):
        if not isinstance(msg, str):
            return "FAIL_DRYRUN", f"messages[{i}] is not a string"
        if not msg.startswith(QA_PREFIX):
            return "FAIL_DRYRUN", f"messages[{i}] missing required '{QA_PREFIX}' prefix"

    expected = scenario.get("expected")
    if not isinstance(expected, dict) or not expected:
        return "FAIL_DRYRUN", "expected must be a non-empty object"

    must_not = expected.get("mustNotContain") or []
    if not isinstance(must_not, list):
        return "FAIL_DRYRUN", "expected.mustNotContain must be an array"
    for rule in IDENTITY_RULES:
        if rule not in must_not:
            return ("FAIL_DRYRUN",
                    f"expected.mustNotContain missing identity rule {rule!r}")

    return "PASS_DRYRUN", ""


def run_dry_run(scenarios, filter_value=None):
    """Iterate scenarios, validate each, return list of result dicts."""
    if filter_value:
        filtered = [s for s in scenarios if s.get("category") == filter_value]
        if not filtered:
            filtered = [s for s in scenarios if s.get("testId") == filter_value]
        scenarios = filtered

    results = []
    for scenario in scenarios:
        status, reason = validate_scenario(scenario)
        results.append({
            "testId": scenario.get("testId", "<missing-testId>"),
            "category": scenario.get("category", "<missing-category>"),
            "channel": scenario.get("channel", "<missing-channel>"),
            "status": status,
            "failureReason": reason,
            "phase2Notes": scenario.get("phase2Notes", ""),
        })
    return results


def make_report_dir():
    """Create reports/<UTC ISO> directory and return its Path."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    report_dir = REPORTS_ROOT / timestamp
    report_dir.mkdir(parents=True, exist_ok=True)
    return report_dir


def write_results_json(report_dir, results):
    path = report_dir / "results.json"
    with path.open("w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    return path


def write_failed_txt(report_dir, results):
    path = report_dir / "failed.txt"
    failed = [r for r in results if r["status"] == "FAIL_DRYRUN"]
    with path.open("w") as f:
        for r in failed:
            f.write(f"{r['testId']}\t{r['failureReason']}\n")
    return path


def _severity_count(results, categories):
    return sum(1 for r in results
               if r["status"] == "FAIL_DRYRUN" and r["category"] in categories)


def write_summary_md(report_dir, results):
    """Render the markdown summary per the issue #9 template."""
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS_DRYRUN")
    failed = sum(1 for r in results if r["status"] == "FAIL_DRYRUN")
    pending_phase_2 = passed  # PASS_DRYRUN scenarios all need live exec

    timestamp = datetime.now(timezone.utc).isoformat()

    lines = [
        "# Unboks QA Agent Report",
        "",
        f"Date: {timestamp}",
        "Environment: dry-run (Phase 1a — no live execution)",
        "Tenant: unboks",
        "QA customer email: calvinadamus@gmail.com",
        f"Total tests: {total}",
        f"Passed (dry-run structural): {passed}",
        f"Failed (dry-run structural): {failed}",
        f"Pending Phase 2 (live exec needed): {pending_phase_2}",
        "",
        f"Critical failures: {_severity_count(results, CRITICAL_CATEGORIES)}",
        f"High failures: {_severity_count(results, HIGH_CATEGORIES)}",
        f"Medium failures: {_severity_count(results, MEDIUM_CATEGORIES)}",
        f"Low failures: {_severity_count(results, LOW_CATEGORIES)}",
        "",
        "## Critical Failures",
    ]

    crit_failures = [r for r in results
                     if r["status"] == "FAIL_DRYRUN"
                     and r["category"] in CRITICAL_CATEGORIES]
    if crit_failures:
        for r in crit_failures:
            lines.append(
                f"- {r['testId']} ({r['category']}): {r['failureReason']}")
    else:
        lines.append("(none)")

    lines.extend(["", "## Pending Phase 2 (live execution required)"])
    pending = [r for r in results
               if r["status"] == "PASS_DRYRUN" and r["phase2Notes"]]
    if pending:
        for r in pending:
            lines.append(f"- {r['testId']}: {r['phase2Notes']}")
    else:
        lines.append("(no phase2Notes recorded)")

    lines.extend(["", "## Passed Areas (dry-run structural)"])
    by_cat = {}
    for r in results:
        if r["status"] == "PASS_DRYRUN":
            by_cat.setdefault(r["category"], 0)
            by_cat[r["category"]] += 1
    for cat in sorted(by_cat):
        lines.append(f"- {cat}: {by_cat[cat]} scenarios")
    if not by_cat:
        lines.append("(none)")

    lines.extend([
        "",
        "## Phase 2 missing infrastructure",
        "- Live message-injection endpoint (does not exist as of Brief 245).",
        "- Mock harness for marina_agent.process_message that records expected vs actual reply.",
        "- Dashboard action verifier (currently no programmatic way to assert 'archive button worked').",
        "",
    ])

    path = report_dir / "summary.md"
    path.write_text("\n".join(lines))
    return path


def cmd_default(args):
    scenarios = load_scenarios()
    results = run_dry_run(scenarios, filter_value=args.filter)

    report_dir = make_report_dir()
    write_results_json(report_dir, results)
    failed_path = write_failed_txt(report_dir, results)
    summary_path = write_summary_md(report_dir, results)

    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS_DRYRUN")
    failed = sum(1 for r in results if r["status"] == "FAIL_DRYRUN")

    print(f"Unboks QA dry-run complete.")
    print(f"  Total: {total}")
    print(f"  Passed (structural): {passed}")
    print(f"  Failed (structural): {failed}")
    print(f"  Pending Phase 2 (live exec): {passed}")
    print(f"  Report dir: {report_dir}")
    print(f"  Summary: {summary_path}")

    return 0 if failed == 0 else 1


def cmd_validate_only(args):
    scenarios = load_scenarios()
    results = run_dry_run(scenarios, filter_value=args.filter)
    failed = [r for r in results if r["status"] == "FAIL_DRYRUN"]
    if failed:
        for r in failed:
            print(f"FAIL\t{r['testId']}\t{r['failureReason']}", file=sys.stderr)
        return 1
    print(f"OK: {len(results)} scenarios validated.")
    return 0


def cmd_live(args):
    print(
        "Phase 2 not implemented yet. Live execution requires a safe\n"
        "message-injection endpoint that does not exist as of Brief 245.\n"
        "Re-run without --live for dry-run mode.",
        file=sys.stderr,
    )
    return 2


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Phase 1a Unboks QA/customer simulator (dry-run only)")
    parser.add_argument(
        "--filter", default=None,
        help="Filter scenarios by category (booking/faq/...) or testId.")
    parser.add_argument(
        "--validate-only", action="store_true",
        help="Validate scenario JSON shape only; do not write reports.")
    parser.add_argument(
        "--live", action="store_true",
        help="NOT IMPLEMENTED — exits with code 2 in Phase 1a.")
    args = parser.parse_args(argv)

    if args.live:
        return cmd_live(args)
    if args.validate_only:
        return cmd_validate_only(args)
    return cmd_default(args)


if __name__ == "__main__":
    sys.exit(main())
