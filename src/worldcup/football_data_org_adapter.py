import hashlib
import http.client
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .provider_contracts import (
    CONTRACT_VERSION,
    STRUCTURED_FACTS_CATEGORY,
    validate_structured_facts_payload,
)


FOOTBALL_DATA_ORG_PROVIDER_ID = "football_data_org"
FOOTBALL_DATA_ORG_TOKEN_ENV = "MATCHORACLE_FOOTBALL_DATA_ORG_TOKEN"
FOOTBALL_DATA_ORG_BASE_URL_ENV = "MATCHORACLE_FOOTBALL_DATA_ORG_API_BASE_URL"
FOOTBALL_DATA_ORG_COMPETITION_ENV = "MATCHORACLE_FOOTBALL_DATA_ORG_COMPETITION"
FOOTBALL_DATA_ORG_SEASON_ENV = "MATCHORACLE_FOOTBALL_DATA_ORG_SEASON"

DEFAULT_BASE_URL = "https://api.football-data.org/v4"
DEFAULT_COMPETITION = "WC"
DEFAULT_SEASON = "2026"
DEFAULT_TIMEOUT_SECONDS = 20

THROTTLE_HEADER_NAMES = (
    "X-Requests-Available-Minute",
    "X-RequestCounter-Reset",
    "X-RateLimit-Limit",
    "X-RateLimit-Remaining",
    "X-RateLimit-Reset",
)

STAGE_MAP = {
    "GROUP_STAGE": "GROUP_STAGE",
    "LAST_32": "ROUND_OF_32",
    "ROUND_OF_32": "ROUND_OF_32",
    "LAST_16": "ROUND_OF_16",
    "ROUND_OF_16": "ROUND_OF_16",
    "QUARTER_FINALS": "QUARTER_FINAL",
    "QUARTER_FINAL": "QUARTER_FINAL",
    "SEMI_FINALS": "SEMI_FINAL",
    "SEMI_FINAL": "SEMI_FINAL",
    "THIRD_PLACE": "THIRD_PLACE",
    "FINAL": "FINAL",
}

PERIOD_BY_STATUS = {
    "SCHEDULED": "PREMATCH",
    "TIMED": "PREMATCH",
    "IN_PLAY": "LIVE",
    "PAUSED": "LIVE",
    "FINISHED": "FINAL",
    "POSTPONED": "INTERRUPTED",
    "SUSPENDED": "INTERRUPTED",
    "CANCELED": "INTERRUPTED",
    "CANCELLED": "INTERRUPTED",
}


class FootballDataOrgAdapterError(ValueError):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def env_value(name, default=None, environ=None):
    source = environ if environ is not None else os.environ
    value = source.get(name)
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip()


def utc_now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def safe_endpoint_label(url):
    parsed = urllib.parse.urlparse(url or "")
    if not parsed.scheme or not parsed.netloc:
        return "invalid-url"
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def build_competition_url(base_url, competition, resource, params=None):
    path = "/".join((
        base_url.rstrip("/"),
        "competitions",
        urllib.parse.quote(str(competition).strip(), safe=""),
        resource.strip("/"),
    ))
    query = urllib.parse.urlencode({
        key: value
        for key, value in (params or {}).items()
        if value not in (None, "")
    })
    if query:
        return f"{path}?{query}"
    return path


def response_throttle_headers(response):
    headers = getattr(response, "headers", None) or {}
    result = {}
    for name in THROTTLE_HEADER_NAMES:
        value = None
        if hasattr(headers, "get"):
            value = headers.get(name)
        if value is not None:
            result[name] = str(value)
    return result


def fetch_json(url, token, timeout=DEFAULT_TIMEOUT_SECONDS, opener=None):
    if not token:
        raise FootballDataOrgAdapterError(
            "FOOTBALL_DATA_ORG_TOKEN_MISSING",
            "football-data.org token is required.",
            details={"env": FOOTBALL_DATA_ORG_TOKEN_ENV, "endpoint": safe_endpoint_label(url)},
        )
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "X-Auth-Token": token,
            "User-Agent": "MatchOracle-football-data-org-adapter/1.0",
        },
        method="GET",
    )
    opener = opener or urllib.request.urlopen
    try:
        with opener(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            throttling = response_throttle_headers(response)
    except urllib.error.HTTPError as failure:
        raise FootballDataOrgAdapterError(
            "FOOTBALL_DATA_ORG_HTTP_ERROR",
            "football-data.org returned an HTTP error.",
            details={"status": failure.code, "endpoint": safe_endpoint_label(url)},
        ) from failure
    except urllib.error.URLError as failure:
        raise FootballDataOrgAdapterError(
            "FOOTBALL_DATA_ORG_REQUEST_FAILED",
            "football-data.org request failed.",
            details={"endpoint": safe_endpoint_label(url), "reason": str(failure.reason)},
        ) from failure
    except (http.client.HTTPException, TimeoutError) as failure:
        raise FootballDataOrgAdapterError(
            "FOOTBALL_DATA_ORG_REQUEST_FAILED",
            "football-data.org request failed.",
            details={"endpoint": safe_endpoint_label(url), "reason": str(failure)},
        ) from failure

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as failure:
        raise FootballDataOrgAdapterError(
            "FOOTBALL_DATA_ORG_JSON_INVALID",
            "football-data.org response must be valid JSON.",
            details={"endpoint": safe_endpoint_label(url), "line": failure.lineno, "column": failure.colno},
        ) from failure
    return payload, throttling


def team_name(team):
    if not isinstance(team, dict):
        return None
    return team.get("name") or team.get("shortName") or team.get("tla")


def team_record(team):
    if not isinstance(team, dict):
        return {}
    return {
        "id": team.get("id"),
        "name": team_name(team),
        "shortName": team.get("shortName"),
        "tla": team.get("tla"),
    }


def match_id_for(match):
    provider_match_id = match.get("id")
    if provider_match_id not in (None, ""):
        return f"football-data-org:{provider_match_id}"
    teams = [team_name(match.get("homeTeam") or {}), team_name(match.get("awayTeam") or {})]
    kickoff = match.get("utcDate") or "unknown-kickoff"
    slug = "-".join(str(value or "tbd").lower().replace(" ", "-") for value in [*teams, kickoff])
    return f"football-data-org:{slug}"


def normalize_stage(stage):
    if not isinstance(stage, str):
        return None
    normalized = stage.strip().upper()
    return STAGE_MAP.get(normalized, normalized)


def normalize_period(status):
    if not isinstance(status, str):
        return "UNKNOWN"
    return PERIOD_BY_STATUS.get(status.strip().upper(), status.strip().upper())


def score_available(score):
    if not isinstance(score, dict):
        return False
    for key in ("fullTime", "regularTime", "extraTime", "penalties", "halfTime"):
        item = score.get(key)
        if isinstance(item, dict) and any(value is not None for value in item.values()):
            return True
    return bool(score.get("winner"))


def normalize_score_block(score, key):
    item = score.get(key) if isinstance(score, dict) else None
    if not isinstance(item, dict):
        return {"home": None, "away": None}
    return {"home": item.get("home"), "away": item.get("away")}


def normalize_fixture(match, competition=None, season=None):
    home = team_record(match.get("homeTeam") or {})
    away = team_record(match.get("awayTeam") or {})
    competition_payload = match.get("competition") if isinstance(match.get("competition"), dict) else {}
    season_payload = match.get("season") if isinstance(match.get("season"), dict) else {}
    return {
        "matchId": match_id_for(match),
        "providerMatchId": match.get("id"),
        "competitionCode": competition or competition_payload.get("code"),
        "season": str(season or season_payload.get("startDate", "")[:4] or DEFAULT_SEASON),
        "homeTeam": home.get("name"),
        "awayTeam": away.get("name"),
        "homeTeamId": home.get("id"),
        "awayTeamId": away.get("id"),
        "homeTeamTla": home.get("tla"),
        "awayTeamTla": away.get("tla"),
        "stage": normalize_stage(match.get("stage")),
        "group": match.get("group"),
        "matchday": match.get("matchday"),
        "venue": match.get("venue"),
        "kickoffAt": match.get("utcDate"),
        "sourceUpdatedAt": match.get("lastUpdated"),
    }


def normalize_kickoff(match):
    return {
        "matchId": match_id_for(match),
        "providerMatchId": match.get("id"),
        "kickoffAt": match.get("utcDate"),
        "timezone": "UTC",
        "sourceUpdatedAt": match.get("lastUpdated"),
    }


def normalize_match_status(match):
    status = str(match.get("status") or "UNKNOWN").upper()
    return {
        "matchId": match_id_for(match),
        "providerMatchId": match.get("id"),
        "status": status,
        "period": normalize_period(status),
        "sourceUpdatedAt": match.get("lastUpdated"),
    }


def normalize_scores(match):
    score = match.get("score") or {}
    if not score_available(score):
        return None
    return {
        "matchId": match_id_for(match),
        "providerMatchId": match.get("id"),
        "status": str(match.get("status") or "UNKNOWN").upper(),
        "winner": score.get("winner"),
        "duration": score.get("duration"),
        "fullTime": normalize_score_block(score, "fullTime"),
        "regularTime": normalize_score_block(score, "regularTime"),
        "extraTime": normalize_score_block(score, "extraTime"),
        "penalties": normalize_score_block(score, "penalties"),
        "halfTime": normalize_score_block(score, "halfTime"),
        "sourceUpdatedAt": match.get("lastUpdated"),
    }


def normalize_standing_row(row, group=None, stage=None):
    team = team_record(row.get("team") or {})
    return {
        "group": group,
        "stage": normalize_stage(stage),
        "team": team.get("name"),
        "teamId": team.get("id"),
        "teamTla": team.get("tla"),
        "position": row.get("position"),
        "playedGames": row.get("playedGames"),
        "won": row.get("won"),
        "draw": row.get("draw"),
        "lost": row.get("lost"),
        "points": row.get("points"),
        "goalsFor": row.get("goalsFor"),
        "goalsAgainst": row.get("goalsAgainst"),
        "goalDifference": row.get("goalDifference"),
    }


def normalize_standings(standings_payload):
    rows = []
    for standing in (standings_payload or {}).get("standings") or []:
        group = standing.get("group")
        stage = standing.get("stage")
        for row in standing.get("table") or []:
            rows.append(normalize_standing_row(row, group=group, stage=stage))
    return rows


def hash_vendor_payload(payload):
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def filter_matches(matches, match_id=None):
    if not match_id:
        return list(matches)
    wanted = str(match_id)
    result = []
    for match in matches:
        provider_match_id = str(match.get("id"))
        if wanted in {provider_match_id, match_id_for(match)}:
            result.append(match)
    return result


def build_structured_facts_payload(
    matches_payload,
    standings_payload=None,
    competition=DEFAULT_COMPETITION,
    season=DEFAULT_SEASON,
    snapshot_time=None,
    match_id=None,
    throttle_headers=None,
    standings_error=None,
):
    matches = filter_matches((matches_payload or {}).get("matches") or [], match_id=match_id)
    score_rows = [normalize_scores(match) for match in matches]
    raw_payload = {
        "matches": matches_payload,
        "standings": standings_payload or {},
    }
    payload = {
        "provider": {
            "providerId": FOOTBALL_DATA_ORG_PROVIDER_ID,
            "category": STRUCTURED_FACTS_CATEGORY,
            "mode": "api_adapter",
            "contractVersion": CONTRACT_VERSION,
            "productionReady": True,
        },
        "source": "football-data.org",
        "snapshotTime": snapshot_time or utc_now_iso(),
        "rawPayloadHash": hash_vendor_payload(raw_payload),
        "rawPayloadRef": f"football-data.org:{competition}:season:{season}",
        "auditContext": {
            "adapter": FOOTBALL_DATA_ORG_PROVIDER_ID,
            "competition": competition,
            "season": str(season),
            "matchFilter": match_id,
            "rateLimitHeaders": throttle_headers or {},
            "standingsFetch": "FAILED" if standings_error else "OK",
            "standingsErrorCode": getattr(standings_error, "code", None),
        },
        "facts": {
            "fixtures": [normalize_fixture(match, competition=competition, season=season) for match in matches],
            "kickoff_time": [normalize_kickoff(match) for match in matches],
            "match_status": [normalize_match_status(match) for match in matches],
            "official_lineups": [],
            "scores": [row for row in score_rows if row],
            "standings": normalize_standings(standings_payload),
            "cards": [],
            "market_odds_snapshots": [],
        },
    }
    validate_structured_facts_payload(payload)
    return payload


def fetch_worldcup_structured_facts_payload(
    token=None,
    base_url=None,
    competition=None,
    season=None,
    snapshot_time=None,
    match_id=None,
    timeout=DEFAULT_TIMEOUT_SECONDS,
    include_standings=True,
    allow_partial_standings=True,
    opener=None,
    environ=None,
):
    token = token if token is not None else env_value(FOOTBALL_DATA_ORG_TOKEN_ENV, environ=environ)
    base_url = base_url or env_value(FOOTBALL_DATA_ORG_BASE_URL_ENV, DEFAULT_BASE_URL, environ=environ)
    competition = competition or env_value(FOOTBALL_DATA_ORG_COMPETITION_ENV, DEFAULT_COMPETITION, environ=environ)
    season = str(season or env_value(FOOTBALL_DATA_ORG_SEASON_ENV, DEFAULT_SEASON, environ=environ))

    matches_url = build_competition_url(base_url, competition, "matches", {"season": season})
    matches_payload, match_headers = fetch_json(matches_url, token, timeout=timeout, opener=opener)

    standings_payload = {}
    standings_headers = {}
    standings_error = None
    if include_standings:
        standings_url = build_competition_url(base_url, competition, "standings", {"season": season})
        try:
            standings_payload, standings_headers = fetch_json(standings_url, token, timeout=timeout, opener=opener)
        except FootballDataOrgAdapterError as error:
            if not allow_partial_standings:
                raise
            standings_error = error

    return build_structured_facts_payload(
        matches_payload,
        standings_payload=standings_payload,
        competition=competition,
        season=season,
        snapshot_time=snapshot_time,
        match_id=match_id,
        throttle_headers={
            "matches": match_headers,
            "standings": standings_headers,
        },
        standings_error=standings_error,
    )
