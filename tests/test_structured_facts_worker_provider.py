from pathlib import Path

import app as app_module


def football_data_payload():
    return {
        "provider": {"providerId": "football_data_org"},
        "source": "football-data.org",
        "snapshotTime": "2026-06-13T00:00:00+00:00",
        "facts": {
            "fixtures": [{"matchId": "football-data-org:1"}],
            "kickoff_time": [{"matchId": "football-data-org:1"}],
            "match_status": [{"matchId": "football-data-org:1"}],
            "official_lineups": [],
            "scores": [],
            "standings": [],
            "cards": [],
            "market_odds_snapshots": [],
        },
    }


def test_structured_facts_worker_uses_football_data_org_adapter(monkeypatch):
    calls = {}

    def fake_fetch(**kwargs):
        calls.update(kwargs)
        return football_data_payload()

    monkeypatch.setenv("MATCHORACLE_STRUCTURED_FACTS_PROVIDER", "football_data_org")
    monkeypatch.setenv("MATCHORACLE_STRUCTURED_FACTS_PROVIDER_TOKEN", "provider-token")
    monkeypatch.setattr(app_module, "fetch_worldcup_structured_facts_payload", fake_fetch)

    result = app_module.run_structured_facts_sync_background_job({
        "payload": {
            "matchId": "football-data-org:1",
            "snapshotTime": "2026-06-13T00:00:00+00:00",
            "dryRun": True,
        }
    })

    assert result["status"] == "VALIDATED"
    assert result["providerId"] == "football_data_org"
    assert result["factCounts"]["fixtures"] == 1
    assert calls["token"] == "provider-token"
    assert calls["match_id"] == "football-data-org:1"


def test_structured_facts_worker_ingests_football_data_org_payload(monkeypatch):
    ingested = {}

    def fake_fetch(**kwargs):
        return football_data_payload()

    def fake_ingest(payload, created_by=None):
        ingested["payload"] = payload
        ingested["created_by"] = created_by
        return {"storageOperation": "INSERTED"}

    monkeypatch.setenv("MATCHORACLE_STRUCTURED_FACTS_PROVIDER", "football_data_org")
    monkeypatch.setenv("MATCHORACLE_STRUCTURED_FACTS_PROVIDER_TOKEN", "provider-token")
    monkeypatch.setattr(app_module, "fetch_worldcup_structured_facts_payload", fake_fetch)
    monkeypatch.setattr(app_module, "ingest_structured_facts_payload", fake_ingest)

    result = app_module.run_structured_facts_sync_background_job({"payload": {"dryRun": False}})

    assert result["status"] == "INGESTED"
    assert result["ingestion"]["storageOperation"] == "INSERTED"
    assert ingested["payload"]["source"] == "football-data.org"
    assert ingested["created_by"] == "background_football_data_org_sync"


def test_local_internal_env_example_is_non_secret_and_provider_ready():
    path = Path(__file__).resolve().parents[1] / "deploy" / "local.internal.env.example"
    text = path.read_text(encoding="utf-8")

    assert "MATCHORACLE_STRUCTURED_FACTS_PROVIDER=football_data_org" in text
    assert "MATCHORACLE_WORKER_RUNTIME_CONFIGURED=1" in text
    assert "MATCHORACLE_JOB_FAILURE_ALERTS_CONFIGURED=1" in text
    assert "MATCHORACLE_STRUCTURED_FACTS_PROVIDER_TOKEN=\n" in text
    assert "api_key" not in text.lower()
    assert "password" not in text.lower()
