from src.worldcup.operations_contracts import (
    JOB_FAILURE_ALERTS_ENV,
    OPERATIONS_CATEGORY,
    QUEUE_BACKLOG_MONITOR_ENV,
    STALE_JOB_MONITOR_ENV,
    STORE_BACKUP_POLICY_ENV,
    STORE_MIGRATION_POLICY_ENV,
    build_operations_readiness_checks,
)


ALL_OPERATION_ENVS = {
    JOB_FAILURE_ALERTS_ENV: "1",
    STALE_JOB_MONITOR_ENV: "1",
    QUEUE_BACKLOG_MONITOR_ENV: "1",
    STORE_BACKUP_POLICY_ENV: "1",
    STORE_MIGRATION_POLICY_ENV: "1",
}


def test_operations_checks_warn_for_local_demo_without_platform_binding():
    checks = build_operations_readiness_checks(production=False, environ={})

    assert {check["status"] for check in checks} == {"WARN"}
    assert {check["category"] for check in checks} == {OPERATIONS_CATEGORY}
    assert all(check["deploymentAgnostic"] is True for check in checks)


def test_operations_checks_block_production_until_contracts_are_declared():
    checks = build_operations_readiness_checks(production=True, environ={})

    assert {check["status"] for check in checks} == {"FAIL"}
    assert {check["name"] for check in checks} == {
        "jobFailureAlerts",
        "staleJobMonitor",
        "queueBacklogMonitor",
        "storeBackupPolicy",
        "storeMigrationPolicy",
    }


def test_operations_checks_pass_with_explicit_contract_envs():
    checks = build_operations_readiness_checks(production=True, environ=ALL_OPERATION_ENVS)

    assert {check["status"] for check in checks} == {"PASS"}
    assert all("no platform-specific provider is required" not in check["message"] for check in checks)
