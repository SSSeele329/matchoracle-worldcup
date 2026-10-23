import hashlib
import json


CONFIG_VERSION = "p0-market-aligned-canonical"
SNAPSHOT_CONTROL_KEYS = {
    "persistSnapshot",
    "predictionCard",
    "predictionSnapshotId",
    "snapshotPolicy",
    "snapshotType",
}


def stable_hash(payload):
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def prediction_input_payload(match_input):
    return {
        key: value
        for key, value in (match_input or {}).items()
        if key not in SNAPSHOT_CONTROL_KEYS
    }


def prediction_input_hash(match_input):
    return stable_hash(prediction_input_payload(match_input))


def build_prediction_manifest(match_input, model_version, weight_scheme, data_reliability, factors=None):
    factors = factors or []
    disabled_factors = [
        factor["id"]
        for factor in factors
        if factor.get("degraded") and factor.get("role") in {"CORE", "LAMBDA_ONLY"}
    ]
    manifest = {
        "modelVersion": model_version,
        "configVersion": CONFIG_VERSION,
        "matchId": match_input.get("matchId"),
        "featureSnapshotTime": match_input.get("featureSnapshotTime"),
        "oddsSnapshotTime": match_input.get("oddsSnapshotTime"),
        "dependencySnapshotId": match_input.get("dependencySnapshotId"),
        "inputSnapshotHash": prediction_input_hash(match_input),
        "weightScheme": weight_scheme,
        "dataReliabilityStatus": data_reliability.get("status"),
        "activeFactorIds": [factor["id"] for factor in factors],
        "disabledCoreFactorIds": disabled_factors,
    }
    manifest["predictionSnapshotId"] = stable_hash(manifest)
    return manifest


def build_canonical_probability(
    probabilities,
    data_reliability,
    source="RAW_MODEL",
    reason=None,
    calibration=None,
    components=None,
):
    if data_reliability.get("status") == "FATAL":
        return {
            "status": "ABORTED",
            "source": "NONE",
            "probabilities": None,
            "reason": "Data reliability is FATAL; canonical probability is blocked.",
        }
    canonical = {
        "status": "ACTIVE",
        "source": source,
        "probabilities": probabilities,
        "reason": reason or "Risk and narrative layers explain this probability; they do not mutate it.",
    }
    if calibration:
        canonical["calibration"] = calibration
    if components:
        canonical["components"] = components
    return canonical
