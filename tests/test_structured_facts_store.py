import json

import pytest

from scripts.ingest_structured_facts_payload import run_structured_facts_ingestion
from src.worldcup.provider_contracts import (
    AI_EVIDENCE_CATEGORY,
    CSV_MANUAL_FALLBACK_CATEGORY,
    STRUCTURED_FACTS_CATEGORY,
    StructuredFactsPayloadError,
)
from src.worldcup.structured_facts_store import (
    StructuredFactsReadModelError,
    get_structured_fact_ingestion,
    get_latest_structured_facts,
    ingest_structured_facts_payload,
    list_structured_fact_ingestions,
    list_structured_fact_items,
)


def valid_structured_facts_payload():
    return {
        "provider": {
            "category": STRUCTURED_FACTS_CATEGORY,
            "providerId": "contract-provider",
        },
        "source": "contract-test-feed",
        "snapshotTime": "2026-06-01T10:00:00Z",
        "auditContext": {"requestId": "local-test"},
        "facts": {
            "fixtures": [{
                "matchId": "M1",
                "homeTeam": "Team A",
                "awayTeam": "Team B",
                "kickoffAt": "2026-06-12T20:00:00+00:00",
            }],
            "official_lineups": [{
                "matchId": "M1",
                "homeStarters": ["A1", "A2"],
                "awayStarters": ["B1", "B2"],
            }],
            "scores": [],
        },
    }


def structured_facts_payload(snapshot_time, match_id="M1", home_team="Team A", starters=None):
    payload = valid_structured_facts_payload()
    payload["snapshotTime"] = snapshot_time
    payload["auditContext"] = {"requestId": f"local-test-{snapshot_time}"}
    payload["facts"]["fixtures"][0]["matchId"] = match_id
    payload["facts"]["fixtures"][0]["homeTeam"] = home_team
    payload["facts"]["official_lineups"][0]["matchId"] = match_id
    payload["facts"]["official_lineups"][0]["homeStarters"] = starters or ["A1", "A2"]
    return payload


def test_structured_facts_ingestion_persists_valid_payload_and_fact_items(tmp_path):
    store_path = tmp_path / "structured_facts.sqlite3"

    result = ingest_structured_facts_payload(
        valid_structured_facts_payload(),
        path=str(store_path),
        created_by="test-worker",
    )

    assert result["storageOperation"] == "INSERTED"
    assert result["providerCategory"] == STRUCTURED_FACTS_CATEGORY
    assert result["factCounts"] == {"fixtures": 1, "official_lineups": 1, "scores": 0}
    assert result["auditMetadata"] == {"auditContext": {"requestId": "local-test"}}

    fetched = get_structured_fact_ingestion(result["ingestionId"], path=str(store_path), include_payload=True)
    items = list_structured_fact_items(result["ingestionId"], path=str(store_path))

    assert fetched["payload"]["facts"]["fixtures"][0]["matchId"] == "M1"
    assert {item["factKey"] for item in items} == {"fixtures", "official_lineups"}
    assert len(items) == 2


def test_structured_facts_ingestion_rejects_payload_without_provider_metadata_before_store(tmp_path):
    store_path = tmp_path / "structured_facts.sqlite3"
    payload = valid_structured_facts_payload()
    payload.pop("provider")

    with pytest.raises(StructuredFactsPayloadError) as error:
        ingest_structured_facts_payload(payload, path=str(store_path))

    assert error.value.code == "STRUCTURED_FACTS_INGESTION_PROVIDER_INVALID"
    assert not store_path.exists()


def test_structured_facts_ingestion_rejects_ai_provider_category_before_store(tmp_path):
    store_path = tmp_path / "structured_facts.sqlite3"
    payload = valid_structured_facts_payload()
    payload["provider"]["category"] = AI_EVIDENCE_CATEGORY

    with pytest.raises(StructuredFactsPayloadError) as error:
        ingest_structured_facts_payload(payload, path=str(store_path))

    assert error.value.code == "STRUCTURED_FACTS_PAYLOAD_INVALID"
    assert "provider.category must be STRUCTURED_FACT_DATA_SOURCE." in error.value.details["errors"]
    assert not store_path.exists()


def test_structured_facts_ingestion_rejects_csv_manual_fallback_category_before_store(tmp_path):
    store_path = tmp_path / "structured_facts.sqlite3"
    payload = valid_structured_facts_payload()
    payload["provider"]["category"] = CSV_MANUAL_FALLBACK_CATEGORY

    with pytest.raises(StructuredFactsPayloadError) as error:
        ingest_structured_facts_payload(payload, path=str(store_path))

    assert error.value.code == "STRUCTURED_FACTS_PAYLOAD_INVALID"
    assert "provider.category must be STRUCTURED_FACT_DATA_SOURCE." in error.value.details["errors"]
    assert not store_path.exists()


def test_structured_facts_ingestion_rejects_unknown_fact_key_before_store(tmp_path):
    store_path = tmp_path / "structured_facts.sqlite3"
    payload = valid_structured_facts_payload()
    payload["facts"]["expected_lineup_evidence"] = [{"player": "A1"}]

    with pytest.raises(StructuredFactsPayloadError) as error:
        ingest_structured_facts_payload(payload, path=str(store_path))

    assert "facts.expected_lineup_evidence is not an allowed structured fact key." in error.value.details["errors"]
    assert not store_path.exists()


def test_structured_facts_ingestion_is_idempotent_by_payload_hash(tmp_path):
    store_path = tmp_path / "structured_facts.sqlite3"
    payload = valid_structured_facts_payload()

    first = ingest_structured_facts_payload(payload, path=str(store_path))
    second = ingest_structured_facts_payload(payload, path=str(store_path))

    assert first["ingestionId"] == second["ingestionId"]
    assert second["storageOperation"] == "DUPLICATE_PAYLOAD"
    assert len(list_structured_fact_ingestions(path=str(store_path))) == 1
    assert len(list_structured_fact_items(first["ingestionId"], path=str(store_path))) == 2


def test_structured_facts_ingestion_cli_ingests_payload_without_server(tmp_path):
    store_path = tmp_path / "structured_facts.sqlite3"
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps(valid_structured_facts_payload()), encoding="utf-8")
    events = []
    errors = []

    exit_code = run_structured_facts_ingestion(
        str(payload_path),
        store_path=str(store_path),
        created_by="test-cli",
        emit=events.append,
        error=errors.append,
    )

    result = json.loads(events[0])
    assert exit_code == 0
    assert errors == []
    assert result["createdBy"] == "test-cli"
    assert result["storageOperation"] == "INSERTED"


def test_structured_facts_ingestion_cli_rejects_invalid_payload_without_store(tmp_path):
    store_path = tmp_path / "structured_facts.sqlite3"
    payload_path = tmp_path / "payload.json"
    payload = valid_structured_facts_payload()
    payload["provider"]["category"] = CSV_MANUAL_FALLBACK_CATEGORY
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    events = []
    errors = []

    exit_code = run_structured_facts_ingestion(
        str(payload_path),
        store_path=str(store_path),
        emit=events.append,
        error=errors.append,
    )

    error = json.loads(errors[0])
    assert exit_code == 2
    assert events == []
    assert error["event"] == "STRUCTURED_FACTS_INGESTION_REJECTED"
    assert error["code"] == "STRUCTURED_FACTS_PAYLOAD_INVALID"
    assert not store_path.exists()


def test_structured_facts_read_model_returns_latest_fact_by_match_and_key(tmp_path):
    store_path = tmp_path / "structured_facts.sqlite3"
    ingest_structured_facts_payload(
        structured_facts_payload("2026-06-01T10:00:00+00:00", home_team="Old Team A"),
        path=str(store_path),
    )
    ingest_structured_facts_payload(
        structured_facts_payload("2026-06-01T11:00:00+00:00", home_team="New Team A"),
        path=str(store_path),
    )

    result = get_latest_structured_facts(
        match_id="M1",
        fact_key="fixtures",
        path=str(store_path),
    )

    assert result["status"] == "FOUND"
    assert result["factCount"] == 1
    assert result["latestSnapshotTime"] == "2026-06-01T11:00:00+00:00"
    assert result["facts"][0]["fact"]["homeTeam"] == "New Team A"
    assert result["facts"][0]["matchId"] == "M1"
    assert "payload" not in result["facts"][0]
    assert len(list_structured_fact_ingestions(path=str(store_path))) == 2


def test_structured_facts_read_model_snapshot_time_is_as_of_upper_bound(tmp_path):
    store_path = tmp_path / "structured_facts.sqlite3"
    ingest_structured_facts_payload(
        structured_facts_payload("2026-06-01T10:00:00+00:00", home_team="Old Team A"),
        path=str(store_path),
    )
    ingest_structured_facts_payload(
        structured_facts_payload("2026-06-01T11:00:00+00:00", home_team="New Team A"),
        path=str(store_path),
    )

    result = get_latest_structured_facts(
        match_id="M1",
        fact_key="fixtures",
        snapshot_time="2026-06-01T10:30:00+00:00",
        path=str(store_path),
    )

    assert result["status"] == "FOUND"
    assert result["asOfSnapshotTime"] == "2026-06-01T10:30:00+00:00"
    assert result["latestSnapshotTime"] == "2026-06-01T10:00:00+00:00"
    assert result["facts"][0]["fact"]["homeTeam"] == "Old Team A"


def test_structured_facts_read_model_returns_latest_per_fact_key(tmp_path):
    store_path = tmp_path / "structured_facts.sqlite3"
    ingest_structured_facts_payload(
        structured_facts_payload("2026-06-01T10:00:00+00:00", home_team="Old Team A", starters=["A1"]),
        path=str(store_path),
    )
    ingest_structured_facts_payload(
        structured_facts_payload("2026-06-01T11:00:00+00:00", home_team="New Team A", starters=["A9"]),
        path=str(store_path),
    )

    result = get_latest_structured_facts(match_id="M1", path=str(store_path))
    by_key = {item["factKey"]: item for item in result["facts"]}

    assert result["status"] == "FOUND"
    assert result["factCount"] == 2
    assert by_key["fixtures"]["snapshotTime"] == "2026-06-01T11:00:00+00:00"
    assert by_key["fixtures"]["fact"]["homeTeam"] == "New Team A"
    assert by_key["official_lineups"]["fact"]["homeStarters"] == ["A9"]


def test_structured_facts_read_model_rejects_naive_snapshot_time(tmp_path):
    store_path = tmp_path / "structured_facts.sqlite3"
    ingest_structured_facts_payload(valid_structured_facts_payload(), path=str(store_path))

    with pytest.raises(StructuredFactsReadModelError) as error:
        get_latest_structured_facts(
            match_id="M1",
            snapshot_time="2026-06-01T10:30:00",
            path=str(store_path),
        )

    assert error.value.code == "STRUCTURED_FACTS_READ_SNAPSHOT_TIME_INVALID"


def test_structured_facts_read_model_rejects_unknown_fact_key(tmp_path):
    store_path = tmp_path / "structured_facts.sqlite3"
    ingest_structured_facts_payload(valid_structured_facts_payload(), path=str(store_path))

    with pytest.raises(StructuredFactsReadModelError) as error:
        get_latest_structured_facts(fact_key="expected_lineup_evidence", path=str(store_path))

    assert error.value.code == "STRUCTURED_FACTS_READ_FACT_KEY_INVALID"
