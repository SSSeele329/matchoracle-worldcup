from .lineup_check import normalize_role
from .snapshot_store import parse_iso_datetime


VALID_SIDES = {"home", "away"}
VALID_TIERS = {"TIER_1", "TIER_2", "TIER_3", "UNKNOWN"}
VALID_EXPECTED_ROLES = {"STARTER", "BENCH", "OUT", "UNKNOWN"}
VALID_TRAINING = {"FULL", "PARTIAL", "NO", "UNKNOWN"}
VALID_REPORTER = {"POSITIVE", "NEGATIVE", "MIXED", "NONE"}
VALID_INJURY = {"FIT", "DOUBTFUL", "OUT", "UNKNOWN"}
DIRECT_PROBABILITY_KEYS = {"probability", "startProbability", "start_probability", "aiStartProbability"}


def clamp(value, low, high):
    return max(low, min(high, value))


def normalize_value(value, allowed, default="UNKNOWN"):
    normalized = str(value or default).strip().upper()
    return normalized if normalized in allowed else default


def optional_minutes(value):
    try:
        if value in (None, ""):
            return None
        return max(0, float(value))
    except (TypeError, ValueError):
        return None


def evidence_items(payload):
    if not payload:
        return []
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return payload.get("players") or payload.get("evidence") or []
    return []


def inherited_snapshot_time(payload):
    if isinstance(payload, dict):
        return payload.get("snapshotTime") or payload.get("snapshot_time")
    return None


def source_timestamp(source):
    if isinstance(source, dict):
        return source.get("publishedAt") or source.get("timestamp") or source.get("snapshotTime")
    return None


def evidence_timestamp(evidence, parent_snapshot_time=None):
    direct = evidence.get("snapshotTime") or evidence.get("snapshot_time") or parent_snapshot_time
    if direct:
        return direct
    for source in evidence.get("sources") or []:
        timestamp = source_timestamp(source)
        if timestamp:
            return timestamp
    coach_quote = evidence.get("coachQuote") or {}
    if isinstance(coach_quote, dict):
        return coach_quote.get("publishedAt") or coach_quote.get("timestamp")
    return None


def has_source(evidence):
    sources = evidence.get("sources") or []
    coach_quote = evidence.get("coachQuote") or {}
    return bool(sources or (isinstance(coach_quote, dict) and coach_quote.get("source")))


def has_probability_evidence(expected_role, training, reporter, injury, minutes, coach_quote):
    return any([
        expected_role != "UNKNOWN",
        training != "UNKNOWN",
        reporter != "NONE",
        injury != "UNKNOWN",
        minutes is not None,
        isinstance(coach_quote, dict) and coach_quote.get("available"),
    ])


def start_threshold(player):
    if player["tier"] == "TIER_1" and player["roleGroup"] == "GOALKEEPER":
        return 0.65
    return 0.70


def start_status(probability):
    if probability is None:
        return "UNKNOWN"
    if probability >= 0.70:
        return "LIKELY_STARTER"
    if probability <= 0.25:
        return "UNLIKELY_STARTER"
    return "UNCERTAIN"


def calculate_start_probability(evidence, kickoff_at=None, parent_snapshot_time=None):
    expected_role = normalize_value(evidence.get("expectedRole"), VALID_EXPECTED_ROLES)
    training = normalize_value(evidence.get("trainedWithTeam"), VALID_TRAINING)
    reporter = normalize_value(evidence.get("reliableReporterSignal"), VALID_REPORTER, default="NONE")
    injury = normalize_value(evidence.get("injuryStatus"), VALID_INJURY)
    minutes = optional_minutes(evidence.get("recentMinutes"))
    coach_quote = evidence.get("coachQuote") or {}
    timestamp = evidence_timestamp(evidence, parent_snapshot_time=parent_snapshot_time)
    parsed_timestamp = parse_iso_datetime(timestamp)
    parsed_kickoff = parse_iso_datetime(kickoff_at)
    direct_probability_ignored = any(key in evidence for key in DIRECT_PROBABILITY_KEYS)
    issues = []

    if not parsed_timestamp:
        issues.append("EVIDENCE_TIMESTAMP_MISSING")
    if parsed_timestamp and parsed_kickoff and parsed_timestamp >= parsed_kickoff:
        issues.append("EVIDENCE_AFTER_KICKOFF")
    if not has_source(evidence):
        issues.append("SOURCE_MISSING")
    if not has_probability_evidence(expected_role, training, reporter, injury, minutes, coach_quote):
        issues.append("NO_PROBABILITY_EVIDENCE")

    if issues:
        return {
            "startProbability": None,
            "status": "UNKNOWN",
            "confidence": "LOW",
            "issues": issues,
            "directProbabilityIgnored": direct_probability_ignored,
        }

    score = 0.50
    score += {"STARTER": 0.25, "BENCH": -0.20, "OUT": -0.45, "UNKNOWN": 0}.get(expected_role, 0)
    score += {"FULL": 0.15, "PARTIAL": -0.05, "NO": -0.25, "UNKNOWN": 0}.get(training, 0)
    score += {"POSITIVE": 0.16, "NEGATIVE": -0.20, "MIXED": -0.03, "NONE": 0}.get(reporter, 0)
    score += {"FIT": 0.16, "DOUBTFUL": -0.25, "OUT": -0.50, "UNKNOWN": 0}.get(injury, 0)
    if isinstance(coach_quote, dict) and coach_quote.get("available"):
        score += 0.12
    if minutes is not None:
        if minutes >= 200:
            score += 0.12
        elif minutes >= 120:
            score += 0.08
        elif minutes > 0:
            score += 0.03
        else:
            score -= 0.05
    if len(evidence.get("sources") or []) >= 2:
        score += 0.04

    probability = round(clamp(score, 0.03, 0.97), 3)
    confidence = "HIGH" if len(evidence.get("sources") or []) >= 2 and reporter in {"POSITIVE", "NEGATIVE"} else "MEDIUM"
    return {
        "startProbability": probability,
        "status": start_status(probability),
        "confidence": confidence,
        "issues": [],
        "directProbabilityIgnored": direct_probability_ignored,
    }


def build_player_projection(evidence, kickoff_at=None, parent_snapshot_time=None):
    player = str(evidence.get("player") or evidence.get("name") or "").strip()
    side = str(evidence.get("teamSide") or evidence.get("side") or "").strip().lower()
    tier = normalize_value(evidence.get("playerTier") or evidence.get("tier"), VALID_TIERS)
    role = normalize_role(evidence.get("roleGroup") or evidence.get("role") or "UNKNOWN")
    probability = calculate_start_probability(evidence, kickoff_at=kickoff_at, parent_snapshot_time=parent_snapshot_time)
    sources = evidence.get("sources") or []
    return {
        "player": player,
        "teamSide": side if side in VALID_SIDES else "UNKNOWN",
        "tier": tier,
        "roleGroup": role,
        "expectedRole": normalize_value(evidence.get("expectedRole"), VALID_EXPECTED_ROLES),
        "trainedWithTeam": normalize_value(evidence.get("trainedWithTeam"), VALID_TRAINING),
        "reliableReporterSignal": normalize_value(evidence.get("reliableReporterSignal"), VALID_REPORTER, default="NONE"),
        "injuryStatus": normalize_value(evidence.get("injuryStatus"), VALID_INJURY),
        "recentMinutes": optional_minutes(evidence.get("recentMinutes")),
        "startProbability": probability["startProbability"],
        "status": probability["status"],
        "confidence": probability["confidence"],
        "issues": probability["issues"],
        "directProbabilityIgnored": probability["directProbabilityIgnored"],
        "sources": sources,
        "evidenceTimestamp": evidence_timestamp(evidence, parent_snapshot_time=parent_snapshot_time),
    }


def players_for_side(players, side):
    return [player for player in players if player["teamSide"] == side]


def expected_names(players, side):
    return [
        player["player"]
        for player in players_for_side(players, side)
        if player["player"] and player["startProbability"] is not None and player["startProbability"] >= start_threshold(player)
    ]


def expected_key_players(players, side):
    key_players = []
    for player in players_for_side(players, side):
        probability = player["startProbability"]
        if not player["player"] or probability is None or probability < start_threshold(player):
            continue
        key_players.append({
            "name": player["player"],
            "tier": player["tier"],
            "role": player["roleGroup"],
            "startProbability": probability,
            "confidence": player["confidence"],
        })
    return key_players


def build_f04p_expected_lineup(match_input):
    payload = (match_input or {}).get("expectedLineupEvidence")
    items = evidence_items(payload)
    parent_snapshot_time = inherited_snapshot_time(payload)
    kickoff_at = ((match_input or {}).get("match") or {}).get("datetime")
    players = [
        build_player_projection(item or {}, kickoff_at=kickoff_at, parent_snapshot_time=parent_snapshot_time)
        for item in items
    ]
    valid_players = [player for player in players if player["player"] and player["teamSide"] in VALID_SIDES]
    expected_lineup = {
        "homeStarters": expected_names(valid_players, "home"),
        "awayStarters": expected_names(valid_players, "away"),
        "homeKeyPlayers": expected_key_players(valid_players, "home"),
        "awayKeyPlayers": expected_key_players(valid_players, "away"),
    }
    known_count = sum(1 for player in valid_players if player["startProbability"] is not None)
    issue_count = sum(1 for player in players if player["issues"] or not player["player"] or player["teamSide"] not in VALID_SIDES)
    status = "AVAILABLE" if known_count else "UNKNOWN"
    return {
        "status": status,
        "snapshotTime": parent_snapshot_time,
        "players": players,
        "expectedLineup": expected_lineup,
        "summary": {
            "playersEvaluated": len(players),
            "playersWithProbability": known_count,
            "issueCount": issue_count,
        },
        "historicalBacktestEligible": False,
        "validationMode": "FORWARD_VALIDATION_ONLY",
        "policy": "AI/search may extract evidence fields only; startProbability is calculated by deterministic code.",
    }


def enrich_match_input_with_f04p(match_input):
    if not (match_input or {}).get("expectedLineupEvidence"):
        return match_input, None
    f04p = build_f04p_expected_lineup(match_input)
    enriched = dict(match_input)
    enriched["f04PExpectedLineup"] = f04p
    if not enriched.get("expectedLineup") and f04p["summary"]["playersWithProbability"]:
        enriched["expectedLineup"] = f04p["expectedLineup"]
    return enriched, f04p
