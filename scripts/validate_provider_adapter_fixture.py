#!/usr/bin/env python3
"""Validate a provider adapter output fixture against MatchOracle acceptance rules."""

import argparse
import json
import os
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.worldcup.provider_adapter_acceptance import (
    ProviderAdapterAcceptanceError,
    validate_provider_adapter_output,
)


def build_error_payload(error):
    if isinstance(error, ProviderAdapterAcceptanceError):
        return {
            "event": "PROVIDER_ADAPTER_ACCEPTANCE_REJECTED",
            "code": error.code,
            "message": error.message,
            "details": error.details,
        }
    if isinstance(error, json.JSONDecodeError):
        return {
            "event": "PROVIDER_ADAPTER_FIXTURE_JSON_INVALID",
            "code": "PROVIDER_ADAPTER_FIXTURE_JSON_INVALID",
            "message": "Provider adapter fixture must be valid JSON.",
            "details": {"line": error.lineno, "column": error.colno},
        }
    return {
        "event": "PROVIDER_ADAPTER_ACCEPTANCE_FAILED",
        "code": "PROVIDER_ADAPTER_ACCEPTANCE_FAILED",
        "message": str(error),
        "details": {},
    }


def run_adapter_fixture_validation(
    fixture_path,
    expected_provider_id=None,
    required_fact_keys=None,
    allow_empty_required_buckets=False,
    emit=print,
    error=print,
):
    try:
        with open(fixture_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        result = validate_provider_adapter_output(
            payload,
            expected_provider_id=expected_provider_id,
            required_fact_keys=required_fact_keys,
            allow_empty_required_buckets=allow_empty_required_buckets,
        )
    except Exception as failure:
        error(json.dumps(build_error_payload(failure), ensure_ascii=False, sort_keys=True))
        return 2
    emit(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        description="Validate a provider adapter output JSON fixture against MatchOracle structured facts acceptance rules."
    )
    parser.add_argument("fixture", help="Path to adapter output fixture JSON.")
    parser.add_argument("--expected-provider-id", help="Require provider.providerId to match this value.")
    parser.add_argument(
        "--required-fact-key",
        action="append",
        default=[],
        help="Fact bucket that must exist and be non-empty. Can be repeated.",
    )
    parser.add_argument(
        "--allow-empty-required-buckets",
        action="store_true",
        help="Only require listed buckets to exist; do not require non-empty lists.",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return run_adapter_fixture_validation(
        args.fixture,
        expected_provider_id=args.expected_provider_id,
        required_fact_keys=args.required_fact_key,
        allow_empty_required_buckets=args.allow_empty_required_buckets,
        error=lambda payload: print(payload, file=sys.stderr),
    )


if __name__ == "__main__":
    sys.exit(main())
