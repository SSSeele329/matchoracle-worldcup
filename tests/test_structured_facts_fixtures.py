import json
from pathlib import Path

from scripts.query_structured_facts import EXIT_FOUND, run_structured_facts_query
from src.worldcup.provider_contracts import validate_structured_facts_payload
from src.worldcup.structured_facts_store import (
    get_latest_structured_facts,
    ingest_structured_facts_payload,
)


SAMPLE_PAYLOAD_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "structured_facts"
    / "worldcup_structured_facts_sample.json"
)


def load_sample_payload():
    with SAMPLE_PAYLOAD_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def test_structured_facts_demo_payload_is_contract_valid_and_marked_demo_only():
    payload = load_sample_payload()

    result = validate_structured_facts_payload(payload)

    assert result["status"] == "PASS"
    assert payload["auditContext"]["purpose"] == "demo_only"
    assert payload["auditContext"]["not_official_data"] is True
    assert payload["provider"]["productionReady"] is False
    assert payload["source"].startswith("demo_only_")


def test_structured_facts_demo_payload_ingests_and_queries_safe_read_model(tmp_path):
    store_path = tmp_path / "structured_facts.sqlite3"
    payload = load_sample_payload()

    ingestion = ingest_structured_facts_payload(
        payload,
        path=str(store_path),
        created_by="fixture_test",
    )
    result = get_latest_structured_facts(
        match_id="demo-arg-fra-2026",
        fact_key="fixtures",
        path=str(store_path),
    )

    assert ingestion["storageOperation"] == "INSERTED"
    assert result["status"] == "FOUND"
    assert result["factCount"] == 1
    assert result["latestSnapshotTime"] == "2026-06-01T12:00:00+00:00"
    assert result["facts"][0]["fact"]["homeTeam"] == "Argentina"
    assert result["facts"][0]["fact"]["demoOnly"] is True
    assert "payload" not in result["facts"][0]
    assert "payload_json" not in json.dumps(result, sort_keys=True)


def test_structured_facts_demo_payload_operator_cli_smoke_json(tmp_path):
    store_path = tmp_path / "structured_facts.sqlite3"
    payload = load_sample_payload()
    ingest_structured_facts_payload(payload, path=str(store_path), created_by="fixture_test")
    events = []
    errors = []

    exit_code = run_structured_facts_query(
        "demo-arg-fra-2026",
        fact_key="official_lineups",
        as_of="2026-06-01T12:30:00+00:00",
        store_path=str(store_path),
        json_output=True,
        emit=events.append,
        error=errors.append,
    )

    assert exit_code == EXIT_FOUND
    assert errors == []
    output = events[0]
    result = json.loads(output)
    assert result["status"] == "FOUND"
    assert result["factKey"] == "official_lineups"
    assert result["facts"][0]["fact"]["notOfficialData"] is True
    assert "payload_json" not in output
    assert "auditContext" not in output
