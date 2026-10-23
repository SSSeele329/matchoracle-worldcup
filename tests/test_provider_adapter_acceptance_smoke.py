import json
from pathlib import Path

from scripts.smoke_provider_adapter_acceptance import (
    run_provider_adapter_acceptance_smoke,
    validate_smoke_summary,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_provider_adapter_acceptance_smoke_passes_builtin_fixtures():
    events = []
    errors = []

    exit_code = run_provider_adapter_acceptance_smoke(
        emit=events.append,
        error=errors.append,
    )

    payload = json.loads(events[0])
    assert exit_code == 0
    assert errors == []
    assert payload["event"] == "PROVIDER_ADAPTER_ACCEPTANCE_SMOKE"
    assert payload["status"] == "PASS"
    assert payload["checked"] == 2
    assert payload["failed"] == 0
    assert {check["name"] for check in payload["checks"]} == {
        "provider_adapter_fixture_template",
        "demo_structured_facts_fixture",
    }


def test_provider_adapter_acceptance_smoke_writes_report(tmp_path):
    report_path = tmp_path / "reports" / "provider_adapter_acceptance_smoke.json"
    events = []
    errors = []

    exit_code = run_provider_adapter_acceptance_smoke(
        write_report_path=str(report_path),
        emit=events.append,
        error=errors.append,
    )

    output_payload = json.loads(events[0])
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert errors == []
    assert report_payload == output_payload
    assert report_payload["status"] == "PASS"


def test_provider_adapter_acceptance_smoke_summary_schema_guard_rejects_broken_shape():
    result = validate_smoke_summary({
        "event": "PROVIDER_ADAPTER_ACCEPTANCE_SMOKE",
        "status": "PASS",
        "checked": 2,
        "failed": 0,
        "checks": [{
            "name": "fixture",
            "fixture": "fixture.json",
            "expectedProviderId": "provider",
            "requiredFactKeys": ["fixtures"],
            "status": "FAIL",
            "error": {"message": "bad fixture"},
        }],
    })

    assert result["status"] == "FAIL"
    assert "checked must equal len(checks)." in result["errors"]
    assert "failed must equal number of failed checks." in result["errors"]
    assert "PASS summary cannot contain failed checks." in result["errors"]


def test_provider_adapter_acceptance_smoke_reports_failure_without_leaking_values(tmp_path):
    fixture_path = tmp_path / "bad_adapter_fixture.json"
    fixture_path.write_text(
        json.dumps({
            "provider": {
                "providerId": "bad-fixture",
                "category": "STRUCTURED_FACT_DATA_SOURCE",
            },
            "source": "bad-fixture",
            "snapshotTime": "2026-06-01T12:00:00+00:00",
            "auditContext": {"secretToken": "do-not-print"},
            "facts": {"fixtures": []},
        }),
        encoding="utf-8",
    )
    events = []
    errors = []

    exit_code = run_provider_adapter_acceptance_smoke(
        fixtures=[{
            "name": "bad_fixture",
            "fixture": str(fixture_path),
            "expectedProviderId": "bad-fixture",
            "requiredFactKeys": ["fixtures", "official_lineups"],
        }],
        emit=events.append,
        error=errors.append,
    )

    payload = json.loads(errors[0])
    assert exit_code == 2
    assert events == []
    assert payload["status"] == "FAIL"
    assert payload["checked"] == 1
    assert payload["failed"] == 1
    assert payload["checks"][0]["status"] == "FAIL"
    assert "do-not-print" not in errors[0]


def test_provider_adapter_acceptance_smoke_failure_report_does_not_leak_values(tmp_path):
    fixture_path = tmp_path / "bad_adapter_fixture.json"
    report_path = tmp_path / "reports" / "provider_adapter_acceptance_smoke.json"
    fixture_path.write_text(
        json.dumps({
            "provider": {
                "providerId": "bad-fixture",
                "category": "STRUCTURED_FACT_DATA_SOURCE",
            },
            "source": "bad-fixture",
            "snapshotTime": "2026-06-01T12:00:00+00:00",
            "auditContext": {"apiToken": "secret-report-token"},
            "facts": {"fixtures": []},
        }),
        encoding="utf-8",
    )
    events = []
    errors = []

    exit_code = run_provider_adapter_acceptance_smoke(
        fixtures=[{
            "name": "bad_fixture",
            "fixture": str(fixture_path),
            "expectedProviderId": "bad-fixture",
            "requiredFactKeys": ["fixtures", "official_lineups"],
        }],
        write_report_path=str(report_path),
        emit=events.append,
        error=errors.append,
    )

    report_text = report_path.read_text(encoding="utf-8")
    report_payload = json.loads(report_text)
    assert exit_code == 2
    assert events == []
    assert report_payload["status"] == "FAIL"
    assert report_payload["failed"] == 1
    assert report_payload["checks"][0]["status"] == "FAIL"
    assert "secret-report-token" not in errors[0]
    assert "secret-report-token" not in report_text
