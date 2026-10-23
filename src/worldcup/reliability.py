from datetime import datetime, timezone


CRITICAL_FIELDS = (
    "match.homeTeam",
    "match.awayTeam",
    "match.stage",
    "teamData.home.fifaRank",
    "teamData.away.fifaRank",
)


def get_path(payload, dotted_path):
    current = payload
    for key in dotted_path.split("."):
        if not isinstance(current, dict) or current.get(key) in (None, ""):
            return None
        current = current.get(key)
    return current


def parse_iso_datetime(value):
    if not value:
        return None
    try:
        normalized = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def build_data_reliability(match_input):
    missing_critical = [field for field in CRITICAL_FIELDS if get_path(match_input, field) is None]
    audit_events = []
    score = 100

    if missing_critical:
        audit_events.append({
            "level": "FATAL",
            "code": "MISSING_CRITICAL_FIELDS",
            "message": "缺少基础关键字段，预测已熔断。",
            "fields": missing_critical,
        })
        return {
            "status": "FATAL",
            "score": 0,
            "lineupReliability": 0,
            "injuryReliability": 0,
            "oddsFreshness": 0,
            "standingsFreshness": 0,
            "sourceConsistency": 0,
            "missingCriticalFields": missing_critical,
            "auditEvents": audit_events,
        }

    expected = match_input.get("expectedLineup") or {}
    actual = match_input.get("actualLineup") or {}
    lineup_reliability = 80
    if not expected:
        lineup_reliability = 45
        score -= 10
        audit_events.append({
            "level": "WARN",
            "code": "EXPECTED_LINEUP_MISSING",
            "message": "未提供T-24预计首发，Lineup Shock只能在官方首发输入后做有限判断。",
        })
    if actual and not expected:
        lineup_reliability = 35
        score -= 8
        audit_events.append({
            "level": "CRITICAL",
            "code": "ACTUAL_WITHOUT_EXPECTED_LINEUP",
            "message": "存在官方首发但缺少预计首发基线，无法计算首发突变delta。",
        })

    odds_timestamp = parse_iso_datetime(match_input.get("oddsSnapshotTime"))
    feature_timestamp = parse_iso_datetime(match_input.get("featureSnapshotTime"))
    odds_freshness = 70 if match_input.get("decimalOdds") else 0
    if match_input.get("decimalOdds") and not odds_timestamp:
        odds_freshness = 45
        score -= 6
        audit_events.append({
            "level": "WARN",
            "code": "ODDS_TIMESTAMP_MISSING",
            "message": "赔率缺少snapshot时间戳，市场分歧只能降级展示。",
        })
    if odds_timestamp and feature_timestamp and feature_timestamp < odds_timestamp:
        score -= 12
        audit_events.append({
            "level": "CRITICAL",
            "code": "RAW_MODEL_STALE_FOR_MARKET",
            "message": "模型特征时间早于赔率时间，禁止计算Market Divergence。",
        })

    status = "OK"
    if any(event["level"] == "CRITICAL" for event in audit_events):
        status = "CRITICAL"
    elif audit_events:
        status = "WARN"

    source_consistency = 100 if status == "OK" else 70 if status == "WARN" else 45
    return {
        "status": status,
        "score": max(0, min(100, score)),
        "lineupReliability": lineup_reliability,
        "injuryReliability": 50,
        "oddsFreshness": odds_freshness,
        "standingsFreshness": 70 if match_input.get("matchContext") else 40,
        "sourceConsistency": source_consistency,
        "missingCriticalFields": [],
        "auditEvents": audit_events,
    }


def market_divergence_allowed(match_input):
    odds_timestamp = parse_iso_datetime(match_input.get("oddsSnapshotTime"))
    feature_timestamp = parse_iso_datetime(match_input.get("featureSnapshotTime"))
    if not match_input.get("decimalOdds"):
        return False, "NO_MARKET_ODDS"
    if not odds_timestamp or not feature_timestamp:
        return False, "MISSING_TEMPORAL_ALIGNMENT"
    if feature_timestamp < odds_timestamp:
        return False, "RAW_MODEL_STALE"
    return True, "ALIGNED"


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()
