import json

from scripts.query_structured_facts import (
    EXIT_FOUND,
    EXIT_INVALID_QUERY,
    EXIT_NOT_FOUND,
    run_structured_facts_query,
)
from src.worldcup.provider_contracts import STRUCTURED_FACTS_CATEGORY
from src.worldcup.structured_facts_store import ingest_structured_facts_payload


def structured_facts_payload(snapshot_time, match_id="M1", home_team="Team A"):
    return {
        "provider": {
            "category": STRUCTURED_FACTS_CATEGORY,
            "providerId": "contract-provider",
        },
        "source": "contract-test-feed",
        "snapshotTime": snapshot_time,
        "auditContext": {"requestId": f"local-test-{snapshot_time}"},
        "facts": {
            "fixtures": [{
                "matchId": match_id,
                "homeTeam": home_team,
                "awayTeam": "Team B",
                "kickoffAt": "2026-06-12T20:00:00+00:00",
            }],
            "official_lineups": [{
                "matchId": match_id,
                "homeStarters": ["A1", "A2"],
                "awayStarters": ["B1", "B2"],
            }],
        },
    }


def query_events():
    return [], []


def test_structured_facts_query_cli_outputs_json_from_safe_read_model(tmp_path):
    store_path = tmp_path / "structured_facts.sqlite3"
    ingest_structured_facts_payload(
        structured_facts_payload("2026-06-01T10:00:00+00:00", home_team="Old Team A"),
        path=str(store_path),
    )
    ingest_structured_facts_payload(
        structured_facts_payload("2026-06-01T11:00:00+00:00", home_team="New Team A"),
        path=str(store_path),
    )
    events, errors = query_events()

    exit_code = run_structured_facts_query(
        "M1",
        fact_key="fixtures",
        store_path=str(store_path),
        json_output=True,
        emit=events.append,
        error=errors.append,
    )

    output = events[0]
    result = json.loads(output)
    assert exit_code == EXIT_FOUND
    assert errors == []
    assert result["status"] == "FOUND"
    assert result["latestSnapshotTime"] == "2026-06-01T11:00:00+00:00"
    assert result["facts"][0]["fact"]["homeTeam"] == "New Team A"
    assert "payload_json" not in output
    assert "auditContext" not in output


def test_structured_facts_query_cli_supports_as_of_snapshot_time(tmp_path):
    store_path = tmp_path / "structured_facts.sqlite3"
    ingest_structured_facts_payload(
        structured_facts_payload("2026-06-01T10:00:00+00:00", home_team="Old Team A"),
        path=str(store_path),
    )
    ingest_structured_facts_payload(
        structured_facts_payload("2026-06-01T11:00:00+00:00", home_team="New Team A"),
        path=str(store_path),
    )
    events, errors = query_events()

    exit_code = run_structured_facts_query(
        "M1",
        fact_key="fixtures",
        as_of="2026-06-01T10:30:00+00:00",
        store_path=str(store_path),
        json_output=True,
        emit=events.append,
        error=errors.append,
    )

    result = json.loads(events[0])
    assert exit_code == EXIT_FOUND
    assert errors == []
    assert result["asOfSnapshotTime"] == "2026-06-01T10:30:00+00:00"
    assert result["latestSnapshotTime"] == "2026-06-01T10:00:00+00:00"
    assert result["facts"][0]["fact"]["homeTeam"] == "Old Team A"


def test_structured_facts_query_cli_rejects_naive_as_of_time(tmp_path):
    store_path = tmp_path / "structured_facts.sqlite3"
    ingest_structured_facts_payload(
        structured_facts_payload("2026-06-01T10:00:00+00:00"),
        path=str(store_path),
    )
    events, errors = query_events()

    exit_code = run_structured_facts_query(
        "M1",
        as_of="2026-06-01T10:30:00",
        store_path=str(store_path),
        json_output=True,
        emit=events.append,
        error=errors.append,
    )

    error = json.loads(errors[0])
    assert exit_code == EXIT_INVALID_QUERY
    assert events == []
    assert error["event"] == "STRUCTURED_FACTS_QUERY_REJECTED"
    assert error["code"] == "STRUCTURED_FACTS_READ_SNAPSHOT_TIME_INVALID"


def test_structured_facts_query_cli_rejects_unknown_fact_key(tmp_path):
    store_path = tmp_path / "structured_facts.sqlite3"
    ingest_structured_facts_payload(
        structured_facts_payload("2026-06-01T10:00:00+00:00"),
        path=str(store_path),
    )
    events, errors = query_events()

    exit_code = run_structured_facts_query(
        "M1",
        fact_key="expected_lineup_evidence",
        store_path=str(store_path),
        json_output=True,
        emit=events.append,
        error=errors.append,
    )

    error = json.loads(errors[0])
    assert exit_code == EXIT_INVALID_QUERY
    assert events == []
    assert error["code"] == "STRUCTURED_FACTS_READ_FACT_KEY_INVALID"


def test_structured_facts_query_cli_returns_stable_not_found_exit(tmp_path):
    store_path = tmp_path / "structured_facts.sqlite3"
    ingest_structured_facts_payload(
        structured_facts_payload("2026-06-01T10:00:00+00:00", match_id="M1"),
        path=str(store_path),
    )
    events, errors = query_events()

    exit_code = run_structured_facts_query(
        "M2",
        store_path=str(store_path),
        emit=events.append,
        error=errors.append,
    )

    assert exit_code == EXIT_NOT_FOUND
    assert errors == []
    assert events == ["No structured facts found for matchId=M2."]
