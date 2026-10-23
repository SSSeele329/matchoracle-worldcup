import os


CONTRACT_VERSION = "operations-contract-v1"
OPERATIONS_CATEGORY = "DEPLOYMENT_AGNOSTIC_OPERATIONS"

JOB_FAILURE_ALERTS_ENV = "MATCHORACLE_JOB_FAILURE_ALERTS_CONFIGURED"
STALE_JOB_MONITOR_ENV = "MATCHORACLE_STALE_JOB_MONITOR_CONFIGURED"
QUEUE_BACKLOG_MONITOR_ENV = "MATCHORACLE_QUEUE_BACKLOG_MONITOR_CONFIGURED"
STORE_BACKUP_POLICY_ENV = "MATCHORACLE_STORE_BACKUP_POLICY_CONFIGURED"
STORE_MIGRATION_POLICY_ENV = "MATCHORACLE_STORE_MIGRATION_POLICY_CONFIGURED"

TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}
FALSY_ENV_VALUES = {"0", "false", "no", "off"}

OPERATIONS_CONTRACTS = (
    {
        "name": "jobFailureAlerts",
        "env": JOB_FAILURE_ALERTS_ENV,
        "capability": "FAILED background jobs trigger an operator-visible alert.",
    },
    {
        "name": "staleJobMonitor",
        "env": STALE_JOB_MONITOR_ENV,
        "capability": "Long-running RUNNING jobs are detected and reviewed.",
    },
    {
        "name": "queueBacklogMonitor",
        "env": QUEUE_BACKLOG_MONITOR_ENV,
        "capability": "Queue backlog and worker starvation are monitored.",
    },
    {
        "name": "storeBackupPolicy",
        "env": STORE_BACKUP_POLICY_ENV,
        "capability": "Snapshot, job queue, and odds stores have an explicit backup/restore policy.",
    },
    {
        "name": "storeMigrationPolicy",
        "env": STORE_MIGRATION_POLICY_ENV,
        "capability": "Store schema changes have an explicit migration and rollback policy.",
    },
)


def env_value(name, default=None, environ=None):
    source = environ if environ is not None else os.environ
    value = source.get(name)
    if value is None:
        return default
    return str(value).strip()


def parse_bool_env(name, default=False, environ=None):
    value = env_value(name, environ=environ)
    if value is None or value == "":
        return default
    lowered = value.lower()
    if lowered in TRUTHY_ENV_VALUES:
        return True
    if lowered in FALSY_ENV_VALUES:
        return False
    return default


def operations_contract_check(contract, production=False, environ=None):
    configured = parse_bool_env(contract["env"], default=False, environ=environ)
    base = {
        "name": contract["name"],
        "category": OPERATIONS_CATEGORY,
        "contractVersion": CONTRACT_VERSION,
        "env": contract["env"],
        "configured": configured,
        "deploymentAgnostic": True,
        "capability": contract["capability"],
    }
    if configured:
        return {
            **base,
            "status": "PASS",
            "message": f"{contract['env']} declares this production operations capability is configured.",
        }
    if production:
        return {
            **base,
            "status": "FAIL",
            "message": f"{contract['env']} must be set before production release; no platform-specific provider is required.",
        }
    return {
        **base,
        "status": "WARN",
        "message": f"{contract['env']} is not set; acceptable only for local demo.",
    }


def build_operations_readiness_checks(production=False, environ=None):
    return [
        operations_contract_check(contract, production=production, environ=environ)
        for contract in OPERATIONS_CONTRACTS
    ]
