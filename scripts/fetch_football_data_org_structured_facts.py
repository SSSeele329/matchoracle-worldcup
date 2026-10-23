#!/usr/bin/env python3
"""Fetch football-data.org World Cup facts and normalize them to MatchOracle's contract."""

import argparse
import json
import os
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.worldcup.football_data_org_adapter import (  # noqa: E402
    DEFAULT_COMPETITION,
    DEFAULT_SEASON,
    FOOTBALL_DATA_ORG_BASE_URL_ENV,
    FOOTBALL_DATA_ORG_COMPETITION_ENV,
    FOOTBALL_DATA_ORG_SEASON_ENV,
    FOOTBALL_DATA_ORG_TOKEN_ENV,
    FootballDataOrgAdapterError,
    fetch_worldcup_structured_facts_payload,
)
from src.worldcup.structured_facts_store import ingest_structured_facts_payload  # noqa: E402


def error_payload(failure):
    if isinstance(failure, FootballDataOrgAdapterError):
        return {
            "event": "FOOTBALL_DATA_ORG_ADAPTER_REJECTED",
            "code": failure.code,
            "message": failure.message,
            "details": failure.details,
        }
    return {
        "event": "FOOTBALL_DATA_ORG_ADAPTER_FAILED",
        "code": "FOOTBALL_DATA_ORG_ADAPTER_FAILED",
        "message": str(failure),
        "details": {},
    }


def fact_counts(payload):
    return {key: len(value) for key, value in sorted((payload.get("facts") or {}).items())}


def write_json(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def run_football_data_org_fetch(
    token=None,
    base_url=None,
    competition=None,
    season=None,
    snapshot_time=None,
    match_id=None,
    timeout=20,
    include_standings=True,
    allow_partial_standings=True,
    output=None,
    ingest=False,
    store_path=None,
    emit=print,
    error=print,
):
    try:
        payload = fetch_worldcup_structured_facts_payload(
            token=token,
            base_url=base_url,
            competition=competition,
            season=season,
            snapshot_time=snapshot_time,
            match_id=match_id,
            timeout=timeout,
            include_standings=include_standings,
            allow_partial_standings=allow_partial_standings,
        )
        ingestion = None
        if output:
            write_json(output, payload)
        if ingest:
            ingestion = ingest_structured_facts_payload(
                payload,
                path=store_path,
                created_by="football_data_org_adapter_cli",
            )
    except (FootballDataOrgAdapterError, OSError) as failure:
        error(json.dumps(error_payload(failure), ensure_ascii=False, sort_keys=True))
        return 2

    if output or ingest:
        summary = {
            "status": "INGESTED" if ingest else "WRITTEN",
            "providerId": payload["provider"]["providerId"],
            "source": payload["source"],
            "snapshotTime": payload["snapshotTime"],
            "factCounts": fact_counts(payload),
        }
        if output:
            summary["output"] = output
        if ingestion:
            summary["ingestion"] = ingestion
        emit(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    else:
        emit(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(
        description="Fetch football-data.org World Cup data and output MatchOracle structured facts JSON."
    )
    parser.add_argument("--token", help=f"football-data.org token. Defaults to {FOOTBALL_DATA_ORG_TOKEN_ENV}.")
    parser.add_argument("--base-url", help=f"API base URL. Defaults to {FOOTBALL_DATA_ORG_BASE_URL_ENV} or official v4 URL.")
    parser.add_argument("--competition", default=None, help=f"Competition code. Defaults to {FOOTBALL_DATA_ORG_COMPETITION_ENV} or {DEFAULT_COMPETITION}.")
    parser.add_argument("--season", default=None, help=f"Season year. Defaults to {FOOTBALL_DATA_ORG_SEASON_ENV} or {DEFAULT_SEASON}.")
    parser.add_argument("--snapshot-time", help="Timezone-aware ISO timestamp for this fetch snapshot.")
    parser.add_argument("--match-id", help="Optional provider match id or MatchOracle matchId filter.")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout in seconds.")
    parser.add_argument("--no-standings", action="store_true", help="Skip the standings endpoint.")
    parser.add_argument(
        "--strict-standings",
        action="store_true",
        help="Fail the run if standings cannot be fetched instead of emitting an empty standings bucket.",
    )
    parser.add_argument("--output", help="Write normalized payload to this JSON file instead of printing it.")
    parser.add_argument("--ingest", action="store_true", help="Ingest the normalized payload into the structured facts store.")
    parser.add_argument("--store", help="Optional structured facts SQLite store path.")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return run_football_data_org_fetch(
        token=args.token,
        base_url=args.base_url,
        competition=args.competition,
        season=args.season,
        snapshot_time=args.snapshot_time,
        match_id=args.match_id,
        timeout=args.timeout,
        include_standings=not args.no_standings,
        allow_partial_standings=not args.strict_standings,
        output=args.output,
        ingest=args.ingest,
        store_path=args.store,
        error=lambda payload: print(payload, file=sys.stderr),
    )


if __name__ == "__main__":
    sys.exit(main())
