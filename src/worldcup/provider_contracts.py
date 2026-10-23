import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


CONTRACT_VERSION = "provider-contract-v1"

STRUCTURED_FACTS_CATEGORY = "STRUCTURED_FACT_DATA_SOURCE"
AI_EVIDENCE_CATEGORY = "AI_EVIDENCE_EXTRACTION"
CSV_MANUAL_FALLBACK_CATEGORY = "CSV_MANUAL_FALLBACK"

STRUCTURED_FACTS_PROVIDER_ENV = "MATCHORACLE_STRUCTURED_FACTS_PROVIDER"
STRUCTURED_FACTS_CONFIGURED_ENV = "MATCHORACLE_STRUCTURED_FACTS_PROVIDER_CONFIGURED"
STRUCTURED_FACTS_API_BASE_URL_ENV = "MATCHORACLE_STRUCTURED_FACTS_API_BASE_URL"
STRUCTURED_FACTS_PROVIDER_TOKEN_ENV = "MATCHORACLE_STRUCTURED_FACTS_PROVIDER_TOKEN"
AI_EVIDENCE_PROVIDER_ENV = "MATCHORACLE_AI_EVIDENCE_PROVIDER"
AI_EVIDENCE_POLICY_ENV = "MATCHORACLE_AI_EVIDENCE_POLICY"
AI_FACT_GENERATION_ENV = "MATCHORACLE_AI_ALLOW_FACT_GENERATION"
CSV_FALLBACK_ENABLED_ENV = "MATCHORACLE_CSV_FALLBACK_ENABLED"

EVIDENCE_ONLY_POLICY = "EVIDENCE_EXTRACTION_ONLY"
PROVIDER_MODE_DISABLED = "disabled"
PROVIDER_MODE_MOCK = "mock"

TRUTHY_ENV_VALUES = {"1", "true", "yes", "on"}
FALSY_ENV_VALUES = {"0", "false", "no", "off"}
NON_PRODUCTION_FACT_PROVIDER_VALUES = {
    "",
    PROVIDER_MODE_DISABLED,
    PROVIDER_MODE_MOCK,
    "csv",
    "manual",
    "csv_manual",
    "csv_manual_fallback",
}

STRUCTURED_FACT_OUTPUTS = (
    "fixtures",
    "kickoff_time",
    "match_status",
    "official_lineups",
    "scores",
    "standings",
    "cards",
    "market_odds_snapshots",
)
AI_ALLOWED_OUTPUTS = (
    "expected_lineup_evidence",
    "injury_training_evidence",
    "coach_quote_evidence",
    "reporter_signal_evidence",
    "tactical_or_narrative_evidence",
)
AI_FORBIDDEN_FACT_OUTPUTS = (
    "odds",
    "official_lineups",
    "scores",
    "standings",
    "yellow_cards",
    "red_cards",
    "cards",
)
CSV_FALLBACK_OUTPUTS = (
    "manual_market_odds_csv",
    "admin_reviewed_seed_data",
)
STRUCTURED_FACT_AUDIT_KEYS = {
    "auditContext",
    "rawPayloadHash",
    "rawPayloadRef",
    "raw_payload_hash",
    "raw_payload_or_audit_context",
    "raw_payload_ref",
}

AI_FORBIDDEN_FACT_FIELD_KEYS = {
    "actualLineup",
    "actualLineups",
    "awayGoals",
    "awayPoints",
    "awayScore",
    "awayStarters",
    "cards",
    "decimalOdds",
    "drawOdds",
    "finalScore",
    "goals",
    "goalsAgainst",
    "goalsFor",
    "groupStandings",
    "homeGoals",
    "homeOdds",
    "homePoints",
    "homeScore",
    "homeStarters",
    "lineup",
    "lineups",
    "liveScore",
    "marketOdds",
    "officialLineup",
    "officialLineups",
    "odds",
    "oddsProbabilities",
    "points",
    "redCards",
    "score",
    "scores",
    "standings",
    "startingXi",
    "yellowCards",
}
NORMALIZED_AI_FORBIDDEN_FACT_FIELD_KEYS = {
    "".join(character for character in key.lower() if character.isalnum())
    for key in AI_FORBIDDEN_FACT_FIELD_KEYS
}


class ProviderContractError(ValueError):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


class StructuredFactsPayloadError(ProviderContractError):
    pass


@dataclass(frozen=True)
class ProviderContract:
    provider_id: str
    category: str
    mode: str
    allowed_outputs: tuple
    forbidden_outputs: tuple = ()
    required_metadata: tuple = ("source", "snapshot_time")
    production_ready: bool = False

    def to_dict(self):
        return {
            "providerId": self.provider_id,
            "category": self.category,
            "mode": self.mode,
            "contractVersion": CONTRACT_VERSION,
            "allowedOutputs": list(self.allowed_outputs),
            "forbiddenOutputs": list(self.forbidden_outputs),
            "requiredMetadata": list(self.required_metadata),
            "productionReady": self.production_ready,
        }


class MatchOracleProvider(ABC):
    @abstractmethod
    def contract(self):
        raise NotImplementedError


class StructuredFactDataProvider(MatchOracleProvider):
    @abstractmethod
    def fetch_structured_facts(self, match_id, snapshot_time=None):
        raise NotImplementedError


class AIEvidenceExtractionProvider(MatchOracleProvider):
    @abstractmethod
    def extract_evidence(self, documents, context=None):
        raise NotImplementedError


class CsvManualFallbackProvider(MatchOracleProvider):
    @abstractmethod
    def describe_fallback(self):
        raise NotImplementedError


class MockStructuredFactDataProvider(StructuredFactDataProvider):
    def contract(self):
        return ProviderContract(
            provider_id="mock_structured_facts",
            category=STRUCTURED_FACTS_CATEGORY,
            mode=PROVIDER_MODE_MOCK,
            allowed_outputs=STRUCTURED_FACT_OUTPUTS,
            production_ready=False,
        )

    def fetch_structured_facts(self, match_id, snapshot_time=None):
        return {
            "provider": self.contract().to_dict(),
            "status": "MOCK_ONLY",
            "source": "mock_structured_facts",
            "matchId": match_id,
            "snapshotTime": snapshot_time or "1970-01-01T00:00:00+00:00",
            "auditContext": {"mode": "mock", "productionReady": False},
            "facts": {},
        }


class MockAIEvidenceExtractionProvider(AIEvidenceExtractionProvider):
    def contract(self):
        return ProviderContract(
            provider_id="mock_ai_evidence_extraction",
            category=AI_EVIDENCE_CATEGORY,
            mode=PROVIDER_MODE_MOCK,
            allowed_outputs=AI_ALLOWED_OUTPUTS,
            forbidden_outputs=AI_FORBIDDEN_FACT_OUTPUTS,
            production_ready=False,
        )

    def extract_evidence(self, documents, context=None):
        evidence = (context or {}).get("mockEvidence") or {}
        validate_ai_evidence_payload(evidence)
        return {
            "provider": self.contract().to_dict(),
            "policy": EVIDENCE_ONLY_POLICY,
            "documentsEvaluated": len(documents or []),
            "evidence": evidence,
        }


class CsvManualMarketFallbackProvider(CsvManualFallbackProvider):
    def contract(self):
        return ProviderContract(
            provider_id="csv_manual_market_fallback",
            category=CSV_MANUAL_FALLBACK_CATEGORY,
            mode="fallback",
            allowed_outputs=CSV_FALLBACK_OUTPUTS,
            required_metadata=("source", "snapshot_time", "admin_review_state"),
            production_ready=False,
        )

    def describe_fallback(self):
        return {
            "provider": self.contract().to_dict(),
            "status": "FALLBACK_ONLY",
            "message": "CSV/manual inputs can seed reviewed fallback data but do not satisfy the structured facts provider contract.",
        }


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


def provider_mode(name, default, environ=None):
    return (env_value(name, default=default, environ=environ) or "").strip().lower()


def normalized_field_key(key):
    return "".join(character for character in str(key).lower() if character.isalnum())


def forbidden_fact_field_paths(payload, path=None):
    path = path or []
    if isinstance(payload, dict):
        paths = []
        for key, value in payload.items():
            current_path = [*path, str(key)]
            if normalized_field_key(key) in NORMALIZED_AI_FORBIDDEN_FACT_FIELD_KEYS:
                paths.append(".".join(current_path))
            paths.extend(forbidden_fact_field_paths(value, current_path))
        return paths
    if isinstance(payload, list):
        paths = []
        for index, value in enumerate(payload):
            paths.extend(forbidden_fact_field_paths(value, [*path, str(index)]))
        return paths
    return []


def validate_ai_evidence_payload(payload):
    forbidden_paths = forbidden_fact_field_paths(payload or {})
    if forbidden_paths:
        raise ProviderContractError(
            "AI_FACT_OUTPUT_FORBIDDEN",
            "AI evidence extraction cannot output factual data such as odds, official lineups, scores, standings, or cards.",
            details={"forbiddenPaths": forbidden_paths},
        )
    return {
        "status": "PASS",
        "policy": EVIDENCE_ONLY_POLICY,
        "forbiddenPaths": [],
    }


def parse_iso_timestamp(value):
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def structured_fact_snapshot_time(payload):
    return payload.get("snapshotTime") or payload.get("snapshot_time")


def validate_structured_facts_payload(payload):
    errors = []
    if not isinstance(payload, dict):
        raise StructuredFactsPayloadError(
            "STRUCTURED_FACTS_PAYLOAD_INVALID",
            "Structured facts payload must be an object.",
            details={"errors": ["payload must be object."]},
        )

    for field in ("source", "facts"):
        if field not in payload:
            errors.append(f"{field} is required.")
    if "snapshotTime" not in payload and "snapshot_time" not in payload:
        errors.append("snapshotTime or snapshot_time is required.")

    if not isinstance(payload.get("source"), str) or not payload.get("source", "").strip():
        errors.append("source must be non-empty string.")
    if not parse_iso_timestamp(structured_fact_snapshot_time(payload)):
        errors.append("snapshotTime or snapshot_time must be a timezone-aware ISO timestamp.")
    if not any(key in payload for key in STRUCTURED_FACT_AUDIT_KEYS):
        errors.append("rawPayloadRef, rawPayloadHash, or auditContext is required.")

    provider = payload.get("provider")
    if provider is not None:
        if not isinstance(provider, dict):
            errors.append("provider must be object when present.")
        elif provider.get("category") != STRUCTURED_FACTS_CATEGORY:
            errors.append("provider.category must be STRUCTURED_FACT_DATA_SOURCE.")

    facts = payload.get("facts")
    if not isinstance(facts, dict):
        errors.append("facts must be object.")
    else:
        unknown_fact_keys = sorted(set(facts) - set(STRUCTURED_FACT_OUTPUTS))
        for key in unknown_fact_keys:
            errors.append(f"facts.{key} is not an allowed structured fact key.")
        for key, value in facts.items():
            if key in STRUCTURED_FACT_OUTPUTS and not isinstance(value, list):
                errors.append(f"facts.{key} must be list.")

    if errors:
        raise StructuredFactsPayloadError(
            "STRUCTURED_FACTS_PAYLOAD_INVALID",
            "Structured facts payload failed provider contract validation.",
            details={"errors": errors},
        )
    return {
        "status": "PASS",
        "category": STRUCTURED_FACTS_CATEGORY,
        "allowedFactKeys": list(STRUCTURED_FACT_OUTPUTS),
    }


def structured_facts_provider_check(production=False, environ=None):
    provider = provider_mode(STRUCTURED_FACTS_PROVIDER_ENV, PROVIDER_MODE_MOCK, environ=environ)
    configured = parse_bool_env(STRUCTURED_FACTS_CONFIGURED_ENV, default=False, environ=environ)
    api_base_url_configured = bool(env_value(STRUCTURED_FACTS_API_BASE_URL_ENV, environ=environ))
    token_configured = bool(env_value(STRUCTURED_FACTS_PROVIDER_TOKEN_ENV, environ=environ))
    env_names = [
        STRUCTURED_FACTS_PROVIDER_ENV,
        STRUCTURED_FACTS_CONFIGURED_ENV,
        STRUCTURED_FACTS_API_BASE_URL_ENV,
        STRUCTURED_FACTS_PROVIDER_TOKEN_ENV,
    ]
    base = {
        "name": "structuredFactsProvider",
        "category": STRUCTURED_FACTS_CATEGORY,
        "contractVersion": CONTRACT_VERSION,
        "env": env_names,
        "provider": provider,
        "configured": configured,
        "apiBaseUrlConfigured": api_base_url_configured,
        "tokenConfigured": token_configured,
        "allowedOutputs": list(STRUCTURED_FACT_OUTPUTS),
        "requiredMetadata": ["source", "snapshot_time", "raw_payload_or_audit_context"],
    }
    if production and (provider in NON_PRODUCTION_FACT_PROVIDER_VALUES or not configured):
        return {
            **base,
            "status": "FAIL",
            "message": "Production requires an explicit structured facts provider; mock, disabled, CSV, and manual fallback modes are not sufficient.",
        }
    if production and (not api_base_url_configured or not token_configured):
        missing = []
        if not api_base_url_configured:
            missing.append(STRUCTURED_FACTS_API_BASE_URL_ENV)
        if not token_configured:
            missing.append(STRUCTURED_FACTS_PROVIDER_TOKEN_ENV)
        return {
            **base,
            "status": "FAIL",
            "missingEnv": missing,
            "message": "Production structured facts provider requires an API base URL and provider token.",
        }
    if provider in NON_PRODUCTION_FACT_PROVIDER_VALUES:
        return {
            **base,
            "status": "WARN",
            "message": "Structured facts provider is mock/disabled; acceptable for local contract testing only.",
        }
    if configured and (not api_base_url_configured or not token_configured):
        missing = []
        if not api_base_url_configured:
            missing.append(STRUCTURED_FACTS_API_BASE_URL_ENV)
        if not token_configured:
            missing.append(STRUCTURED_FACTS_PROVIDER_TOKEN_ENV)
        return {
            **base,
            "status": "WARN",
            "missingEnv": missing,
            "message": "Structured facts provider is selected, but local sync will not run until the API base URL and provider token are configured.",
        }
    status = "PASS" if configured else "WARN"
    message = (
        "Structured facts provider is declared and configured."
        if configured
        else "Structured facts provider name is declared but configuration has not been acknowledged."
    )
    return {**base, "status": status, "message": message}


def ai_evidence_provider_check(production=False, environ=None):
    provider = provider_mode(AI_EVIDENCE_PROVIDER_ENV, PROVIDER_MODE_DISABLED, environ=environ)
    policy = env_value(AI_EVIDENCE_POLICY_ENV, default=EVIDENCE_ONLY_POLICY, environ=environ).upper()
    fact_generation = parse_bool_env(AI_FACT_GENERATION_ENV, default=False, environ=environ)
    base = {
        "name": "aiEvidenceProvider",
        "category": AI_EVIDENCE_CATEGORY,
        "contractVersion": CONTRACT_VERSION,
        "env": [AI_EVIDENCE_PROVIDER_ENV, AI_EVIDENCE_POLICY_ENV],
        "provider": provider,
        "policy": policy,
        "allowedOutputs": list(AI_ALLOWED_OUTPUTS),
        "forbiddenOutputs": list(AI_FORBIDDEN_FACT_OUTPUTS),
    }
    if fact_generation:
        return {
            **base,
            "status": "FAIL",
            "message": f"{AI_FACT_GENERATION_ENV}=1 is not allowed; AI providers may not generate factual match data.",
        }
    if policy != EVIDENCE_ONLY_POLICY:
        return {
            **base,
            "status": "FAIL",
            "message": f"{AI_EVIDENCE_POLICY_ENV} must remain {EVIDENCE_ONLY_POLICY}.",
        }
    if provider == PROVIDER_MODE_DISABLED:
        return {
            **base,
            "status": "PASS",
            "message": "AI evidence extraction is disabled; structured facts and deterministic code remain the source of truth.",
        }
    if production and provider == PROVIDER_MODE_MOCK:
        return {
            **base,
            "status": "WARN",
            "message": "Mock AI evidence extraction is not a production capability; AI remains optional and evidence-only.",
        }
    return {
        **base,
        "status": "PASS",
        "message": "AI evidence provider is constrained to evidence extraction and narrative support only.",
    }


def csv_manual_fallback_check(production=False, environ=None):
    enabled = parse_bool_env(CSV_FALLBACK_ENABLED_ENV, default=True, environ=environ)
    status = "PASS" if enabled else "WARN"
    message = (
        "CSV/manual fallback is available for reviewed imports and local recovery; it does not satisfy structured facts readiness."
        if enabled
        else "CSV/manual fallback is disabled; automated structured facts must cover production data needs."
    )
    return {
        "name": "csvManualFallback",
        "category": CSV_MANUAL_FALLBACK_CATEGORY,
        "contractVersion": CONTRACT_VERSION,
        "env": CSV_FALLBACK_ENABLED_ENV,
        "enabled": enabled,
        "status": status,
        "allowedOutputs": list(CSV_FALLBACK_OUTPUTS),
        "message": message,
    }


def provider_contract_policy_check():
    return {
        "name": "providerContractPolicy",
        "status": "PASS",
        "contractVersion": CONTRACT_VERSION,
        "message": "Provider categories are separated: structured facts, AI evidence extraction, and CSV/manual fallback.",
        "aiPolicy": {
            "allowed": list(AI_ALLOWED_OUTPUTS),
            "forbidden": list(AI_FORBIDDEN_FACT_OUTPUTS),
        },
    }


def build_provider_contract_readiness_checks(production=False, environ=None):
    return [
        structured_facts_provider_check(production=production, environ=environ),
        ai_evidence_provider_check(production=production, environ=environ),
        csv_manual_fallback_check(production=production, environ=environ),
        provider_contract_policy_check(),
    ]
