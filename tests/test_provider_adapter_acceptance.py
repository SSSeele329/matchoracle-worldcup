import json
from pathlib import Path

import pytest

from scripts.validate_provider_adapter_fixture import run_adapter_fixture_validation
from src.worldcup.provider_adapter_acceptance import (
    ProviderAdapterAcceptanceError,
    find_inline_raw_payload_paths,
    find_sensitive_field_paths,
    validate_provider_adapter_output,
)
from src.worldcup.provider_contracts import STRUCTURED_FACTS_CATEGORY


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ADAPTER_TEMPLATE_PATH = (
    PROJECT_ROOT
    / "data"
    / "structured_facts"
    / "provider_adapter_fixture_template.json"
)


def adapter_payload():
    return {
        "provider": {
            "providerId": "adapter-fixture-provider",
            "category": STRUCTURED_FACTS_CATEGORY,
            "mode": "adapter_fixture",
            "productionReady": False,
        },
        "source": "adapter-fixture-provider",
        "snapshotTime": "2026-06-01T12:00:00+00:00",
        "rawPayloadHash": "sha256:fixture-hash",
        "facts": {
            "fixtures": [{
                "matchId": "M1",
                "homeTeam": "Team A",
                "awayTeam": "Team B",
            }],
            "official_lineups": [{
                "matchId": "M1",
                "homeStarters": ["A1"],
                "awayStarters": ["B1"],
            }],
        },
    }


def test_provider_adapter_acceptance_passes_contract_fixture():
    result = validate_provider_adapter_output(
        adapter_payload(),
        expected_provider_id="adapter-fixture-provider",
        required_fact_keys=["fixtures", "official_lineups"],
    )

    assert result["status"] == "PASS"
    assert result["providerId"] == "adapter-fixture-provider"
    assert result["factCounts"] == {"fixtures": 1, "official_lineups": 1}


def test_provider_adapter_acceptance_rejects_wrong_provider_id():
    with pytest.raises(ProviderAdapterAcceptanceError) as error:
        validate_provider_adapter_output(
            adapter_payload(),
            expected_provider_id="other-provider",
        )

    assert error.value.code == "PROVIDER_ADAPTER_ACCEPTANCE_FAILED"
    assert "provider.providerId must match expected provider id" in error.value.details["errors"][0]


def test_provider_adapter_acceptance_rejects_missing_required_bucket():
    payload = adapter_payload()
    payload["facts"].pop("official_lineups")

    with pytest.raises(ProviderAdapterAcceptanceError) as error:
        validate_provider_adapter_output(
            payload,
            expected_provider_id="adapter-fixture-provider",
            required_fact_keys=["fixtures", "official_lineups"],
        )

    assert "facts.official_lineups is required for this adapter acceptance run." in error.value.details["errors"]


def test_provider_adapter_acceptance_rejects_empty_required_bucket_by_default():
    payload = adapter_payload()
    payload["facts"]["official_lineups"] = []

    with pytest.raises(ProviderAdapterAcceptanceError) as error:
        validate_provider_adapter_output(
            payload,
            required_fact_keys=["official_lineups"],
        )

    assert "facts.official_lineups must not be empty for this adapter acceptance run." in error.value.details["errors"]


def test_provider_adapter_acceptance_can_allow_empty_required_bucket_when_explicit():
    payload = adapter_payload()
    payload["facts"]["official_lineups"] = []

    result = validate_provider_adapter_output(
        payload,
        required_fact_keys=["official_lineups"],
        allow_empty_required_buckets=True,
    )

    assert result["status"] == "PASS"
    assert result["factCounts"]["official_lineups"] == 0


def test_provider_adapter_acceptance_rejects_sensitive_fields_and_inline_raw_payload():
    payload = adapter_payload()
    payload["auditContext"] = {
        "adapterVersion": "unit",
        "apiToken": "secret-token",
        "rawPayload": {"vendor": "body"},
    }

    with pytest.raises(ProviderAdapterAcceptanceError) as error:
        validate_provider_adapter_output(payload)

    assert "adapter output must not include token, secret, authorization, password, or API key fields." in error.value.details["errors"]
    assert "adapter output must not inline raw vendor payloads; use rawPayloadHash/rawPayloadRef/auditContext instead." in error.value.details["errors"]
    assert error.value.details["sensitiveFieldPaths"] == ["auditContext.apiToken"]
    assert error.value.details["inlineRawPayloadPaths"] == ["auditContext.rawPayload"]


def test_provider_adapter_acceptance_path_helpers():
    payload = {"headers": {"authorization": "Bearer secret"}, "vendorPayload": {"ok": True}}

    assert find_sensitive_field_paths(payload) == ["headers.authorization"]
    assert find_inline_raw_payload_paths(payload) == ["vendorPayload"]


def test_provider_adapter_cli_accepts_fixture(tmp_path):
    fixture_path = tmp_path / "adapter_output.json"
    fixture_path.write_text(json.dumps(adapter_payload()), encoding="utf-8")
    events = []
    errors = []

    exit_code = run_adapter_fixture_validation(
        str(fixture_path),
        expected_provider_id="adapter-fixture-provider",
        required_fact_keys=["fixtures"],
        emit=events.append,
        error=errors.append,
    )

    payload = json.loads(events[0])
    assert exit_code == 0
    assert errors == []
    assert payload["status"] == "PASS"


def test_provider_adapter_cli_rejects_fixture_without_leaking_values(tmp_path):
    payload = adapter_payload()
    payload["auditContext"] = {"secretToken": "super-secret"}
    fixture_path = tmp_path / "adapter_output.json"
    fixture_path.write_text(json.dumps(payload), encoding="utf-8")
    events = []
    errors = []

    exit_code = run_adapter_fixture_validation(
        str(fixture_path),
        emit=events.append,
        error=errors.append,
    )

    assert exit_code == 2
    assert events == []
    assert "PROVIDER_ADAPTER_ACCEPTANCE_REJECTED" in errors[0]
    assert "super-secret" not in errors[0]


def test_provider_adapter_fixture_template_is_acceptance_ready():
    with ADAPTER_TEMPLATE_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    result = validate_provider_adapter_output(
        payload,
        expected_provider_id="template_structured_facts_adapter",
        required_fact_keys=["fixtures", "official_lineups"],
    )
    events = []
    errors = []
    exit_code = run_adapter_fixture_validation(
        str(ADAPTER_TEMPLATE_PATH),
        expected_provider_id="template_structured_facts_adapter",
        required_fact_keys=["fixtures", "official_lineups"],
        emit=events.append,
        error=errors.append,
    )

    assert find_sensitive_field_paths(payload) == []
    assert find_inline_raw_payload_paths(payload) == []
    assert result["status"] == "PASS"
    assert result["factCounts"]["fixtures"] == 1
    assert result["factCounts"]["official_lineups"] == 1
    assert exit_code == 0
    assert errors == []
    assert json.loads(events[0])["status"] == "PASS"
