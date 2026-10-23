import json
import os
import subprocess
import sys

import scripts.release_preflight_bundle as preflight_bundle
from scripts.release_preflight_bundle import (
    build_preflight_bundle,
    render_preflight_summary,
    run_release_preflight_bundle,
    validate_preflight_bundle,
)


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def test_release_preflight_bundle_passes_with_fake_checks(tmp_path):
    task_file = tmp_path / "DEVELOPMENT_TASKS.md"
    task_file.write_text("unused", encoding="utf-8")

    bundle = build_preflight_bundle(
        task_file=str(task_file),
        production_env_file="deploy/production.env.example",
        current_task_check_fn=lambda path: {"status": "PASS", "nextTask": "NONE", "hasQueuedTask": False},
        adapter_smoke_check_fn=lambda: {"status": "PASS", "checked": 2, "failed": 0},
        demo_readiness_check_fn=lambda: {"status": "PASS", "readinessStatus": "DEMO_READY"},
        production_template_check_fn=lambda path: {"status": "PASS", "readinessStatus": "BLOCKED"},
    )

    assert bundle["event"] == "MATCHORACLE_RELEASE_PREFLIGHT"
    assert bundle["status"] == "PASS"
    assert bundle["failedChecks"] == []
    assert bundle["checks"]["currentTask"]["nextTask"] == "NONE"
    assert validate_preflight_bundle(bundle)["status"] == "PASS"


def test_release_preflight_bundle_marks_failed_check():
    bundle = build_preflight_bundle(
        current_task_check_fn=lambda path: {"status": "PASS", "nextTask": "NONE", "hasQueuedTask": False},
        adapter_smoke_check_fn=lambda: {"status": "FAIL", "checked": 2, "failed": 1},
        demo_readiness_check_fn=lambda: {"status": "PASS", "readinessStatus": "DEMO_READY"},
        production_template_check_fn=lambda path: {"status": "PASS", "readinessStatus": "BLOCKED"},
    )

    assert bundle["status"] == "FAIL"
    assert bundle["failedChecks"] == ["providerAdapterSmoke"]
    assert validate_preflight_bundle(bundle)["status"] == "PASS"


def test_release_preflight_bundle_schema_guard_rejects_broken_shape():
    validation = validate_preflight_bundle({
        "event": "MATCHORACLE_RELEASE_PREFLIGHT",
        "status": "PASS",
        "failedChecks": [],
        "checks": {
            "providerAdapterSmoke": {"status": "FAIL"},
        },
        "redaction": "No secrets are printed.",
    })

    assert validation["status"] == "FAIL"
    assert "checks.currentTask must be object." in validation["errors"]
    assert "failedChecks must equal non-PASS check names in preflight order." in validation["errors"]
    assert "PASS bundle cannot contain non-PASS checks." in validation["errors"]


def test_release_preflight_bundle_writes_report(tmp_path):
    report_path = tmp_path / "reports" / "release_preflight_bundle.json"
    events = []
    errors = []

    exit_code = run_release_preflight_bundle(
        write_report=str(report_path),
        emit=events.append,
        error=errors.append,
    )

    emitted = json.loads(events[0])
    written = json.loads(report_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert errors == []
    assert emitted == written
    assert emitted["status"] == "PASS"


def test_release_preflight_bundle_summary_writes_same_redacted_text(tmp_path):
    report_path = tmp_path / "reports" / "release_preflight_summary.txt"
    events = []
    errors = []

    exit_code = run_release_preflight_bundle(
        write_report=str(report_path),
        summary=True,
        emit=events.append,
        error=errors.append,
    )

    output = events[0]
    written = report_path.read_text(encoding="utf-8").strip()
    assert exit_code == 0
    assert errors == []
    assert output == written
    assert output.startswith("Preflight: PASS")
    assert "Failed checks: none" in output
    assert "- currentTask: status=PASS; nextTask=NONE" in output
    assert "- productionTemplateReadiness: status=PASS; readiness=BLOCKED; readyForProduction=no" in output
    assert "provider-secret-token" not in output
    assert "provider.example" not in output


def test_render_preflight_summary_reports_failed_optional_check():
    bundle = build_preflight_bundle(
        current_task_check_fn=lambda path: {"status": "PASS", "nextTask": "NONE", "hasQueuedTask": False},
        adapter_smoke_check_fn=lambda: {"status": "PASS", "checked": 2, "failed": 0, "smokeStatus": "PASS"},
        demo_readiness_check_fn=lambda: {"status": "PASS", "readinessStatus": "DEMO_READY"},
        production_template_check_fn=lambda path: {"status": "PASS", "readinessStatus": "BLOCKED"},
        ready_env_file="broken.env",
        production_ready_env_check_fn=lambda path: {
            "status": "FAIL",
            "exitCode": 4,
            "errorCode": "ENV_FILE_READ_FAILED",
        },
    )

    summary = render_preflight_summary(bundle)
    assert "Preflight: FAIL" in summary
    assert "Failed checks: productionReadyEnvReadiness" in summary
    assert "- productionReadyEnvReadiness: status=FAIL; errorCode=ENV_FILE_READ_FAILED" in summary


def test_release_preflight_bundle_does_not_write_schema_invalid_report(tmp_path, monkeypatch):
    report_path = tmp_path / "reports" / "release_preflight_bundle.json"
    events = []
    errors = []

    def broken_bundle(**kwargs):
        return {
            "event": "MATCHORACLE_RELEASE_PREFLIGHT",
            "status": "PASS",
            "failedChecks": [],
            "checks": {},
            "redaction": "No secrets are printed.",
        }

    monkeypatch.setattr(preflight_bundle, "build_preflight_bundle", broken_bundle)

    exit_code = run_release_preflight_bundle(
        write_report=str(report_path),
        emit=events.append,
        error=errors.append,
    )

    assert exit_code == 2
    assert events == []
    assert not report_path.exists()
    error_payload = json.loads(errors[0])
    assert error_payload["event"] == "MATCHORACLE_RELEASE_PREFLIGHT_SCHEMA_INVALID"


def test_release_preflight_bundle_script_runs_without_server(tmp_path):
    report_path = tmp_path / "release_preflight_bundle.json"
    env = {key: value for key, value in os.environ.items() if not key.startswith("MATCHORACLE_")}
    result = subprocess.run(
        [
            sys.executable,
            "scripts/release_preflight_bundle.py",
            "--write-report",
            str(report_path),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert result.returncode == 0
    assert payload == report_payload
    assert payload["status"] == "PASS"
    assert payload["checks"]["productionTemplateReadiness"]["readinessStatus"] == "BLOCKED"
    assert "provider-secret-token" not in result.stdout
    assert "provider.example" not in result.stdout
    assert result.stderr == ""


def test_release_preflight_bundle_script_redacts_real_environment_values(tmp_path):
    report_path = tmp_path / "release_preflight_bundle.json"
    secret_path = str(tmp_path / "secret-store.sqlite3")
    secret_values = [
        "preflight-worker-secret-token",
        "preflight-provider-secret-token",
        "preflight-odds-secret-token",
        "secret-provider.invalid",
        "secret-odds.invalid",
        secret_path,
    ]
    env = {key: value for key, value in os.environ.items() if not key.startswith("MATCHORACLE_")}
    env.update({
        "MATCHORACLE_APP_ENV": "production",
        "MATCHORACLE_WORKER_TOKEN": "preflight-worker-secret-token",
        "MATCHORACLE_WORKER_RUNTIME_CONFIGURED": "1",
        "MATCHORACLE_SNAPSHOT_STORE": secret_path,
        "MATCHORACLE_JOB_QUEUE_STORE": secret_path,
        "MATCHORACLE_ODDS_STORE": secret_path,
        "MATCHORACLE_STRUCTURED_FACTS_STORE": secret_path,
        "MATCHORACLE_STRUCTURED_FACTS_PROVIDER": "contract_provider",
        "MATCHORACLE_STRUCTURED_FACTS_PROVIDER_CONFIGURED": "1",
        "MATCHORACLE_STRUCTURED_FACTS_API_BASE_URL": "https://secret-provider.invalid/structured-facts",
        "MATCHORACLE_STRUCTURED_FACTS_PROVIDER_TOKEN": "preflight-provider-secret-token",
        "MATCHORACLE_AI_EVIDENCE_PROVIDER": "disabled",
        "MATCHORACLE_AI_EVIDENCE_POLICY": "EVIDENCE_EXTRACTION_ONLY",
        "MATCHORACLE_CSV_FALLBACK_ENABLED": "1",
        "MATCHORACLE_ODDS_API_BASE_URL": "https://secret-odds.invalid/v4",
        "MATCHORACLE_ODDS_PROVIDER_TOKEN": "preflight-odds-secret-token",
        "MATCHORACLE_JOB_FAILURE_ALERTS_CONFIGURED": "1",
        "MATCHORACLE_STALE_JOB_MONITOR_CONFIGURED": "1",
        "MATCHORACLE_QUEUE_BACKLOG_MONITOR_CONFIGURED": "1",
        "MATCHORACLE_STORE_BACKUP_POLICY_CONFIGURED": "1",
        "MATCHORACLE_STORE_MIGRATION_POLICY_CONFIGURED": "1",
    })

    result = subprocess.run(
        [
            sys.executable,
            "scripts/release_preflight_bundle.py",
            "--write-report",
            str(report_path),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    report_text = report_path.read_text(encoding="utf-8")
    combined_output = result.stdout + result.stderr + report_text
    assert result.returncode == 0
    assert payload["status"] == "PASS"
    assert payload["checks"]["demoReadiness"]["readinessStatus"] == "READY"
    assert result.stderr == ""
    for value in secret_values:
        assert value not in combined_output


def test_release_preflight_bundle_accepts_ready_env_file_without_leaking_values(tmp_path):
    env_file = tmp_path / "production.env"
    report_path = tmp_path / "release_preflight_bundle.json"
    secret_path = str(tmp_path / "ready-secret-store.sqlite3")
    secret_values = [
        "ready-worker-secret-token",
        "ready-provider-secret-token",
        "ready-odds-secret-token",
        "ready-provider.invalid",
        "ready-odds.invalid",
        secret_path,
    ]
    env_file.write_text(
        "\n".join([
            "MATCHORACLE_APP_ENV=production",
            "MATCHORACLE_WORKER_TOKEN=ready-worker-secret-token",
            "MATCHORACLE_WORKER_RUNTIME_CONFIGURED=1",
            f"MATCHORACLE_SNAPSHOT_STORE={secret_path}",
            f"MATCHORACLE_JOB_QUEUE_STORE={secret_path}",
            f"MATCHORACLE_ODDS_STORE={secret_path}",
            f"MATCHORACLE_STRUCTURED_FACTS_STORE={secret_path}",
            "MATCHORACLE_STRUCTURED_FACTS_PROVIDER=contract_provider",
            "MATCHORACLE_STRUCTURED_FACTS_PROVIDER_CONFIGURED=1",
            "MATCHORACLE_STRUCTURED_FACTS_API_BASE_URL=https://ready-provider.invalid/structured-facts",
            "MATCHORACLE_STRUCTURED_FACTS_PROVIDER_TOKEN=ready-provider-secret-token",
            "MATCHORACLE_AI_EVIDENCE_PROVIDER=disabled",
            "MATCHORACLE_AI_EVIDENCE_POLICY=EVIDENCE_EXTRACTION_ONLY",
            "MATCHORACLE_CSV_FALLBACK_ENABLED=1",
            "MATCHORACLE_ODDS_API_BASE_URL=https://ready-odds.invalid/v4",
            "MATCHORACLE_ODDS_PROVIDER_TOKEN=ready-odds-secret-token",
            "MATCHORACLE_JOB_FAILURE_ALERTS_CONFIGURED=1",
            "MATCHORACLE_STALE_JOB_MONITOR_CONFIGURED=1",
            "MATCHORACLE_QUEUE_BACKLOG_MONITOR_CONFIGURED=1",
            "MATCHORACLE_STORE_BACKUP_POLICY_CONFIGURED=1",
            "MATCHORACLE_STORE_MIGRATION_POLICY_CONFIGURED=1",
        ]),
        encoding="utf-8",
    )
    env = {key: value for key, value in os.environ.items() if not key.startswith("MATCHORACLE_")}

    result = subprocess.run(
        [
            sys.executable,
            "scripts/release_preflight_bundle.py",
            "--ready-env-file",
            str(env_file),
            "--write-report",
            str(report_path),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    report_text = report_path.read_text(encoding="utf-8")
    combined_output = result.stdout + result.stderr + report_text
    assert result.returncode == 0
    assert payload["status"] == "PASS"
    assert payload["checks"]["productionReadyEnvReadiness"]["readinessStatus"] == "READY"
    assert payload["checks"]["productionReadyEnvReadiness"]["readyForProduction"] is True
    assert result.stderr == ""
    assert validate_preflight_bundle(payload)["status"] == "PASS"
    for value in secret_values:
        assert value not in combined_output


def test_release_preflight_bundle_summary_with_ready_env_file_redacts_values(tmp_path):
    env_file = tmp_path / "summary-production.env"
    report_path = tmp_path / "release_preflight_summary.txt"
    secret_path = str(tmp_path / "summary-secret-store.sqlite3")
    secret_values = [
        "summary-worker-secret-token",
        "summary-provider-secret-token",
        "summary-odds-secret-token",
        "summary-provider.invalid",
        "summary-odds.invalid",
        secret_path,
    ]
    env_file.write_text(
        "\n".join([
            "MATCHORACLE_APP_ENV=production",
            "MATCHORACLE_WORKER_TOKEN=summary-worker-secret-token",
            "MATCHORACLE_WORKER_RUNTIME_CONFIGURED=1",
            f"MATCHORACLE_SNAPSHOT_STORE={secret_path}",
            f"MATCHORACLE_JOB_QUEUE_STORE={secret_path}",
            f"MATCHORACLE_ODDS_STORE={secret_path}",
            f"MATCHORACLE_STRUCTURED_FACTS_STORE={secret_path}",
            "MATCHORACLE_STRUCTURED_FACTS_PROVIDER=contract_provider",
            "MATCHORACLE_STRUCTURED_FACTS_PROVIDER_CONFIGURED=1",
            "MATCHORACLE_STRUCTURED_FACTS_API_BASE_URL=https://summary-provider.invalid/structured-facts",
            "MATCHORACLE_STRUCTURED_FACTS_PROVIDER_TOKEN=summary-provider-secret-token",
            "MATCHORACLE_AI_EVIDENCE_PROVIDER=disabled",
            "MATCHORACLE_AI_EVIDENCE_POLICY=EVIDENCE_EXTRACTION_ONLY",
            "MATCHORACLE_CSV_FALLBACK_ENABLED=1",
            "MATCHORACLE_ODDS_API_BASE_URL=https://summary-odds.invalid/v4",
            "MATCHORACLE_ODDS_PROVIDER_TOKEN=summary-odds-secret-token",
            "MATCHORACLE_JOB_FAILURE_ALERTS_CONFIGURED=1",
            "MATCHORACLE_STALE_JOB_MONITOR_CONFIGURED=1",
            "MATCHORACLE_QUEUE_BACKLOG_MONITOR_CONFIGURED=1",
            "MATCHORACLE_STORE_BACKUP_POLICY_CONFIGURED=1",
            "MATCHORACLE_STORE_MIGRATION_POLICY_CONFIGURED=1",
        ]),
        encoding="utf-8",
    )
    env = {key: value for key, value in os.environ.items() if not key.startswith("MATCHORACLE_")}

    result = subprocess.run(
        [
            sys.executable,
            "scripts/release_preflight_bundle.py",
            "--ready-env-file",
            str(env_file),
            "--summary",
            "--write-report",
            str(report_path),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    report_text = report_path.read_text(encoding="utf-8")
    combined_output = result.stdout + result.stderr + report_text
    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.strip() == report_text.strip()
    assert result.stdout.startswith("Preflight: PASS")
    assert "Failed checks: none" in result.stdout
    assert "- productionReadyEnvReadiness: status=PASS; readiness=READY; readyForProduction=yes" in result.stdout
    for value in secret_values:
        assert value not in combined_output


def test_release_preflight_bundle_ready_env_file_blocked_writes_redacted_failure_report(tmp_path):
    env_file = tmp_path / "blocked-production.env"
    report_path = tmp_path / "release_preflight_bundle.json"
    env_file.write_text(
        "\n".join([
            "MATCHORACLE_APP_ENV=production",
            "MATCHORACLE_WORKER_TOKEN=blocked-worker-secret-token",
            "MATCHORACLE_STRUCTURED_FACTS_PROVIDER_TOKEN=blocked-provider-secret-token",
            "MATCHORACLE_STRUCTURED_FACTS_API_BASE_URL=https://blocked-provider.invalid/structured-facts",
        ]),
        encoding="utf-8",
    )
    env = {key: value for key, value in os.environ.items() if not key.startswith("MATCHORACLE_")}

    result = subprocess.run(
        [
            sys.executable,
            "scripts/release_preflight_bundle.py",
            "--ready-env-file",
            str(env_file),
            "--write-report",
            str(report_path),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    combined_output = result.stdout + result.stderr + report_path.read_text(encoding="utf-8")
    assert result.returncode == 2
    assert result.stderr == ""
    assert payload == report_payload
    assert payload["status"] == "FAIL"
    assert payload["failedChecks"] == ["productionReadyEnvReadiness"]
    assert payload["checks"]["productionReadyEnvReadiness"]["status"] == "FAIL"
    assert payload["checks"]["productionReadyEnvReadiness"]["readinessStatus"] == "BLOCKED"
    assert validate_preflight_bundle(payload)["status"] == "PASS"
    assert "blocked-worker-secret-token" not in combined_output
    assert "blocked-provider-secret-token" not in combined_output
    assert "blocked-provider.invalid" not in combined_output


def test_release_preflight_bundle_ready_env_file_parse_error_reports_redacted_code(tmp_path):
    env_file = tmp_path / "broken-production.env"
    report_path = tmp_path / "release_preflight_bundle.json"
    env_file.write_text("MATCHORACLE_WORKER_TOKEN broken-env-secret-token\n", encoding="utf-8")
    env = {key: value for key, value in os.environ.items() if not key.startswith("MATCHORACLE_")}

    result = subprocess.run(
        [
            sys.executable,
            "scripts/release_preflight_bundle.py",
            "--ready-env-file",
            str(env_file),
            "--write-report",
            str(report_path),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    combined_output = result.stdout + result.stderr + report_path.read_text(encoding="utf-8")
    ready_check = payload["checks"]["productionReadyEnvReadiness"]
    assert result.returncode == 2
    assert result.stderr == ""
    assert payload == report_payload
    assert payload["status"] == "FAIL"
    assert payload["failedChecks"] == ["productionReadyEnvReadiness"]
    assert ready_check["exitCode"] == 4
    assert ready_check["errorEvent"] == "RELEASE_READINESS_ENV_FILE_FAILED"
    assert ready_check["errorCode"] == "ENV_FILE_LINE_INVALID"
    assert ready_check["errorMessage"] == "Env file lines must use KEY=value syntax."
    assert validate_preflight_bundle(payload)["status"] == "PASS"
    assert "broken-env-secret-token" not in combined_output


def test_release_preflight_bundle_ready_env_file_missing_reports_redacted_code(tmp_path):
    env_file = tmp_path / "missing-production.env"
    report_path = tmp_path / "release_preflight_bundle.json"
    env = {key: value for key, value in os.environ.items() if not key.startswith("MATCHORACLE_")}

    result = subprocess.run(
        [
            sys.executable,
            "scripts/release_preflight_bundle.py",
            "--ready-env-file",
            str(env_file),
            "--write-report",
            str(report_path),
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    combined_output = result.stdout + result.stderr + report_path.read_text(encoding="utf-8")
    ready_check = payload["checks"]["productionReadyEnvReadiness"]
    assert result.returncode == 2
    assert result.stderr == ""
    assert payload == report_payload
    assert payload["status"] == "FAIL"
    assert payload["failedChecks"] == ["productionReadyEnvReadiness"]
    assert ready_check["exitCode"] == 4
    assert ready_check["errorEvent"] == "RELEASE_READINESS_ENV_FILE_FAILED"
    assert ready_check["errorCode"] == "ENV_FILE_READ_FAILED"
    assert ready_check["errorMessage"] == "Could not read env file."
    assert validate_preflight_bundle(payload)["status"] == "PASS"
    assert str(env_file) not in combined_output
    assert "missing-production.env" not in combined_output
