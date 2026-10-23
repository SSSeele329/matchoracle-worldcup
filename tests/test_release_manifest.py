import json
import os
import tempfile

from app import app
from src.worldcup.release_manifest import (
    ReleaseManifestSchemaError,
    build_release_readiness_manifest,
    validate_release_readiness_manifest,
)


PROVIDER_ENV = {
    "MATCHORACLE_STRUCTURED_FACTS_PROVIDER": "contract_provider",
    "MATCHORACLE_STRUCTURED_FACTS_PROVIDER_CONFIGURED": "1",
    "MATCHORACLE_STRUCTURED_FACTS_API_BASE_URL": "https://provider.example/structured-facts",
    "MATCHORACLE_STRUCTURED_FACTS_PROVIDER_TOKEN": "provider-secret-token",
}
OPERATIONS_ENV = {
    "MATCHORACLE_JOB_FAILURE_ALERTS_CONFIGURED": "1",
    "MATCHORACLE_STALE_JOB_MONITOR_CONFIGURED": "1",
    "MATCHORACLE_QUEUE_BACKLOG_MONITOR_CONFIGURED": "1",
    "MATCHORACLE_STORE_BACKUP_POLICY_CONFIGURED": "1",
    "MATCHORACLE_STORE_MIGRATION_POLICY_CONFIGURED": "1",
}
ALL_ENV_KEYS = {
    "MATCHORACLE_APP_ENV",
    "MATCHORACLE_WORKER_TOKEN",
    "MATCHORACLE_WORKER_RUNTIME_CONFIGURED",
    "MATCHORACLE_SNAPSHOT_STORE",
    "MATCHORACLE_JOB_QUEUE_STORE",
    "MATCHORACLE_ODDS_STORE",
    "MATCHORACLE_STRUCTURED_FACTS_STORE",
    *PROVIDER_ENV.keys(),
    *OPERATIONS_ENV.keys(),
}


def clear_env():
    for key in ALL_ENV_KEYS:
        os.environ.pop(key, None)


def test_release_manifest_groups_checks_and_redacts_env_values():
    report = {
        "status": "BLOCKED",
        "environment": "production",
        "blockingChecks": ["workerAuth"],
        "warningChecks": [],
        "checks": [
            {
                "name": "workerAuth",
                "status": "FAIL",
                "message": "token missing",
                "tokenConfigured": False,
                "tokenValue": "secret-should-not-leak",
            },
            {
                "name": "predictionSnapshotStore",
                "status": "PASS",
                "env": "MATCHORACLE_SNAPSHOT_STORE",
                "configuredValue": "/private/tmp/secret.sqlite3",
            },
        ],
    }

    manifest = build_release_readiness_manifest(report)
    encoded = json.dumps(manifest)

    assert manifest["manifestVersion"] == "release-readiness-manifest-v1"
    assert manifest["readyForProduction"] is False
    assert manifest["statusCounts"] == {"PASS": 1, "WARN": 0, "FAIL": 1}
    assert manifest["checkGroups"]["CORE_RUNTIME"] == ["workerAuth"]
    assert manifest["checkGroups"]["CORE_STORAGE"] == ["predictionSnapshotStore"]
    assert manifest["environmentVariables"] == [{
        "name": "MATCHORACLE_SNAPSHOT_STORE",
        "check": "predictionSnapshotStore",
        "status": "PASS",
        "category": "CORE_STORAGE",
        "value": "REDACTED",
    }]
    assert "secret-should-not-leak" not in encoded
    assert "/private/tmp/secret.sqlite3" not in encoded


def test_readiness_response_includes_release_manifest_without_secret_values():
    with tempfile.TemporaryDirectory() as tmp_dir:
        clear_env()
        os.environ["MATCHORACLE_APP_ENV"] = "production"
        os.environ["MATCHORACLE_WORKER_TOKEN"] = "super-secret-token"
        os.environ["MATCHORACLE_WORKER_RUNTIME_CONFIGURED"] = "1"
        os.environ["MATCHORACLE_SNAPSHOT_STORE"] = os.path.join(tmp_dir, "prediction_snapshots.sqlite3")
        os.environ["MATCHORACLE_JOB_QUEUE_STORE"] = os.path.join(tmp_dir, "background_jobs.sqlite3")
        os.environ["MATCHORACLE_ODDS_STORE"] = os.path.join(tmp_dir, "market_odds.sqlite3")
        os.environ["MATCHORACLE_STRUCTURED_FACTS_STORE"] = os.path.join(tmp_dir, "structured_facts.sqlite3")
        for key, value in {**PROVIDER_ENV, **OPERATIONS_ENV}.items():
            os.environ[key] = value
        try:
            response = app.test_client().get("/api/readiness")
            payload = response.get_json()
            manifest = payload["releaseReadinessManifest"]
            encoded = json.dumps(payload)

            assert response.status_code == 200
            assert manifest["readyForProduction"] is True
            assert manifest["readinessStatus"] == "READY"
            assert "super-secret-token" not in encoded
            assert "provider-secret-token" not in encoded
            assert "provider.example" not in encoded
            assert tmp_dir not in encoded
            assert any(item["name"] == "MATCHORACLE_WORKER_RUNTIME_CONFIGURED" for item in manifest["environmentVariables"])
            assert all(item["value"] == "REDACTED" for item in manifest["environmentVariables"])
        finally:
            clear_env()


def test_local_demo_readiness_includes_manifest_with_warning_summary():
    clear_env()
    try:
        response = app.test_client().get("/api/readiness")
        payload = response.get_json()
        manifest = payload["releaseReadinessManifest"]

        assert response.status_code == 200
        assert payload["status"] == "DEMO_READY"
        assert manifest["manifestVersion"] == "release-readiness-manifest-v1"
        assert manifest["readyForProduction"] is False
        assert manifest["statusCounts"]["WARN"] > 0
        assert "CORE_RUNTIME" in manifest["checkGroups"]
        assert "CORE_STORAGE" in manifest["checkGroups"]
    finally:
        clear_env()


def test_predict_endpoint_still_uses_default_model_after_manifest_integration():
    clear_env()
    response = app.test_client().post("/api/predict", json={
        "matchId": "manifest-smoke-test",
        "match": {
            "homeTeam": "A",
            "awayTeam": "B",
            "stage": "GROUP_STAGE",
            "datetime": "2026-06-01T20:00:00+00:00",
        },
        "teamData": {
            "home": {"fifaRank": 10},
            "away": {"fifaRank": 20},
        },
    })
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["modelVersion"] == "V4-P0"
    assert payload["canonicalProbability"]["status"] in {"ACTIVE", "ABORTED"}
    assert "releaseReadinessManifest" not in payload


def test_release_manifest_schema_validation_accepts_valid_manifest():
    manifest = build_release_readiness_manifest({
        "status": "READY",
        "environment": "production",
        "blockingChecks": [],
        "warningChecks": [],
        "checks": [{"name": "workerAuth", "status": "PASS"}],
    })

    validation = validate_release_readiness_manifest(manifest)

    assert validation["status"] == "PASS"
    assert validation["manifestVersion"] == "release-readiness-manifest-v1"


def test_release_manifest_schema_validation_rejects_missing_required_field():
    manifest = build_release_readiness_manifest({
        "status": "READY",
        "environment": "production",
        "blockingChecks": [],
        "warningChecks": [],
        "checks": [],
    })
    manifest.pop("statusCounts")

    try:
        validate_release_readiness_manifest(manifest)
        assert False, "schema validation should fail"
    except ReleaseManifestSchemaError as error:
        assert "statusCounts is required." in error.errors


def test_release_manifest_schema_validation_rejects_non_redacted_env_value():
    manifest = build_release_readiness_manifest({
        "status": "READY",
        "environment": "production",
        "blockingChecks": [],
        "warningChecks": [],
        "checks": [{
            "name": "predictionSnapshotStore",
            "status": "PASS",
            "env": "MATCHORACLE_SNAPSHOT_STORE",
        }],
    })
    manifest["environmentVariables"][0]["value"] = "/private/tmp/secret.sqlite3"

    try:
        validate_release_readiness_manifest(manifest)
        assert False, "schema validation should fail"
    except ReleaseManifestSchemaError as error:
        assert "environmentVariables[0].value must be REDACTED." in error.errors
        assert "/private/tmp/secret.sqlite3" not in str(error)
