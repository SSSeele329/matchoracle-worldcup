import os

from .operations_contracts import build_operations_readiness_checks
from .provider_contracts import build_provider_contract_readiness_checks
from .release_manifest import build_release_readiness_manifest


PRODUCTION_ENV_VALUES = {"prod", "production"}
TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}
FALSY_ENV_VALUES = {"0", "false", "no", "off"}


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


def app_environment(environ=None):
    return (
        env_value("MATCHORACLE_APP_ENV", environ=environ)
        or env_value("APP_ENV", environ=environ)
        or env_value("FLASK_ENV", environ=environ)
        or "development"
    ).lower()


def is_production_runtime(environ=None):
    return app_environment(environ=environ) in PRODUCTION_ENV_VALUES


def worker_token_required(environ=None):
    explicit = env_value("MATCHORACLE_REQUIRE_WORKER_TOKEN", environ=environ)
    if explicit is not None and explicit != "":
        return parse_bool_env("MATCHORACLE_REQUIRE_WORKER_TOKEN", environ=environ)
    return is_production_runtime(environ=environ)


def worker_auth_state(environ=None):
    token_configured = bool(env_value("MATCHORACLE_WORKER_TOKEN", environ=environ))
    token_required = worker_token_required(environ=environ)
    return {
        "environment": app_environment(environ=environ),
        "production": is_production_runtime(environ=environ),
        "tokenConfigured": token_configured,
        "tokenRequired": token_required,
        "legacyHeaderAllowed": not token_required and not token_configured,
    }


def store_check(name, env_name, production=False, environ=None):
    value = env_value(env_name, environ=environ)
    if value:
        return {
            "name": name,
            "status": "PASS",
            "env": env_name,
            "message": f"{env_name} is configured.",
        }
    if production:
        return {
            "name": name,
            "status": "FAIL",
            "env": env_name,
            "message": f"{env_name} must be configured for production; default local SQLite paths are demo-only.",
        }
    return {
        "name": name,
        "status": "WARN",
        "env": env_name,
        "message": f"{env_name} is not set; default local SQLite path will be used.",
    }


def build_readiness_report(environ=None):
    checks = []
    production = is_production_runtime(environ=environ)
    auth_state = worker_auth_state(environ=environ)
    if auth_state["tokenRequired"] and not auth_state["tokenConfigured"]:
        checks.append({
            "name": "workerAuth",
            "status": "FAIL",
            "message": "Production worker endpoints require MATCHORACLE_WORKER_TOKEN.",
            **auth_state,
        })
    elif auth_state["tokenConfigured"]:
        checks.append({
            "name": "workerAuth",
            "status": "PASS",
            "message": "Worker token authentication is configured.",
            **auth_state,
        })
    else:
        checks.append({
            "name": "workerAuth",
            "status": "WARN",
            "message": "Legacy X-MatchOracle-Worker header is allowed for local demo only.",
            **auth_state,
        })

    worker_runtime_configured = parse_bool_env("MATCHORACLE_WORKER_RUNTIME_CONFIGURED", default=False, environ=environ)
    if production and not worker_runtime_configured:
        checks.append({
            "name": "workerRuntime",
            "status": "FAIL",
            "env": "MATCHORACLE_WORKER_RUNTIME_CONFIGURED",
            "message": "Production release requires an independent worker runtime.",
        })
    elif worker_runtime_configured:
        checks.append({
            "name": "workerRuntime",
            "status": "PASS",
            "env": "MATCHORACLE_WORKER_RUNTIME_CONFIGURED",
            "message": "Independent worker runtime is declared as configured.",
        })
    else:
        checks.append({
            "name": "workerRuntime",
            "status": "WARN",
            "env": "MATCHORACLE_WORKER_RUNTIME_CONFIGURED",
            "message": "No independent worker runtime declared; acceptable only for local demo.",
        })

    checks.extend([
        store_check("predictionSnapshotStore", "MATCHORACLE_SNAPSHOT_STORE", production=production, environ=environ),
        store_check("backgroundJobStore", "MATCHORACLE_JOB_QUEUE_STORE", production=production, environ=environ),
        store_check("marketOddsStore", "MATCHORACLE_ODDS_STORE", production=production, environ=environ),
        store_check("structuredFactsStore", "MATCHORACLE_STRUCTURED_FACTS_STORE", production=production, environ=environ),
    ])
    checks.extend(build_provider_contract_readiness_checks(production=production, environ=environ))
    checks.extend(build_operations_readiness_checks(production=production, environ=environ))

    failed = [check for check in checks if check["status"] == "FAIL"]
    warnings = [check for check in checks if check["status"] == "WARN"]
    if failed:
        status = "BLOCKED"
    elif warnings:
        status = "DEMO_READY"
    else:
        status = "READY"
    report = {
        "ok": not failed,
        "status": status,
        "environment": app_environment(environ=environ),
        "checks": checks,
        "blockingChecks": [check["name"] for check in failed],
        "warningChecks": [check["name"] for check in warnings],
    }
    report["releaseReadinessManifest"] = build_release_readiness_manifest(report)
    return report
