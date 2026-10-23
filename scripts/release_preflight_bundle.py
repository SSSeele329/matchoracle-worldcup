#!/usr/bin/env python3
"""Run a redacted MatchOracle release preflight bundle."""

import argparse
import json
import os
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scripts.current_task import DEFAULT_TASKS_FILE, parse_current_task, read_text
from scripts.release_readiness_report import run_release_readiness_report
from scripts.smoke_provider_adapter_acceptance import run_provider_adapter_acceptance_smoke


DEFAULT_PRODUCTION_ENV_EXAMPLE = os.path.join(PROJECT_ROOT, "deploy", "production.env.example")
DEFAULT_PREFLIGHT_REPORT = os.path.join(PROJECT_ROOT, "reports", "release_preflight_bundle.json")
PREFLIGHT_EVENT = "MATCHORACLE_RELEASE_PREFLIGHT"
PREFLIGHT_STATUSES = {"PASS", "FAIL"}
PREFLIGHT_CHECK_STATUSES = {"PASS", "WARN", "FAIL"}
PREFLIGHT_REQUIRED_CHECK_NAMES = (
    "currentTask",
    "providerAdapterSmoke",
    "demoReadiness",
    "productionTemplateReadiness",
)
PREFLIGHT_OPTIONAL_CHECK_NAMES = (
    "productionReadyEnvReadiness",
)
PREFLIGHT_CHECK_NAMES = PREFLIGHT_REQUIRED_CHECK_NAMES + PREFLIGHT_OPTIONAL_CHECK_NAMES


def _write_report(path, content):
    report_path = os.path.abspath(path)
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as handle:
        handle.write(content)
        handle.write("\n")


def _capture_json_call(fn, *args, **kwargs):
    events = []
    errors = []
    kwargs["emit"] = events.append
    kwargs["error"] = errors.append
    exit_code = fn(*args, **kwargs)
    output = events[0] if events else None
    error_output = errors[0] if errors else None
    parsed_output = json.loads(output) if output else None
    parsed_error = json.loads(error_output) if error_output else None
    return {
        "exitCode": exit_code,
        "output": parsed_output,
        "error": parsed_error,
    }


def build_current_task_check(task_file=DEFAULT_TASKS_FILE):
    pointer = parse_current_task(read_text(task_file), source_path=task_file)
    return {
        "status": "PASS" if pointer.get("nextTask") == "NONE" else "WARN",
        "nextTask": pointer.get("nextTask"),
        "hasQueuedTask": pointer.get("hasQueuedTask"),
        "nextTaskRule": pointer.get("nextTaskRule"),
    }


def build_adapter_smoke_check(adapter_smoke_fn=run_provider_adapter_acceptance_smoke):
    captured = _capture_json_call(adapter_smoke_fn)
    output = captured["output"] or captured["error"] or {}
    return {
        "status": "PASS" if captured["exitCode"] == 0 and output.get("status") == "PASS" else "FAIL",
        "exitCode": captured["exitCode"],
        "smokeStatus": output.get("status"),
        "checked": output.get("checked"),
        "failed": output.get("failed"),
    }


def build_demo_readiness_check(readiness_fn=run_release_readiness_report):
    captured = _capture_json_call(
        readiness_fn,
        allow_demo=True,
        validate_schema=True,
    )
    output = captured["output"] or captured["error"] or {}
    return {
        "status": "PASS" if captured["exitCode"] == 0 and output.get("readinessStatus") in {"READY", "DEMO_READY"} else "FAIL",
        "exitCode": captured["exitCode"],
        "readinessStatus": output.get("readinessStatus"),
        "readyForProduction": output.get("readyForProduction"),
        "blockingChecks": output.get("blockingChecks"),
        "warningChecks": output.get("warningChecks"),
    }


def build_production_template_check(production_env_file=DEFAULT_PRODUCTION_ENV_EXAMPLE, readiness_fn=run_release_readiness_report):
    captured = _capture_json_call(
        readiness_fn,
        env_file=production_env_file,
        validate_schema=True,
    )
    output = captured["output"] or captured["error"] or {}
    expected_blocked = captured["exitCode"] == 2 and output.get("readinessStatus") == "BLOCKED"
    return {
        "status": "PASS" if expected_blocked else "FAIL",
        "exitCode": captured["exitCode"],
        "readinessStatus": output.get("readinessStatus"),
        "readyForProduction": output.get("readyForProduction"),
        "expected": "production.env.example must remain BLOCKED until real secrets and deployment settings are supplied.",
        "blockingChecks": output.get("blockingChecks"),
    }


def build_production_ready_env_check(ready_env_file, readiness_fn=run_release_readiness_report):
    captured = _capture_json_call(
        readiness_fn,
        env_file=ready_env_file,
        validate_schema=True,
    )
    output = captured["output"] or captured["error"] or {}
    ready = captured["exitCode"] == 0 and output.get("readinessStatus") == "READY" and output.get("readyForProduction") is True
    check = {
        "status": "PASS" if ready else "FAIL",
        "exitCode": captured["exitCode"],
        "readinessStatus": output.get("readinessStatus"),
        "readyForProduction": output.get("readyForProduction"),
        "expected": "The supplied production env file must pass release readiness as READY.",
        "blockingChecks": output.get("blockingChecks"),
        "warningChecks": output.get("warningChecks"),
    }
    if captured["error"]:
        check["errorEvent"] = output.get("event")
        check["errorCode"] = output.get("code")
        check["errorMessage"] = output.get("message")
    return check


def build_preflight_bundle(
    task_file=DEFAULT_TASKS_FILE,
    production_env_file=DEFAULT_PRODUCTION_ENV_EXAMPLE,
    ready_env_file=None,
    current_task_check_fn=build_current_task_check,
    adapter_smoke_check_fn=build_adapter_smoke_check,
    demo_readiness_check_fn=build_demo_readiness_check,
    production_template_check_fn=build_production_template_check,
    production_ready_env_check_fn=build_production_ready_env_check,
):
    checks = {
        "currentTask": current_task_check_fn(task_file),
        "providerAdapterSmoke": adapter_smoke_check_fn(),
        "demoReadiness": demo_readiness_check_fn(),
        "productionTemplateReadiness": production_template_check_fn(production_env_file),
    }
    if ready_env_file:
        checks["productionReadyEnvReadiness"] = production_ready_env_check_fn(ready_env_file)
    failed = [name for name, check in checks.items() if check.get("status") != "PASS"]
    return {
        "event": PREFLIGHT_EVENT,
        "status": "PASS" if not failed else "FAIL",
        "failedChecks": failed,
        "checks": checks,
        "redaction": "No token, secret, domain, store path, provider URL, or API key values are printed.",
    }


def validate_preflight_bundle(bundle):
    errors = []
    if not isinstance(bundle, dict):
        return {
            "status": "FAIL",
            "errors": ["bundle must be object."],
        }

    if bundle.get("event") != PREFLIGHT_EVENT:
        errors.append(f"event must be {PREFLIGHT_EVENT}.")
    if bundle.get("status") not in PREFLIGHT_STATUSES:
        errors.append("status must be PASS or FAIL.")

    failed_checks = bundle.get("failedChecks")
    if not isinstance(failed_checks, list) or not all(isinstance(name, str) and name for name in failed_checks):
        errors.append("failedChecks must be non-empty string list or empty list.")
        failed_checks = []

    checks = bundle.get("checks")
    if not isinstance(checks, dict):
        errors.append("checks must be object.")
        checks = {}

    actual_failed = []
    if isinstance(checks, dict):
        for name in PREFLIGHT_REQUIRED_CHECK_NAMES:
            if name not in checks:
                errors.append(f"checks.{name} must be object.")
        for name, check in checks.items():
            if name not in PREFLIGHT_CHECK_NAMES:
                continue
            if not isinstance(check, dict):
                errors.append(f"checks.{name} must be object.")
                continue
            status = check.get("status")
            if status not in PREFLIGHT_CHECK_STATUSES:
                errors.append(f"checks.{name}.status must be PASS, WARN, or FAIL.")
            if status != "PASS":
                actual_failed.append(name)
        extra_checks = sorted(set(checks.keys()) - set(PREFLIGHT_CHECK_NAMES))
        for name in extra_checks:
            errors.append(f"checks.{name} is not an allowed preflight check.")

    if list(failed_checks) != actual_failed:
        errors.append("failedChecks must equal non-PASS check names in preflight order.")
    if bundle.get("status") == "PASS" and actual_failed:
        errors.append("PASS bundle cannot contain non-PASS checks.")
    if bundle.get("status") == "FAIL" and not actual_failed:
        errors.append("FAIL bundle must contain at least one non-PASS check.")

    redaction = bundle.get("redaction")
    if not isinstance(redaction, str) or not redaction.strip():
        errors.append("redaction must be non-empty string.")

    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
    }


def _format_value(value):
    if value is True:
        return "yes"
    if value is False:
        return "no"
    if value is None:
        return "n/a"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else "none"
    return str(value)


def render_preflight_summary(bundle):
    lines = [
        f"Preflight: {bundle['status']}",
        f"Failed checks: {_format_value(bundle.get('failedChecks') or [])}",
    ]
    checks = bundle.get("checks") or {}
    for name in PREFLIGHT_CHECK_NAMES:
        check = checks.get(name)
        if not isinstance(check, dict):
            continue
        detail_parts = [f"status={check.get('status', 'n/a')}"]
        if "readinessStatus" in check:
            detail_parts.append(f"readiness={_format_value(check.get('readinessStatus'))}")
        if "readyForProduction" in check:
            detail_parts.append(f"readyForProduction={_format_value(check.get('readyForProduction'))}")
        if "nextTask" in check:
            detail_parts.append(f"nextTask={_format_value(check.get('nextTask'))}")
        if "smokeStatus" in check:
            detail_parts.append(f"smoke={_format_value(check.get('smokeStatus'))}")
        if "checked" in check:
            detail_parts.append(f"checked={_format_value(check.get('checked'))}")
        if "failed" in check:
            detail_parts.append(f"failed={_format_value(check.get('failed'))}")
        if "errorCode" in check:
            detail_parts.append(f"errorCode={_format_value(check.get('errorCode'))}")
        lines.append(f"- {name}: " + "; ".join(detail_parts))
    lines.append(f"Redaction: {bundle.get('redaction')}")
    return "\n".join(lines)


def run_release_preflight_bundle(
    task_file=DEFAULT_TASKS_FILE,
    production_env_file=DEFAULT_PRODUCTION_ENV_EXAMPLE,
    ready_env_file=None,
    summary=False,
    write_report=None,
    emit=print,
    error=print,
):
    try:
        bundle = build_preflight_bundle(
            task_file=task_file,
            production_env_file=production_env_file,
            ready_env_file=ready_env_file,
        )
        schema_validation = validate_preflight_bundle(bundle)
        if schema_validation["status"] != "PASS":
            error(json.dumps({
                "event": "MATCHORACLE_RELEASE_PREFLIGHT_SCHEMA_INVALID",
                "status": "FAIL",
                "details": schema_validation,
            }, ensure_ascii=False, sort_keys=True))
            return 2
        output = render_preflight_summary(bundle) if summary else json.dumps(bundle, ensure_ascii=False, sort_keys=True)
        if write_report:
            _write_report(write_report, output)
    except Exception as failure:
        error(json.dumps({
            "event": "MATCHORACLE_RELEASE_PREFLIGHT_FAILED",
            "status": "FAIL",
            "message": str(failure),
        }, ensure_ascii=False, sort_keys=True))
        return 2
    emit(output)
    return 0 if bundle["status"] == "PASS" else 2


def build_parser():
    parser = argparse.ArgumentParser(
        description="Run the MatchOracle release preflight bundle without starting Flask."
    )
    parser.add_argument("--task-file", default=DEFAULT_TASKS_FILE, help="Development task pointer file.")
    parser.add_argument("--production-env-file", default=DEFAULT_PRODUCTION_ENV_EXAMPLE, help="Production env template to verify as expected BLOCKED.")
    parser.add_argument("--ready-env-file", default=None, help="Optional real production env file that must pass readiness as READY.")
    parser.add_argument("--summary", action="store_true", help="Output a redacted human-readable preflight summary instead of JSON.")
    parser.add_argument("--write-report", default=None, help="Optional path to write the same redacted preflight output.")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return run_release_preflight_bundle(
        task_file=args.task_file,
        production_env_file=args.production_env_file,
        ready_env_file=args.ready_env_file,
        summary=args.summary,
        write_report=args.write_report,
        error=lambda payload: print(payload, file=sys.stderr),
    )


if __name__ == "__main__":
    sys.exit(main())
