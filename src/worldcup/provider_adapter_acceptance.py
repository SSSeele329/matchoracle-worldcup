from .provider_contracts import (
    STRUCTURED_FACTS_CATEGORY,
    STRUCTURED_FACT_OUTPUTS,
    StructuredFactsPayloadError,
    validate_structured_facts_payload,
)


SENSITIVE_FIELD_FRAGMENTS = (
    "authorization",
    "apikey",
    "api_key",
    "api-token",
    "api_token",
    "bearer",
    "clientsecret",
    "client_secret",
    "password",
    "secret",
    "token",
)
INLINE_RAW_PAYLOAD_KEYS = {
    "rawPayload",
    "raw_payload",
    "rawResponse",
    "raw_response",
    "responseBody",
    "response_body",
    "vendorPayload",
    "vendor_payload",
}


class ProviderAdapterAcceptanceError(ValueError):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def _normalized_key(value):
    return str(value).strip().lower()


def _walk_payload(value, path=None):
    path = path or []
    if isinstance(value, dict):
        for key, item in value.items():
            current_path = [*path, str(key)]
            yield current_path, key, item
            yield from _walk_payload(item, current_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_payload(item, [*path, str(index)])


def find_sensitive_field_paths(payload):
    findings = []
    for path, key, _item in _walk_payload(payload):
        normalized = _normalized_key(key).replace("-", "_")
        if any(fragment in normalized for fragment in SENSITIVE_FIELD_FRAGMENTS):
            findings.append(".".join(path))
    return findings


def find_inline_raw_payload_paths(payload):
    findings = []
    for path, key, _item in _walk_payload(payload):
        if key in INLINE_RAW_PAYLOAD_KEYS:
            findings.append(".".join(path))
    return findings


def validate_provider_adapter_output(
    payload,
    expected_provider_id=None,
    required_fact_keys=None,
    allow_empty_required_buckets=False,
):
    errors = []
    try:
        contract_validation = validate_structured_facts_payload(payload)
    except StructuredFactsPayloadError as error:
        errors.extend(error.details.get("errors") or [error.message])
        contract_validation = None

    provider = payload.get("provider") if isinstance(payload, dict) else None
    if not isinstance(provider, dict):
        errors.append("provider metadata is required for adapter acceptance.")
    else:
        provider_id = provider.get("providerId") or provider.get("provider_id")
        if not isinstance(provider_id, str) or not provider_id.strip():
            errors.append("provider.providerId is required for adapter acceptance.")
        if expected_provider_id and provider_id != expected_provider_id:
            errors.append(f"provider.providerId must match expected provider id: {expected_provider_id}.")
        if provider.get("category") != STRUCTURED_FACTS_CATEGORY:
            errors.append("provider.category must be STRUCTURED_FACT_DATA_SOURCE.")

    facts = payload.get("facts") if isinstance(payload, dict) else None
    required_fact_keys = list(required_fact_keys or [])
    unknown_required = sorted(set(required_fact_keys) - set(STRUCTURED_FACT_OUTPUTS))
    for key in unknown_required:
        errors.append(f"required fact key is not supported by MatchOracle: {key}.")
    if isinstance(facts, dict):
        for key in required_fact_keys:
            if key not in facts:
                errors.append(f"facts.{key} is required for this adapter acceptance run.")
            elif not allow_empty_required_buckets and not facts.get(key):
                errors.append(f"facts.{key} must not be empty for this adapter acceptance run.")

    sensitive_paths = find_sensitive_field_paths(payload)
    if sensitive_paths:
        errors.append("adapter output must not include token, secret, authorization, password, or API key fields.")

    inline_raw_payload_paths = find_inline_raw_payload_paths(payload)
    if inline_raw_payload_paths:
        errors.append("adapter output must not inline raw vendor payloads; use rawPayloadHash/rawPayloadRef/auditContext instead.")

    if errors:
        raise ProviderAdapterAcceptanceError(
            "PROVIDER_ADAPTER_ACCEPTANCE_FAILED",
            "Provider adapter output failed MatchOracle acceptance checks.",
            details={
                "errors": errors,
                "sensitiveFieldPaths": sensitive_paths,
                "inlineRawPayloadPaths": inline_raw_payload_paths,
            },
        )

    fact_counts = {key: len(value) for key, value in sorted((facts or {}).items())}
    return {
        "status": "PASS",
        "providerId": provider.get("providerId") or provider.get("provider_id"),
        "source": payload.get("source"),
        "snapshotTime": payload.get("snapshotTime") or payload.get("snapshot_time"),
        "requiredFactKeys": required_fact_keys,
        "factCounts": fact_counts,
        "contractValidation": contract_validation,
    }
