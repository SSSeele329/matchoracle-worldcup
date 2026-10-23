#!/usr/bin/env python3
"""Query structured facts through the safe read model."""

import argparse
import json
import os
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.worldcup.structured_facts_store import (  # noqa: E402
    StructuredFactsReadModelError,
    get_latest_structured_facts,
)


EXIT_FOUND = 0
EXIT_NOT_FOUND = 1
EXIT_INVALID_QUERY = 2


def error_payload(event, failure):
    if isinstance(failure, StructuredFactsReadModelError):
        return {
            "event": event,
            "code": failure.code,
            "message": failure.message,
            "details": failure.details,
        }
    return {
        "event": event,
        "code": "STRUCTURED_FACTS_QUERY_FAILED",
        "message": str(failure),
        "details": {},
    }


def emit_json(payload, emit):
    emit(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def render_human_result(result):
    if result["status"] != "FOUND":
        parts = [f"No structured facts found for matchId={result['matchId']}"]
        if result.get("factKey"):
            parts.append(f"factKey={result['factKey']}")
        if result.get("asOfSnapshotTime"):
            parts.append(f"asOf={result['asOfSnapshotTime']}")
        return " ".join(parts) + "."

    lines = [
        f"Structured facts for matchId={result['matchId']}",
        f"status={result['status']} factCount={result['factCount']} latestSnapshotTime={result['latestSnapshotTime']}",
    ]
    if result.get("factKey"):
        lines.append(f"factKey={result['factKey']}")
    if result.get("asOfSnapshotTime"):
        lines.append(f"asOf={result['asOfSnapshotTime']}")
    for item in result["facts"]:
        lines.append(
            " - "
            + f"factKey={item['factKey']} "
            + f"matchId={item['matchId']} "
            + f"snapshotTime={item['snapshotTime']} "
            + f"source={item['source']} "
            + f"ingestionId={item['ingestionId']}"
        )
        lines.append("   fact=" + json.dumps(item["fact"], ensure_ascii=False, sort_keys=True))
    return "\n".join(lines)


def run_structured_facts_query(
    match_id,
    fact_key=None,
    as_of=None,
    limit=20,
    store_path=None,
    json_output=False,
    emit=print,
    error=print,
):
    try:
        result = get_latest_structured_facts(
            match_id=match_id,
            fact_key=fact_key,
            snapshot_time=as_of,
            limit=limit,
            path=store_path,
        )
    except StructuredFactsReadModelError as failure:
        payload = error_payload("STRUCTURED_FACTS_QUERY_REJECTED", failure)
        if json_output:
            emit_json(payload, error)
        else:
            error(f"{payload['code']}: {payload['message']}")
        return EXIT_INVALID_QUERY

    if json_output:
        emit_json(result, emit)
    else:
        emit(render_human_result(result))
    return EXIT_FOUND if result["status"] == "FOUND" else EXIT_NOT_FOUND


def build_parser():
    parser = argparse.ArgumentParser(
        description="Query structured facts from the local safe read model."
    )
    parser.add_argument("--match-id", required=True, help="Match id to query.")
    parser.add_argument("--fact-key", help="Optional structured fact bucket.")
    parser.add_argument("--as-of", help="Optional timezone-aware ISO timestamp upper bound.")
    parser.add_argument("--limit", type=int, default=20, help="Maximum fact items to print. Defaults to 20.")
    parser.add_argument("--store", help="Optional SQLite store path. Defaults to MATCHORACLE_STRUCTURED_FACTS_STORE or local data store.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return run_structured_facts_query(
        args.match_id,
        fact_key=args.fact_key,
        as_of=args.as_of,
        limit=args.limit,
        store_path=args.store,
        json_output=args.json,
        error=lambda payload: print(payload, file=sys.stderr),
    )


if __name__ == "__main__":
    sys.exit(main())
