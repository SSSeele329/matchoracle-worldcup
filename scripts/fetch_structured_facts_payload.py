#!/usr/bin/env python3
"""Fetch, validate, and optionally ingest a contract-shaped structured facts payload."""

import argparse
import json
import os
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.worldcup.provider_contracts import StructuredFactsPayloadError
from src.worldcup.structured_facts_http_provider import (
    StructuredFactsHttpProviderError,
    fetch_validate_and_optionally_ingest_structured_facts,
)


def error_payload(failure):
    if isinstance(failure, StructuredFactsHttpProviderError):
        return {
            "event": "STRUCTURED_FACTS_PROVIDER_FETCH_REJECTED",
            "code": failure.code,
            "message": failure.message,
            "details": failure.details,
        }
    if isinstance(failure, StructuredFactsPayloadError):
        return {
            "event": "STRUCTURED_FACTS_PROVIDER_PAYLOAD_REJECTED",
            "code": failure.code,
            "message": failure.message,
            "details": failure.details,
        }
    return {
        "event": "STRUCTURED_FACTS_PROVIDER_FETCH_FAILED",
        "code": "STRUCTURED_FACTS_PROVIDER_FETCH_FAILED",
        "message": str(failure),
        "details": {},
    }


def run_structured_facts_fetch(
    url=None,
    token=None,
    match_id=None,
    snapshot_time=None,
    store_path=None,
    created_by="structured_facts_http_cli",
    timeout=20,
    dry_run=False,
    emit=print,
    error=print,
):
    try:
        result = fetch_validate_and_optionally_ingest_structured_facts(
            base_url=url,
            token=token,
            match_id=match_id,
            snapshot_time=snapshot_time,
            timeout=timeout,
            store_path=store_path,
            created_by=created_by,
            dry_run=dry_run,
        )
    except (StructuredFactsHttpProviderError, StructuredFactsPayloadError, OSError) as failure:
        error(json.dumps(error_payload(failure), ensure_ascii=False, sort_keys=True))
        return 2
    emit(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        description="Fetch a contract-shaped structured facts payload from an HTTP provider."
    )
    parser.add_argument("--url", help="Provider contract endpoint. Defaults to MATCHORACLE_STRUCTURED_FACTS_API_BASE_URL.")
    parser.add_argument("--token", help="Provider token. Defaults to MATCHORACLE_STRUCTURED_FACTS_PROVIDER_TOKEN.")
    parser.add_argument("--match-id", help="Optional matchId query parameter.")
    parser.add_argument("--snapshot-time", help="Optional snapshotTime query parameter.")
    parser.add_argument("--store", help="Optional structured facts SQLite store path.")
    parser.add_argument("--created-by", default="structured_facts_http_cli", help="Audit label for ingestion.")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout in seconds.")
    parser.add_argument("--dry-run", action="store_true", help="Validate only; do not ingest into the store.")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return run_structured_facts_fetch(
        url=args.url,
        token=args.token,
        match_id=args.match_id,
        snapshot_time=args.snapshot_time,
        store_path=args.store,
        created_by=args.created_by,
        timeout=args.timeout,
        dry_run=args.dry_run,
        error=lambda payload: print(payload, file=sys.stderr),
    )


if __name__ == "__main__":
    sys.exit(main())
