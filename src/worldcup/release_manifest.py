RELEASE_MANIFEST_VERSION = "release-readiness-manifest-v1"
CORE_RUNTIME_CATEGORY = "CORE_RUNTIME"
CORE_STORAGE_CATEGORY = "CORE_STORAGE"
GENERAL_CATEGORY = "GENERAL"
VALID_READINESS_STATUSES = {"READY", "DEMO_READY", "BLOCKED"}
REQUIRED_STATUS_COUNT_KEYS = {"PASS", "WARN", "FAIL"}
RELEASE_MANIFEST_SCHEMA_VERSION = "release-readiness-manifest-schema-v1"

SAFE_CHECK_FIELDS = {
    "allowedOutputs",
    "apiBaseUrlConfigured",
    "capability",
    "category",
    "configured",
    "contractVersion",
    "deploymentAgnostic",
    "enabled",
    "env",
    "forbiddenOutputs",
    "legacyHeaderAllowed",
    "message",
    "missingEnv",
    "name",
    "policy",
    "production",
    "provider",
    "requiredMetadata",
    "status",
    "tokenConfigured",
    "tokenRequired",
}


class ReleaseManifestSchemaError(ValueError):
    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("Release readiness manifest schema validation failed.")


RELEASE_READINESS_MANIFEST_SCHEMA = {
    "schemaVersion": RELEASE_MANIFEST_SCHEMA_VERSION,
    "manifestVersion": RELEASE_MANIFEST_VERSION,
    "requiredTopLevelFields": [
        "manifestVersion",
        "readinessStatus",
        "readyForProduction",
        "environment",
        "redactionPolicy",
        "statusCounts",
        "blockingChecks",
        "warningChecks",
        "checkGroups",
        "environmentVariables",
        "checks",
    ],
    "validReadinessStatuses": sorted(VALID_READINESS_STATUSES),
    "redactionValue": "REDACTED",
}


def check_category(check):
    if check.get("category"):
        return check["category"]
    name = check.get("name")
    if name in {"workerAuth", "workerRuntime"}:
        return CORE_RUNTIME_CATEGORY
    if name in {"predictionSnapshotStore", "backgroundJobStore", "marketOddsStore", "structuredFactsStore"}:
        return CORE_STORAGE_CATEGORY
    return GENERAL_CATEGORY


def normalize_env_names(env_value):
    if not env_value:
        return []
    if isinstance(env_value, (list, tuple)):
        return [str(item) for item in env_value if item]
    return [str(env_value)]


def sanitized_check(check):
    redacted = {
        key: value
        for key, value in (check or {}).items()
        if key in SAFE_CHECK_FIELDS
    }
    redacted["category"] = check_category(check or {})
    if "env" in redacted:
        redacted["env"] = normalize_env_names(redacted["env"])
    return redacted


def env_manifest_items(checks):
    items = []
    seen = set()
    for check in checks:
        for env_name in normalize_env_names(check.get("env")):
            if env_name in seen:
                continue
            seen.add(env_name)
            items.append({
                "name": env_name,
                "check": check.get("name"),
                "status": check.get("status"),
                "category": check_category(check),
                "value": "REDACTED",
            })
    return items


def status_counts(checks):
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for check in checks:
        status = check.get("status")
        if status not in counts:
            counts[status] = 0
        counts[status] += 1
    return counts


def grouped_check_names(checks):
    groups = {}
    for check in checks:
        category = check_category(check)
        groups.setdefault(category, []).append(check.get("name"))
    return groups


def build_release_readiness_manifest(readiness_report):
    checks = readiness_report.get("checks") or []
    sanitized_checks = [sanitized_check(check) for check in checks]
    status = readiness_report.get("status")
    return {
        "manifestVersion": RELEASE_MANIFEST_VERSION,
        "readinessStatus": status,
        "readyForProduction": status == "READY",
        "environment": readiness_report.get("environment"),
        "redactionPolicy": "Environment variable values, tokens, store paths, domains, and provider secrets are never included.",
        "statusCounts": status_counts(checks),
        "blockingChecks": list(readiness_report.get("blockingChecks") or []),
        "warningChecks": list(readiness_report.get("warningChecks") or []),
        "checkGroups": grouped_check_names(checks),
        "environmentVariables": env_manifest_items(checks),
        "checks": sanitized_checks,
    }


def require_type(errors, manifest, field, expected_type):
    value = manifest.get(field)
    if not isinstance(value, expected_type):
        errors.append(f"{field} must be {expected_type.__name__}.")
        return None
    return value


def validate_environment_variables(errors, manifest):
    items = require_type(errors, manifest, "environmentVariables", list)
    if items is None:
        return
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"environmentVariables[{index}] must be object.")
            continue
        for field in ("name", "check", "status", "category", "value"):
            if field not in item:
                errors.append(f"environmentVariables[{index}].{field} is required.")
        if item.get("value") != "REDACTED":
            errors.append(f"environmentVariables[{index}].value must be REDACTED.")


def validate_checks(errors, manifest):
    checks = require_type(errors, manifest, "checks", list)
    if checks is None:
        return
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            errors.append(f"checks[{index}] must be object.")
            continue
        if not isinstance(check.get("name"), str) or not check.get("name"):
            errors.append(f"checks[{index}].name must be non-empty string.")
        if check.get("status") not in {"PASS", "WARN", "FAIL"}:
            errors.append(f"checks[{index}].status must be PASS, WARN, or FAIL.")
        if not isinstance(check.get("category"), str) or not check.get("category"):
            errors.append(f"checks[{index}].category must be non-empty string.")
        if "env" in check and not isinstance(check["env"], list):
            errors.append(f"checks[{index}].env must be list when present.")


def validate_release_readiness_manifest(manifest):
    errors = []
    if not isinstance(manifest, dict):
        raise ReleaseManifestSchemaError(["manifest must be object."])

    for field in RELEASE_READINESS_MANIFEST_SCHEMA["requiredTopLevelFields"]:
        if field not in manifest:
            errors.append(f"{field} is required.")

    if manifest.get("manifestVersion") != RELEASE_MANIFEST_VERSION:
        errors.append("manifestVersion is not supported.")
    if manifest.get("readinessStatus") not in VALID_READINESS_STATUSES:
        errors.append("readinessStatus must be READY, DEMO_READY, or BLOCKED.")
    require_type(errors, manifest, "readyForProduction", bool)
    require_type(errors, manifest, "environment", str)
    require_type(errors, manifest, "redactionPolicy", str)

    status_count_values = require_type(errors, manifest, "statusCounts", dict)
    if isinstance(status_count_values, dict):
        missing = REQUIRED_STATUS_COUNT_KEYS - set(status_count_values)
        for key in sorted(missing):
            errors.append(f"statusCounts.{key} is required.")
        for key, value in status_count_values.items():
            if not isinstance(value, int):
                errors.append(f"statusCounts.{key} must be int.")

    require_type(errors, manifest, "blockingChecks", list)
    require_type(errors, manifest, "warningChecks", list)
    require_type(errors, manifest, "checkGroups", dict)
    validate_environment_variables(errors, manifest)
    validate_checks(errors, manifest)

    if errors:
        raise ReleaseManifestSchemaError(errors)
    return {
        "status": "PASS",
        "schemaVersion": RELEASE_MANIFEST_SCHEMA_VERSION,
        "manifestVersion": RELEASE_MANIFEST_VERSION,
    }
