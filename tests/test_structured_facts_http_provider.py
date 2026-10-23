import io
import json
import urllib.error

import pytest

from scripts.fetch_structured_facts_payload import run_structured_facts_fetch
from src.worldcup.provider_contracts import STRUCTURED_FACTS_CATEGORY
from src.worldcup.structured_facts_http_provider import (
    StructuredFactsHttpProviderError,
    fetch_structured_facts_payload,
    fetch_validate_and_optionally_ingest_structured_facts,
)
from src.worldcup.structured_facts_store import list_structured_fact_ingestions


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        if isinstance(self.payload, bytes):
            return self.payload
        return json.dumps(self.payload).encode("utf-8")


def valid_payload():
    return {
        "provider": {
            "category": STRUCTURED_FACTS_CATEGORY,
            "providerId": "contract-http-provider",
        },
        "source": "contract-http-provider",
        "snapshotTime": "2026-06-01T12:00:00+00:00",
        "auditContext": {"requestId": "unit-test"},
        "facts": {
            "fixtures": [{
                "matchId": "M1",
                "homeTeam": "Team A",
                "awayTeam": "Team B",
            }],
            "official_lineups": [],
        },
    }


def test_http_provider_requires_token():
    with pytest.raises(StructuredFactsHttpProviderError) as error:
        fetch_structured_facts_payload(
            base_url="https://provider.example/structured-facts",
            token="",
        )

    assert error.value.code == "STRUCTURED_FACTS_PROVIDER_TOKEN_MISSING"
    assert error.value.details["endpoint"] == "https://provider.example/structured-facts"


def test_http_provider_fetches_with_bearer_token_and_query_params():
    calls = []

    def opener(request, timeout=20):
        calls.append((request, timeout))
        return FakeResponse(valid_payload())

    payload = fetch_structured_facts_payload(
        base_url="https://provider.example/structured-facts?league=worldcup",
        token="secret-token",
        match_id="M1",
        snapshot_time="2026-06-01T12:00:00+00:00",
        timeout=7,
        opener=opener,
    )

    request, timeout = calls[0]
    assert payload["source"] == "contract-http-provider"
    assert timeout == 7
    assert request.headers["Authorization"] == "Bearer secret-token"
    assert "league=worldcup" in request.full_url
    assert "matchId=M1" in request.full_url
    assert "snapshotTime=2026-06-01T12%3A00%3A00%2B00%3A00" in request.full_url


def test_http_provider_rejects_invalid_json_without_token_leak():
    def opener(request, timeout=20):
        return FakeResponse(b"{not-json")

    with pytest.raises(StructuredFactsHttpProviderError) as error:
        fetch_structured_facts_payload(
            base_url="https://provider.example/structured-facts?token=secret-in-url",
            token="secret-token",
            opener=opener,
        )

    assert error.value.code == "STRUCTURED_FACTS_PROVIDER_JSON_INVALID"
    assert "secret-token" not in str(error.value.details)
    assert "secret-in-url" not in str(error.value.details)
    assert error.value.details["endpoint"] == "https://provider.example/structured-facts"


def test_http_provider_http_error_is_redacted():
    def opener(request, timeout=20):
        raise urllib.error.HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b"secret-token"),
        )

    with pytest.raises(StructuredFactsHttpProviderError) as error:
        fetch_structured_facts_payload(
            base_url="https://provider.example/structured-facts",
            token="secret-token",
            opener=opener,
        )

    assert error.value.code == "STRUCTURED_FACTS_PROVIDER_HTTP_ERROR"
    assert error.value.details["status"] == 401
    assert "secret-token" not in str(error.value.details)


def test_fetch_dry_run_validates_without_ingesting(tmp_path):
    store_path = tmp_path / "structured_facts.sqlite3"

    def opener(request, timeout=20):
        return FakeResponse(valid_payload())

    result = fetch_validate_and_optionally_ingest_structured_facts(
        base_url="https://provider.example/structured-facts",
        token="secret-token",
        dry_run=True,
        store_path=str(store_path),
        opener=opener,
    )

    assert result["status"] == "VALIDATED"
    assert result["factKeys"] == ["fixtures", "official_lineups"]
    assert not store_path.exists()


def test_fetch_ingests_valid_payload(tmp_path):
    store_path = tmp_path / "structured_facts.sqlite3"

    def opener(request, timeout=20):
        return FakeResponse(valid_payload())

    result = fetch_validate_and_optionally_ingest_structured_facts(
        base_url="https://provider.example/structured-facts",
        token="secret-token",
        store_path=str(store_path),
        opener=opener,
    )

    assert result["status"] == "INGESTED"
    assert result["ingestion"]["storageOperation"] == "INSERTED"
    assert len(list_structured_fact_ingestions(path=str(store_path))) == 1


def test_fetch_cli_dry_run_outputs_validation_without_store(monkeypatch, tmp_path):
    store_path = tmp_path / "structured_facts.sqlite3"

    def fake_fetch(**kwargs):
        return {
            "status": "VALIDATED",
            "source": "contract-http-provider",
            "snapshotTime": "2026-06-01T12:00:00+00:00",
            "validation": {"status": "PASS"},
            "factKeys": ["fixtures"],
        }

    monkeypatch.setattr(
        "scripts.fetch_structured_facts_payload.fetch_validate_and_optionally_ingest_structured_facts",
        fake_fetch,
    )
    events = []
    errors = []

    exit_code = run_structured_facts_fetch(
        url="https://provider.example/structured-facts",
        token="secret-token",
        store_path=str(store_path),
        dry_run=True,
        emit=events.append,
        error=errors.append,
    )

    payload = json.loads(events[0])
    assert exit_code == 0
    assert errors == []
    assert payload["status"] == "VALIDATED"
    assert not store_path.exists()


def test_fetch_cli_error_is_redacted(monkeypatch):
    def fake_fetch(**kwargs):
        raise StructuredFactsHttpProviderError(
            "STRUCTURED_FACTS_PROVIDER_HTTP_ERROR",
            "Structured facts provider returned an HTTP error.",
            details={"status": 401, "endpoint": "https://provider.example/structured-facts"},
        )

    monkeypatch.setattr(
        "scripts.fetch_structured_facts_payload.fetch_validate_and_optionally_ingest_structured_facts",
        fake_fetch,
    )
    events = []
    errors = []

    exit_code = run_structured_facts_fetch(
        url="https://provider.example/structured-facts",
        token="secret-token",
        emit=events.append,
        error=errors.append,
    )

    payload = json.loads(errors[0])
    assert exit_code == 2
    assert events == []
    assert payload["event"] == "STRUCTURED_FACTS_PROVIDER_FETCH_REJECTED"
    assert "secret-token" not in errors[0]
