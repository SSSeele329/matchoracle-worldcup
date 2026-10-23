import json
import os
import subprocess
import sys

from scripts.release_readiness_report import parse_env_file, run_release_readiness_report
from src.worldcup.release_manifest import build_release_readiness_manifest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def fake_report(status, checks=None):
    checks = checks or []
    report = {
        "ok": status == "READY",
        "status": status,
        "environment": "production" if status != "DEMO_READY" else "development",
        "checks": checks,
        "blockingChecks": [check["name"] for check in checks if check.get("status") == "FAIL"],
        "warningChecks": [check["name"] for check in checks if check.get("status") == "WARN"],
    }
    report["releaseReadinessManifest"] = build_release_readiness_manifest(report)
    return report


def test_release_readiness_cli_returns_zero_when_ready():
    events = []
    exit_code = run_release_readiness_report(
        emit=events.append,
        report_fn=lambda: fake_report("READY", [{"name": "workerAuth", "status": "PASS"}]),
    )

    payload = json.loads(events[0])
    assert exit_code == 0
    assert payload["readinessStatus"] == "READY"
    assert payload["readyForProduction"] is True


def test_release_readiness_cli_validates_schema_when_requested():
    events = []
    errors = []
    exit_code = run_release_readiness_report(
        validate_schema=True,
        emit=events.append,
        error=errors.append,
        report_fn=lambda: fake_report("READY", [{"name": "workerAuth", "status": "PASS"}]),
    )

    payload = json.loads(events[0])
    assert exit_code == 0
    assert payload["readinessStatus"] == "READY"
    assert errors == []


def test_release_readiness_cli_blocks_non_ready_by_default():
    events = []
    exit_code = run_release_readiness_report(
        emit=events.append,
        report_fn=lambda: fake_report("BLOCKED", [{"name": "workerAuth", "status": "FAIL"}]),
    )

    payload = json.loads(events[0])
    assert exit_code == 2
    assert payload["readinessStatus"] == "BLOCKED"
    assert payload["blockingChecks"] == ["workerAuth"]


def test_release_readiness_cli_can_allow_demo_status():
    events = []
    exit_code = run_release_readiness_report(
        allow_demo=True,
        emit=events.append,
        report_fn=lambda: fake_report("DEMO_READY", [{"name": "workerAuth", "status": "WARN"}]),
    )

    payload = json.loads(events[0])
    assert exit_code == 0
    assert payload["readinessStatus"] == "DEMO_READY"
    assert payload["readyForProduction"] is False


def test_release_readiness_cli_outputs_only_redacted_manifest():
    events = []
    exit_code = run_release_readiness_report(
        emit=events.append,
        report_fn=lambda: fake_report("READY", [{
            "name": "predictionSnapshotStore",
            "status": "PASS",
            "env": "MATCHORACLE_SNAPSHOT_STORE",
            "configuredValue": "/private/tmp/secret.sqlite3",
            "tokenValue": "do-not-print",
        }]),
    )

    encoded = events[0]
    payload = json.loads(encoded)
    assert exit_code == 0
    assert "releaseReadinessManifest" not in payload
    assert payload["environmentVariables"][0]["value"] == "REDACTED"
    assert "/private/tmp/secret.sqlite3" not in encoded
    assert "do-not-print" not in encoded


def test_release_readiness_cli_summary_is_redacted_and_actionable():
    events = []
    exit_code = run_release_readiness_report(
        summary=True,
        emit=events.append,
        report_fn=lambda: fake_report("BLOCKED", [{
            "name": "predictionSnapshotStore",
            "status": "FAIL",
            "env": "MATCHORACLE_SNAPSHOT_STORE",
            "configuredValue": "/private/tmp/secret.sqlite3",
            "tokenValue": "do-not-print",
        }]),
    )

    output = events[0]
    assert exit_code == 2
    assert "Readiness: BLOCKED" in output
    assert "Ready for production: no" in output
    assert "Blocking checks: predictionSnapshotStore" in output
    assert "MATCHORACLE_SNAPSHOT_STORE" in output
    assert "values are not printed" in output
    assert "/private/tmp/secret.sqlite3" not in output
    assert "do-not-print" not in output


def test_release_readiness_cli_writes_redacted_json_report(tmp_path):
    report_path = tmp_path / "nested" / "readiness.json"
    events = []
    exit_code = run_release_readiness_report(
        write_report=str(report_path),
        emit=events.append,
        report_fn=lambda: fake_report("READY", [{
            "name": "predictionSnapshotStore",
            "status": "PASS",
            "env": "MATCHORACLE_SNAPSHOT_STORE",
            "configuredValue": "/private/tmp/secret.sqlite3",
        }]),
    )

    file_text = report_path.read_text(encoding="utf-8")
    payload = json.loads(file_text)
    assert exit_code == 0
    assert json.loads(events[0]) == payload
    assert payload["readinessStatus"] == "READY"
    assert "/private/tmp/secret.sqlite3" not in file_text


def test_release_readiness_cli_writes_redacted_summary_report(tmp_path):
    report_path = tmp_path / "readiness.txt"
    events = []
    exit_code = run_release_readiness_report(
        summary=True,
        write_report=str(report_path),
        emit=events.append,
        report_fn=lambda: fake_report("BLOCKED", [{
            "name": "workerAuth",
            "status": "FAIL",
            "env": "MATCHORACLE_WORKER_TOKEN",
            "tokenValue": "super-secret-token",
        }]),
    )

    file_text = report_path.read_text(encoding="utf-8")
    assert exit_code == 2
    assert events[0] == file_text.strip()
    assert "Readiness: BLOCKED" in file_text
    assert "MATCHORACLE_WORKER_TOKEN" in file_text
    assert "super-secret-token" not in file_text


def test_release_readiness_cli_schema_failure_does_not_print_manifest_or_secrets():
    events = []
    errors = []

    def invalid_report():
        report = fake_report("READY", [{
            "name": "predictionSnapshotStore",
            "status": "PASS",
            "env": "MATCHORACLE_SNAPSHOT_STORE",
            "configuredValue": "/private/tmp/secret.sqlite3",
        }])
        report["releaseReadinessManifest"].pop("manifestVersion")
        return report

    exit_code = run_release_readiness_report(
        validate_schema=True,
        emit=events.append,
        error=errors.append,
        report_fn=invalid_report,
    )

    payload = json.loads(errors[0])
    assert exit_code == 3
    assert events == []
    assert payload["event"] == "RELEASE_READINESS_SCHEMA_FAILED"
    assert "manifestVersion is required." in payload["errors"]
    assert "/private/tmp/secret.sqlite3" not in errors[0]


def test_release_readiness_cli_env_file_dry_run_uses_file_only(tmp_path):
    env_file = tmp_path / "production.env"
    env_file.write_text(
        "\n".join([
            "MATCHORACLE_APP_ENV=production",
            "MATCHORACLE_WORKER_TOKEN=",
            "MATCHORACLE_WORKER_RUNTIME_CONFIGURED=0",
            "MATCHORACLE_SNAPSHOT_STORE=",
            "MATCHORACLE_JOB_QUEUE_STORE=",
            "MATCHORACLE_ODDS_STORE=",
            "MATCHORACLE_STRUCTURED_FACTS_STORE=",
            "MATCHORACLE_STRUCTURED_FACTS_PROVIDER=",
            "MATCHORACLE_STRUCTURED_FACTS_PROVIDER_CONFIGURED=0",
        ]),
        encoding="utf-8",
    )
    os.environ["MATCHORACLE_WORKER_TOKEN"] = "local-shell-token-should-not-matter"
    events = []
    try:
        exit_code = run_release_readiness_report(
            env_file=str(env_file),
            summary=True,
            emit=events.append,
        )
    finally:
        os.environ.pop("MATCHORACLE_WORKER_TOKEN", None)

    output = events[0]
    assert exit_code == 2
    assert "Readiness: BLOCKED" in output
    assert "Blocking checks:" in output
    assert "workerAuth" in output
    assert "local-shell-token-should-not-matter" not in output


def test_release_readiness_cli_env_file_can_validate_ready_config_without_leaking_values(tmp_path):
    env_file = tmp_path / "production-ready.env"
    secret_path = str(tmp_path / "secret-store.sqlite3")
    env_file.write_text(
        "\n".join([
            "MATCHORACLE_APP_ENV=production",
            "MATCHORACLE_WORKER_TOKEN=super-secret-token",
            "MATCHORACLE_WORKER_RUNTIME_CONFIGURED=1",
            f"MATCHORACLE_SNAPSHOT_STORE={secret_path}",
            f"MATCHORACLE_JOB_QUEUE_STORE={secret_path}",
            f"MATCHORACLE_ODDS_STORE={secret_path}",
            f"MATCHORACLE_STRUCTURED_FACTS_STORE={secret_path}",
            "MATCHORACLE_STRUCTURED_FACTS_PROVIDER=contract_provider",
            "MATCHORACLE_STRUCTURED_FACTS_PROVIDER_CONFIGURED=1",
            "MATCHORACLE_STRUCTURED_FACTS_API_BASE_URL=https://provider.example/structured-facts",
            "MATCHORACLE_STRUCTURED_FACTS_PROVIDER_TOKEN=provider-secret-token",
            "MATCHORACLE_AI_EVIDENCE_PROVIDER=disabled",
            "MATCHORACLE_AI_EVIDENCE_POLICY=EVIDENCE_EXTRACTION_ONLY",
            "MATCHORACLE_CSV_FALLBACK_ENABLED=1",
            "MATCHORACLE_JOB_FAILURE_ALERTS_CONFIGURED=1",
            "MATCHORACLE_STALE_JOB_MONITOR_CONFIGURED=1",
            "MATCHORACLE_QUEUE_BACKLOG_MONITOR_CONFIGURED=1",
            "MATCHORACLE_STORE_BACKUP_POLICY_CONFIGURED=1",
            "MATCHORACLE_STORE_MIGRATION_POLICY_CONFIGURED=1",
        ]),
        encoding="utf-8",
    )
    events = []

    exit_code = run_release_readiness_report(
        env_file=str(env_file),
        validate_schema=True,
        emit=events.append,
    )

    encoded = events[0]
    payload = json.loads(encoded)
    assert exit_code == 0
    assert payload["readinessStatus"] == "READY"
    assert payload["readyForProduction"] is True
    assert "super-secret-token" not in encoded
    assert "provider-secret-token" not in encoded
    assert "provider.example" not in encoded
    assert secret_path not in encoded


def test_release_readiness_cli_env_file_parse_error_is_redacted(tmp_path):
    env_file = tmp_path / "broken.env"
    env_file.write_text("MATCHORACLE_WORKER_TOKEN super-secret-token\n", encoding="utf-8")
    events = []
    errors = []

    exit_code = run_release_readiness_report(
        env_file=str(env_file),
        emit=events.append,
        error=errors.append,
    )

    payload = json.loads(errors[0])
    assert exit_code == 4
    assert events == []
    assert payload["event"] == "RELEASE_READINESS_ENV_FILE_FAILED"
    assert payload["code"] == "ENV_FILE_LINE_INVALID"
    assert "super-secret-token" not in errors[0]


def test_env_file_parser_accepts_export_and_quoted_values(tmp_path):
    env_file = tmp_path / "quoted.env"
    env_file.write_text(
        "export MATCHORACLE_APP_ENV='production'\nMATCHORACLE_WORKER_RUNTIME_CONFIGURED=\"1\"\n",
        encoding="utf-8",
    )

    values = parse_env_file(str(env_file))

    assert values["MATCHORACLE_APP_ENV"] == "production"
    assert values["MATCHORACLE_WORKER_RUNTIME_CONFIGURED"] == "1"


def test_release_readiness_script_runs_directly_without_server():
    env = {key: value for key, value in os.environ.items() if not key.startswith("MATCHORACLE_")}
    result = subprocess.run(
        [sys.executable, "scripts/release_readiness_report.py", "--allow-demo", "--validate-schema"],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    assert result.returncode == 0
    assert payload["readinessStatus"] == "DEMO_READY"
    assert payload["readyForProduction"] is False
    assert result.stderr == ""


def test_release_readiness_script_accepts_env_file(tmp_path):
    env_file = tmp_path / "production.env"
    env_file.write_text(
        "MATCHORACLE_APP_ENV=production\nMATCHORACLE_WORKER_TOKEN=\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "scripts/release_readiness_report.py",
            "--env-file",
            str(env_file),
            "--summary",
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "Readiness: BLOCKED" in result.stdout
    assert "MATCHORACLE_WORKER_TOKEN=" not in result.stdout
    assert result.stderr == ""


def test_release_readiness_script_writes_report_file(tmp_path):
    report_path = tmp_path / "readiness-summary.txt"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/release_readiness_report.py",
            "--allow-demo",
            "--summary",
            "--write-report",
            str(report_path),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Readiness: DEMO_READY" in result.stdout
    assert report_path.read_text(encoding="utf-8").startswith("Readiness: DEMO_READY")
