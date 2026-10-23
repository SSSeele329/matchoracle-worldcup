import http.client
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request


API_FOOTBALL_PROVIDER_ID = "api_football"
API_FOOTBALL_KEY_ENVS = ("MATCHORACLE_API_FOOTBALL_KEY", "MATCHORACLE_API_SPORTS_KEY")
API_FOOTBALL_BASE_URL_ENV = "MATCHORACLE_API_FOOTBALL_BASE_URL"
API_FOOTBALL_LEAGUE_ENV = "MATCHORACLE_API_FOOTBALL_LEAGUE"
API_FOOTBALL_SEASON_ENV = "MATCHORACLE_API_FOOTBALL_SEASON"

DEFAULT_BASE_URL = "https://v3.football.api-sports.io"
DEFAULT_WORLD_CUP_LEAGUE = "1"
DEFAULT_WORLD_CUP_SEASON = "2026"
DEFAULT_TIMEOUT_SECONDS = 20
AVAILABILITY_CACHE_SECONDS = 6 * 60 * 60

AVAILABILITY_CACHE = {}


class ApiFootballAdapterError(ValueError):
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


def configured_token(environ=None):
    for name in API_FOOTBALL_KEY_ENVS:
        token = env_value(name, environ=environ)
        if token:
            return token
    return None


def safe_endpoint_label(url):
    parsed = urllib.parse.urlparse(url or "")
    if not parsed.scheme or not parsed.netloc:
        return "invalid-url"
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def build_api_football_url(base_url, path, params=None):
    query = urllib.parse.urlencode({
        key: value
        for key, value in (params or {}).items()
        if value not in (None, "")
    })
    url = f"{base_url.rstrip('/')}/{path.strip('/')}"
    return f"{url}?{query}" if query else url


def fetch_json(url, api_key, timeout=DEFAULT_TIMEOUT_SECONDS, opener=None):
    if not api_key:
        raise ApiFootballAdapterError(
            "API_FOOTBALL_TOKEN_MISSING",
            "API-Football token is required.",
            details={"env": list(API_FOOTBALL_KEY_ENVS), "endpoint": safe_endpoint_label(url)},
        )
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "x-apisports-key": api_key,
            "User-Agent": "MatchOracle-api-football-adapter/1.0",
        },
        method="GET",
    )
    opener = opener or urllib.request.urlopen
    try:
        with opener(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as failure:
        raise ApiFootballAdapterError(
            "API_FOOTBALL_HTTP_ERROR",
            "API-Football returned an HTTP error.",
            details={"status": failure.code, "endpoint": safe_endpoint_label(url)},
        ) from failure
    except urllib.error.URLError as failure:
        raise ApiFootballAdapterError(
            "API_FOOTBALL_REQUEST_FAILED",
            "API-Football request failed.",
            details={"endpoint": safe_endpoint_label(url), "reason": str(failure.reason)},
        ) from failure
    except (http.client.HTTPException, TimeoutError) as failure:
        raise ApiFootballAdapterError(
            "API_FOOTBALL_REQUEST_FAILED",
            "API-Football request failed.",
            details={"endpoint": safe_endpoint_label(url), "reason": str(failure)},
        ) from failure

    try:
        return json.loads(body)
    except json.JSONDecodeError as failure:
        raise ApiFootballAdapterError(
            "API_FOOTBALL_JSON_INVALID",
            "API-Football response must be valid JSON.",
            details={"endpoint": safe_endpoint_label(url), "line": failure.lineno, "column": failure.colno},
        ) from failure


def plan_blocked(errors):
    if not isinstance(errors, dict):
        return False
    return any("free plans do not have access" in str(value).lower() for value in errors.values())


def api_football_worldcup_availability(api_key=None, environ=None, opener=None):
    environ = environ if environ is not None else os.environ
    token = api_key or configured_token(environ)
    if not token:
        return {
            "connected": False,
            "keyConfigured": False,
            "mode": "TOKEN_MISSING",
            "requiredEnv": list(API_FOOTBALL_KEY_ENVS),
        }

    base_url = env_value(API_FOOTBALL_BASE_URL_ENV, DEFAULT_BASE_URL, environ=environ)
    league = env_value(API_FOOTBALL_LEAGUE_ENV, DEFAULT_WORLD_CUP_LEAGUE, environ=environ)
    season = env_value(API_FOOTBALL_SEASON_ENV, DEFAULT_WORLD_CUP_SEASON, environ=environ)
    url = build_api_football_url(base_url, "leagues", {"id": league, "season": season})
    payload = fetch_json(url, token, opener=opener)
    errors = payload.get("errors")
    if plan_blocked(errors):
        return {
            "connected": False,
            "keyConfigured": True,
            "mode": "PLAN_BLOCKED_FOR_2026_FREE",
            "requiredEnv": list(API_FOOTBALL_KEY_ENVS),
            "reason": "API-Football free plans do not expose World Cup 2026 data.",
        }
    if errors:
        return {
            "connected": False,
            "keyConfigured": True,
            "mode": "PROVIDER_ERROR",
            "requiredEnv": list(API_FOOTBALL_KEY_ENVS),
            "reason": "API-Football returned an error for the configured World Cup season.",
        }
    return {
        "connected": int(payload.get("results") or 0) > 0,
        "keyConfigured": True,
        "mode": "LIVE_API" if int(payload.get("results") or 0) > 0 else "NO_RESULTS",
        "requiredEnv": list(API_FOOTBALL_KEY_ENVS),
        "league": league,
        "season": season,
    }


def cached_api_football_worldcup_availability(environ=None):
    now = time.time()
    cached = AVAILABILITY_CACHE.get("status")
    if cached and AVAILABILITY_CACHE.get("expiresAt", 0) > now:
        return dict(cached)
    try:
        status = api_football_worldcup_availability(environ=environ)
    except ApiFootballAdapterError as error:
        status = {
            "connected": False,
            "keyConfigured": bool(configured_token(environ)),
            "mode": error.code,
            "requiredEnv": list(API_FOOTBALL_KEY_ENVS),
        }
    AVAILABILITY_CACHE["status"] = dict(status)
    AVAILABILITY_CACHE["expiresAt"] = now + AVAILABILITY_CACHE_SECONDS
    return status
