#!/usr/bin/env python3
"""Ingest a validated structured facts payload into the local audit store."""

import argparse
import json
import os
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.worldcup.provider_contracts import StructuredFactsPayloadError
from src.worldcup.structured_facts_store import ingest_structured_facts_payload


def load_json_payload(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def error_payload(event, failure):
    if isinstance(failure, StructuredFactsPayloadError):
        return {
            "event": event,
            "code": failure.code,
            "message": failure.message,
            "details": failure.details,
        }
    if isinstance(failure, json.JSONDecodeError):
        return {
            "event": event,
            "code": "STRUCTURED_FACTS_PAYLOAD_JSON_INVALID",
            "message": "Structured facts payload must be valid JSON.",
            "details": {"line": failure.lineno, "column": failure.colno},
        }
    return {
        "event": event,
        "code": "STRUCTURED_FACTS_INGESTION_FAILED",
        "message": str(failure),
        "details": {},
    }


def run_structured_facts_ingestion(payload_path, store_path=None, created_by="local_cli", emit=print, error=print):
    try:
        payload = load_json_payload(payload_path)
        result = ingest_structured_facts_payload(payload, path=store_path, created_by=created_by)
    except (OSError, json.JSONDecodeError, StructuredFactsPayloadError) as failure:
        error(json.dumps(error_payload("STRUCTURED_FACTS_INGESTION_REJECTED", failure), ensure_ascii=False, sort_keys=True))
        return 2
    emit(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        description="Validate and ingest a structured facts payload into the local audit store."
    )
    parser.add_argument("payload", help="Path to a structured facts payload JSON file.")
    parser.add_argument("--store", help="Optional SQLite store path. Defaults to MATCHORACLE_STRUCTURED_FACTS_STORE or local data store.")
    parser.add_argument("--created-by", default="local_cli", help="Audit label for the ingestion actor.")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return run_structured_facts_ingestion(
        args.payload,
        store_path=args.store,
        created_by=args.created_by,
        error=lambda payload: print(payload, file=sys.stderr),
    )


if __name__ == "__main__":
    sys.exit(main())
