from pathlib import Path

from src.worldcup.readiness import build_readiness_report


ENV_EXAMPLE_PATH = Path(__file__).resolve().parents[1] / "deploy" / "production.env.example"

REQUIRED_PRODUCTION_ENV_KEYS = {
    "MATCHORACLE_APP_ENV",
    "MATCHORACLE_WORKER_TOKEN",
    "MATCHORACLE_WORKER_RUNTIME_CONFIGURED",
    "MATCHORACLE_SNAPSHOT_STORE",
    "MATCHORACLE_JOB_QUEUE_STORE",
    "MATCHORACLE_ODDS_STORE",
    "MATCHORACLE_STRUCTURED_FACTS_STORE",
    "MATCHORACLE_STRUCTURED_FACTS_PROVIDER",
    "MATCHORACLE_STRUCTURED_FACTS_PROVIDER_CONFIGURED",
    "MATCHORACLE_STRUCTURED_FACTS_API_BASE_URL",
    "MATCHORACLE_STRUCTURED_FACTS_PROVIDER_TOKEN",
    "MATCHORACLE_AI_EVIDENCE_PROVIDER",
    "MATCHORACLE_AI_EVIDENCE_POLICY",
    "MATCHORACLE_AI_ALLOW_FACT_GENERATION",
    "MATCHORACLE_CSV_FALLBACK_ENABLED",
    "MATCHORACLE_ODDS_API_BASE_URL",
    "MATCHORACLE_ODDS_PROVIDER_TOKEN",
    "MATCHORACLE_JOB_FAILURE_ALERTS_CONFIGURED",
    "MATCHORACLE_STALE_JOB_MONITOR_CONFIGURED",
    "MATCHORACLE_QUEUE_BACKLOG_MONITOR_CONFIGURED",
    "MATCHORACLE_STORE_BACKUP_POLICY_CONFIGURED",
    "MATCHORACLE_STORE_MIGRATION_POLICY_CONFIGURED",
}


def parse_env_example(path=ENV_EXAMPLE_PATH):
    values = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def test_production_env_example_contains_required_release_readiness_keys():
    values = parse_env_example()

    assert REQUIRED_PRODUCTION_ENV_KEYS <= set(values)
    assert values["MATCHORACLE_APP_ENV"] == "production"
    assert values["MATCHORACLE_AI_EVIDENCE_POLICY"] == "EVIDENCE_EXTRACTION_ONLY"
    assert values["MATCHORACLE_AI_ALLOW_FACT_GENERATION"] == "0"


def test_production_env_example_is_not_accidentally_ready_as_is():
    values = parse_env_example()

    report = build_readiness_report(environ=values)

    assert report["status"] == "BLOCKED"
    assert "workerAuth" in report["blockingChecks"]
    assert "workerRuntime" in report["blockingChecks"]
    assert "structuredFactsProvider" in report["blockingChecks"]
    assert "structuredFactsStore" in report["blockingChecks"]
    assert values["MATCHORACLE_WORKER_TOKEN"] == ""
    assert values["MATCHORACLE_STRUCTURED_FACTS_PROVIDER"] == ""


def test_production_env_example_does_not_include_real_secret_values():
    encoded = ENV_EXAMPLE_PATH.read_text(encoding="utf-8")

    assert "super-secret" not in encoded
    assert "do-not-print" not in encoded
    assert "api_key" not in encoded.lower()
    assert "password" not in encoded.lower()
