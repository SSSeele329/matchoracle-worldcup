#!/usr/bin/env python3
"""Print a redacted MatchOracle release readiness manifest without starting a server."""

import argparse
import json
import os
import re
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.worldcup.readiness import build_readiness_report
from src.worldcup.release_manifest import ReleaseManifestSchemaError, validate_release_readiness_manifest


ENV_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class EnvFileError(ValueError):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def strip_optional_quotes(value):
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
        return stripped[1:-1]
    return stripped


def parse_env_file(path):
    values = {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError as failure:
        raise EnvFileError(
            "ENV_FILE_READ_FAILED",
            "Could not read env file.",
            details={"path": path},
        ) from failure

    for index, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            raise EnvFileError(
                "ENV_FILE_LINE_INVALID",
                "Env file lines must use KEY=value syntax.",
                details={"line": index},
            )
        key, value = line.split("=", 1)
        key = key.strip()
        if not ENV_KEY_PATTERN.match(key):
            raise EnvFileError(
                "ENV_FILE_KEY_INVALID",
                "Env file contains an invalid key.",
                details={"line": index, "key": key},
            )
        values[key] = strip_optional_quotes(value)
    return values


def format_name_list(values):
    values = [value for value in values if value]
    return ", ".join(values) if values else "none"


def render_summary(manifest):
    env_names = [item["name"] for item in manifest.get("environmentVariables") or []]
    lines = [
        f"Readiness: {manifest['readinessStatus']}",
        f"Ready for production: {'yes' if manifest['readyForProduction'] else 'no'}",
        f"Environment: {manifest['environment']}",
        f"Status counts: PASS={manifest['statusCounts'].get('PASS', 0)} WARN={manifest['statusCounts'].get('WARN', 0)} FAIL={manifest['statusCounts'].get('FAIL', 0)}",
        f"Blocking checks: {format_name_list(manifest.get('blockingChecks') or [])}",
        f"Warning checks: {format_name_list(manifest.get('warningChecks') or [])}",
        f"Environment variables to review: {format_name_list(env_names)}",
        "Redaction: values are not printed.",
    ]
    return "\n".join(lines)


def write_report_file(path, content):
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
        if not content.endswith("\n"):
            handle.write("\n")


def run_release_readiness_report(
    allow_demo=False,
    validate_schema=False,
    summary=False,
    env_file=None,
    write_report=None,
    emit=print,
    error=print,
    report_fn=build_readiness_report,
):
    if env_file:
        try:
            environ = parse_env_file(env_file)
        except EnvFileError as failure:
            error(json.dumps({
                "event": "RELEASE_READINESS_ENV_FILE_FAILED",
                "code": failure.code,
                "message": failure.message,
                "details": failure.details,
            }, ensure_ascii=False, sort_keys=True))
            return 4
        report = report_fn(environ=environ)
    else:
        report = report_fn()
    manifest = report["releaseReadinessManifest"]
    if validate_schema:
        try:
            validate_release_readiness_manifest(manifest)
        except ReleaseManifestSchemaError as failure:
            error(json.dumps({
                "event": "RELEASE_READINESS_SCHEMA_FAILED",
                "errors": failure.errors,
            }, ensure_ascii=False, sort_keys=True))
            return 3
    if summary:
        output = render_summary(manifest)
    else:
        output = json.dumps(manifest, ensure_ascii=False, sort_keys=True)
    if write_report:
        write_report_file(write_report, output)
    emit(output)
    if manifest["readinessStatus"] == "READY":
        return 0
    if allow_demo and manifest["readinessStatus"] == "DEMO_READY":
        return 0
    return 2


def build_parser():
    parser = argparse.ArgumentParser(
        description="Print the redacted MatchOracle release readiness manifest without starting Flask."
    )
    parser.add_argument(
        "--allow-demo",
        action="store_true",
        help="Return exit code 0 for DEMO_READY local environments.",
    )
    parser.add_argument(
        "--validate-schema",
        action="store_true",
        help="Validate the manifest schema before printing it. Schema failures return exit code 3.",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a human-readable redacted readiness summary instead of JSON.",
    )
    parser.add_argument(
        "--env-file",
        help="Run readiness against a KEY=value env file instead of the current process environment.",
    )
    parser.add_argument(
        "--write-report",
        help="Write the same redacted JSON or summary output to a file path.",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return run_release_readiness_report(
        allow_demo=args.allow_demo,
        validate_schema=args.validate_schema,
        summary=args.summary,
        env_file=args.env_file,
        write_report=args.write_report,
        error=lambda payload: print(payload, file=sys.stderr),
    )


if __name__ == "__main__":
    sys.exit(main())
