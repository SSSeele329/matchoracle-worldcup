#!/usr/bin/env python3
"""Smoke-check built-in provider adapter acceptance fixtures."""

import argparse
import json
import os
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scripts.validate_provider_adapter_fixture import run_adapter_fixture_validation


DEFAULT_SMOKE_FIXTURES = (
    {
        "name": "provider_adapter_fixture_template",
        "fixture": os.path.join(
            PROJECT_ROOT,
            "data",
            "structured_facts",
            "provider_adapter_fixture_template.json",
        ),
        "expectedProviderId": "template_structured_facts_adapter",
        "requiredFactKeys": ["fixtures", "official_lineups"],
    },
    {
        "name": "demo_structured_facts_fixture",
        "fixture": os.path.join(
            PROJECT_ROOT,
            "data",
            "structured_facts",
            "worldcup_structured_facts_sample.json",
        ),
        "expectedProviderId": "demo_structured_facts_fixture",
        "requiredFactKeys": ["fixtures", "official_lineups"],
    },
)

SMOKE_EVENT = "PROVIDER_ADAPTER_ACCEPTANCE_SMOKE"
SMOKE_STATUSES = {"PASS", "FAIL"}


def _relative_fixture_path(path):
    return os.path.relpath(path, PROJECT_ROOT)


def _write_report(path, output):
    report_path = os.path.abspath(path)
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as handle:
        handle.write(output)
        handle.write("\n")


def validate_smoke_summary(summary):
    errors = []
    if not isinstance(summary, dict):
        return {
            "status": "FAIL",
            "errors": ["summary must be object."],
        }

    if summary.get("event") != SMOKE_EVENT:
        errors.append(f"event must be {SMOKE_EVENT}.")
    if summary.get("status") not in SMOKE_STATUSES:
        errors.append("status must be PASS or FAIL.")

    checked = summary.get("checked")
    failed = summary.get("failed")
    checks = summary.get("checks")
    if not isinstance(checked, int) or checked < 0:
        errors.append("checked must be non-negative integer.")
    if not isinstance(failed, int) or failed < 0:
        errors.append("failed must be non-negative integer.")
    if not isinstance(checks, list):
        errors.append("checks must be list.")
        checks = []

    if isinstance(checked, int) and len(checks) != checked:
        errors.append("checked must equal len(checks).")

    failed_count = 0
    for index, check in enumerate(checks):
        path = f"checks.{index}"
        if not isinstance(check, dict):
            errors.append(f"{path} must be object.")
            continue
        for field in ("name", "fixture", "expectedProviderId", "status"):
            if not isinstance(check.get(field), str) or not check.get(field).strip():
                errors.append(f"{path}.{field} must be non-empty string.")
        required_fact_keys = check.get("requiredFactKeys")
        if not isinstance(required_fact_keys, list) or not all(isinstance(key, str) and key for key in required_fact_keys):
            errors.append(f"{path}.requiredFactKeys must be non-empty string list.")
        status = check.get("status")
        if status not in SMOKE_STATUSES:
            errors.append(f"{path}.status must be PASS or FAIL.")
        if status == "FAIL":
            failed_count += 1
            if "error" not in check:
                errors.append(f"{path}.error is required when status is FAIL.")
        if status == "PASS":
            result = check.get("result")
            if not isinstance(result, dict) or result.get("status") != "PASS":
                errors.append(f"{path}.result.status must be PASS when check status is PASS.")

    if isinstance(failed, int) and failed != failed_count:
        errors.append("failed must equal number of failed checks.")
    if summary.get("status") == "PASS" and failed_count != 0:
        errors.append("PASS summary cannot contain failed checks.")
    if summary.get("status") == "FAIL" and failed_count == 0:
        errors.append("FAIL summary must contain at least one failed check.")

    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
    }


def run_provider_adapter_acceptance_smoke(fixtures=None, write_report_path=None, emit=print, error=print):
    fixtures = fixtures or DEFAULT_SMOKE_FIXTURES
    checks = []
    failures = []

    for fixture in fixtures:
        events = []
        errors = []
        exit_code = run_adapter_fixture_validation(
            fixture["fixture"],
            expected_provider_id=fixture["expectedProviderId"],
            required_fact_keys=fixture["requiredFactKeys"],
            emit=events.append,
            error=errors.append,
        )
        check = {
            "name": fixture["name"],
            "fixture": _relative_fixture_path(fixture["fixture"]),
            "expectedProviderId": fixture["expectedProviderId"],
            "requiredFactKeys": fixture["requiredFactKeys"],
            "status": "PASS" if exit_code == 0 else "FAIL",
        }
        if events:
            check["result"] = json.loads(events[0])
        if errors:
            check["error"] = json.loads(errors[0])
            failures.append(check)
        checks.append(check)

    summary = {
        "event": SMOKE_EVENT,
        "status": "PASS" if not failures else "FAIL",
        "checked": len(checks),
        "failed": len(failures),
        "checks": checks,
    }

    schema_validation = validate_smoke_summary(summary)
    if schema_validation["status"] != "PASS":
        error(json.dumps({
            "event": "PROVIDER_ADAPTER_ACCEPTANCE_SMOKE_SCHEMA_INVALID",
            "status": "FAIL",
            "details": schema_validation,
        }, ensure_ascii=False, sort_keys=True))
        return 2

    output = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    if write_report_path:
        try:
            _write_report(write_report_path, output)
        except OSError as failure:
            error(json.dumps({
                "event": "PROVIDER_ADAPTER_ACCEPTANCE_SMOKE_REPORT_WRITE_FAILED",
                "status": "FAIL",
                "message": str(failure),
            }, ensure_ascii=False, sort_keys=True))
            return 2

    if failures:
        error(output)
        return 2
    emit(output)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        description="Smoke-check built-in MatchOracle provider adapter acceptance fixtures."
    )
    parser.add_argument(
        "--write-report",
        help="Write the same redacted JSON smoke summary to this file path.",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return run_provider_adapter_acceptance_smoke(
        write_report_path=args.write_report,
        error=lambda payload: print(payload, file=sys.stderr),
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
