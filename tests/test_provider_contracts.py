import pytest

from src.worldcup.provider_contracts import (
    AI_EVIDENCE_CATEGORY,
    CSV_MANUAL_FALLBACK_CATEGORY,
    STRUCTURED_FACTS_CATEGORY,
    MockAIEvidenceExtractionProvider,
    MockStructuredFactDataProvider,
    ProviderContractError,
    StructuredFactsPayloadError,
    build_provider_contract_readiness_checks,
    validate_ai_evidence_payload,
    validate_structured_facts_payload,
)


def test_provider_contracts_distinguish_fact_ai_and_csv_sources():
    checks = build_provider_contract_readiness_checks(production=False, environ={})
    by_name = {check["name"]: check for check in checks}

    assert by_name["structuredFactsProvider"]["category"] == STRUCTURED_FACTS_CATEGORY
    assert by_name["structuredFactsProvider"]["status"] == "WARN"
    assert by_name["aiEvidenceProvider"]["category"] == AI_EVIDENCE_CATEGORY
    assert by_name["aiEvidenceProvider"]["status"] == "PASS"
    assert by_name["csvManualFallback"]["category"] == CSV_MANUAL_FALLBACK_CATEGORY
    assert by_name["csvManualFallback"]["status"] == "PASS"


def test_production_readiness_rejects_mock_structured_facts_provider():
    checks = build_provider_contract_readiness_checks(
        production=True,
        environ={
            "MATCHORACLE_STRUCTURED_FACTS_PROVIDER": "mock",
            "MATCHORACLE_STRUCTURED_FACTS_PROVIDER_CONFIGURED": "1",
        },
    )
    structured = next(check for check in checks if check["name"] == "structuredFactsProvider")

    assert structured["status"] == "FAIL"
    assert structured["category"] == STRUCTURED_FACTS_CATEGORY


def test_production_readiness_requires_http_provider_url_and_token():
    checks = build_provider_contract_readiness_checks(
        production=True,
        environ={
            "MATCHORACLE_STRUCTURED_FACTS_PROVIDER": "contract_provider",
            "MATCHORACLE_STRUCTURED_FACTS_PROVIDER_CONFIGURED": "1",
            "MATCHORACLE_AI_EVIDENCE_PROVIDER": "disabled",
        },
    )
    structured = next(check for check in checks if check["name"] == "structuredFactsProvider")

    assert structured["status"] == "FAIL"
    assert structured["apiBaseUrlConfigured"] is False
    assert structured["tokenConfigured"] is False
    assert "MATCHORACLE_STRUCTURED_FACTS_API_BASE_URL" in structured["missingEnv"]
    assert "MATCHORACLE_STRUCTURED_FACTS_PROVIDER_TOKEN" in structured["missingEnv"]


def test_local_readiness_warns_when_real_provider_credentials_are_missing():
    checks = build_provider_contract_readiness_checks(
        production=False,
        environ={
            "MATCHORACLE_STRUCTURED_FACTS_PROVIDER": "football_data_org",
            "MATCHORACLE_STRUCTURED_FACTS_PROVIDER_CONFIGURED": "1",
            "MATCHORACLE_STRUCTURED_FACTS_API_BASE_URL": "https://api.football-data.org/v4",
        },
    )
    structured = next(check for check in checks if check["name"] == "structuredFactsProvider")

    assert structured["status"] == "WARN"
    assert structured["provider"] == "football_data_org"
    assert structured["tokenConfigured"] is False
    assert "MATCHORACLE_STRUCTURED_FACTS_PROVIDER_TOKEN" in structured["missingEnv"]


def test_production_readiness_accepts_explicit_provider_contract_with_http_credentials():
    checks = build_provider_contract_readiness_checks(
        production=True,
        environ={
            "MATCHORACLE_STRUCTURED_FACTS_PROVIDER": "contract_provider",
            "MATCHORACLE_STRUCTURED_FACTS_PROVIDER_CONFIGURED": "1",
            "MATCHORACLE_STRUCTURED_FACTS_API_BASE_URL": "https://provider.example/structured-facts",
            "MATCHORACLE_STRUCTURED_FACTS_PROVIDER_TOKEN": "secret-provider-token",
            "MATCHORACLE_AI_EVIDENCE_PROVIDER": "disabled",
        },
    )
    by_name = {check["name"]: check for check in checks}

    assert by_name["structuredFactsProvider"]["status"] == "PASS"
    assert by_name["aiEvidenceProvider"]["status"] == "PASS"
    assert by_name["providerContractPolicy"]["status"] == "PASS"


def test_ai_evidence_payload_rejects_direct_fact_outputs():
    with pytest.raises(ProviderContractError) as error:
        validate_ai_evidence_payload({
            "expectedLineupEvidence": {
                "players": [{"player": "A", "expectedRole": "STARTER"}],
            },
            "officialLineup": {"homeStarters": ["A"]},
            "oddsProbabilities": {"home": 0.5, "draw": 0.25, "away": 0.25},
        })

    assert error.value.code == "AI_FACT_OUTPUT_FORBIDDEN"
    assert "officialLineup" in error.value.details["forbiddenPaths"]
    assert "oddsProbabilities" in error.value.details["forbiddenPaths"]


def test_ai_evidence_payload_allows_evidence_fields_only():
    validation = validate_ai_evidence_payload({
        "expectedLineupEvidence": {
            "players": [{
                "player": "A",
                "teamSide": "home",
                "expectedRole": "STARTER",
                "trainedWithTeam": "FULL",
                "sources": [{"source": "training-report", "publishedAt": "2026-06-01T10:00:00+00:00"}],
            }],
        },
        "narrativeEvidence": [{"source": "coach-quote", "summary": "Player trained fully."}],
    })

    assert validation["status"] == "PASS"


def test_mock_providers_expose_contract_metadata_without_facts():
    facts = MockStructuredFactDataProvider().fetch_structured_facts("M1")
    ai = MockAIEvidenceExtractionProvider().extract_evidence(
        ["source text"],
        context={"mockEvidence": {"narrativeEvidence": [{"summary": "training note"}]}},
    )

    assert facts["status"] == "MOCK_ONLY"
    assert facts["facts"] == {}
    assert facts["provider"]["productionReady"] is False
    assert ai["provider"]["category"] == AI_EVIDENCE_CATEGORY


def test_structured_facts_payload_accepts_allowed_fact_keys_with_audit_metadata():
    validation = validate_structured_facts_payload({
        "source": "contract-test-feed",
        "snapshotTime": "2026-06-01T10:00:00+00:00",
        "rawPayloadHash": "sha256:abc123",
        "provider": {
            "category": STRUCTURED_FACTS_CATEGORY,
            "providerId": "contract_provider",
        },
        "facts": {
            "fixtures": [{"matchId": "M1"}],
            "official_lineups": [{"matchId": "M1", "homeStarters": ["A"]}],
            "scores": [],
            "standings": [],
            "cards": [],
            "market_odds_snapshots": [],
        },
    })

    assert validation["status"] == "PASS"
    assert validation["category"] == STRUCTURED_FACTS_CATEGORY


def test_structured_facts_payload_rejects_missing_timestamp_and_audit_context():
    with pytest.raises(StructuredFactsPayloadError) as error:
        validate_structured_facts_payload({
            "source": "contract-test-feed",
            "facts": {"fixtures": []},
        })

    assert error.value.code == "STRUCTURED_FACTS_PAYLOAD_INVALID"
    assert "snapshotTime or snapshot_time is required." in error.value.details["errors"]
    assert "rawPayloadRef, rawPayloadHash, or auditContext is required." in error.value.details["errors"]


def test_structured_facts_payload_rejects_naive_snapshot_time():
    with pytest.raises(StructuredFactsPayloadError) as error:
        validate_structured_facts_payload({
            "source": "contract-test-feed",
            "snapshotTime": "2026-06-01T10:00:00",
            "auditContext": {"requestId": "local-test"},
            "facts": {"fixtures": []},
        })

    assert "snapshotTime or snapshot_time must be a timezone-aware ISO timestamp." in error.value.details["errors"]


def test_structured_facts_payload_rejects_ai_evidence_as_fact_key():
    with pytest.raises(StructuredFactsPayloadError) as error:
        validate_structured_facts_payload({
            "source": "contract-test-feed",
            "snapshotTime": "2026-06-01T10:00:00+00:00",
            "auditContext": {"requestId": "local-test"},
            "facts": {
                "expected_lineup_evidence": [{"player": "A"}],
            },
        })

    assert "facts.expected_lineup_evidence is not an allowed structured fact key." in error.value.details["errors"]


def test_structured_facts_payload_rejects_csv_fallback_provider_category():
    with pytest.raises(StructuredFactsPayloadError) as error:
        validate_structured_facts_payload({
            "source": "csv-import",
            "snapshotTime": "2026-06-01T10:00:00+00:00",
            "rawPayloadRef": "local-csv",
            "provider": {"category": CSV_MANUAL_FALLBACK_CATEGORY},
            "facts": {"market_odds_snapshots": []},
        })

    assert "provider.category must be STRUCTURED_FACT_DATA_SOURCE." in error.value.details["errors"]


def test_structured_facts_payload_accepts_snapshot_time_alias():
    validation = validate_structured_facts_payload({
        "source": "contract-test-feed",
        "snapshot_time": "2026-06-01T10:00:00Z",
        "raw_payload_or_audit_context": {"requestId": "local-test"},
        "facts": {"fixtures": []},
    })

    assert validation["status"] == "PASS"


def test_mock_structured_facts_provider_payload_passes_contract_validation():
    payload = MockStructuredFactDataProvider().fetch_structured_facts("M1")

    validation = validate_structured_facts_payload(payload)

    assert validation["status"] == "PASS"
    assert payload["status"] == "MOCK_ONLY"
