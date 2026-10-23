import http.client
import json
import os
import statistics
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


THE_ODDS_API_PROVIDER_ID = "the_odds_api"
THE_ODDS_API_BASE_URL_ENV = "MATCHORACLE_ODDS_API_BASE_URL"
THE_ODDS_API_TOKEN_ENVS = (
    "MATCHORACLE_THE_ODDS_API_KEY",
    "MATCHORACLE_ODDS_PROVIDER_TOKEN",
    "THE_ODDS_API_KEY",
)
THE_ODDS_API_SPORT_KEY_ENV = "MATCHORACLE_ODDS_SPORT_KEY"
THE_ODDS_API_REGIONS_ENV = "MATCHORACLE_ODDS_REGIONS"
THE_ODDS_API_MARKETS_ENV = "MATCHORACLE_ODDS_MARKETS"

DEFAULT_BASE_URL = "https://api.the-odds-api.com/v4"
DEFAULT_SPORT_KEY = "soccer_fifa_world_cup"
DEFAULT_REGIONS = "us"
DEFAULT_MARKETS = "h2h"
DEFAULT_TIMEOUT_SECONDS = 20


class TheOddsApiError(ValueError):
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
    source = environ if environ is not None else os.environ
    for name in THE_ODDS_API_TOKEN_ENVS:
        value = env_value(name, environ=source)
        if value:
            return value
    return None


def utc_now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def safe_endpoint_label(url):
    parsed = urllib.parse.urlparse(url or "")
    if not parsed.scheme or not parsed.netloc:
        return "invalid-url"
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def build_odds_url(base_url, sport_key, api_key, regions, markets):
    query = urllib.parse.urlencode({
        "apiKey": api_key,
        "regions": regions,
        "markets": markets,
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    })
    return f"{base_url.rstrip('/')}/sports/{urllib.parse.quote(str(sport_key), safe='')}/odds?{query}"


def fetch_json(url, timeout=DEFAULT_TIMEOUT_SECONDS, opener=None):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "MatchOracle-the-odds-api-adapter/1.0",
        },
        method="GET",
    )
    opener = opener or urllib.request.urlopen
    try:
        with opener(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            headers = getattr(response, "headers", {}) or {}
    except urllib.error.HTTPError as failure:
        raise TheOddsApiError(
            "THE_ODDS_API_HTTP_ERROR",
            "The Odds API returned an HTTP error.",
            details={"status": failure.code, "endpoint": safe_endpoint_label(url)},
        ) from failure
    except urllib.error.URLError as failure:
        raise TheOddsApiError(
            "THE_ODDS_API_REQUEST_FAILED",
            "The Odds API request failed.",
            details={"endpoint": safe_endpoint_label(url), "reason": str(failure.reason)},
        ) from failure
    except (http.client.HTTPException, TimeoutError) as failure:
        raise TheOddsApiError(
            "THE_ODDS_API_REQUEST_FAILED",
            "The Odds API request failed.",
            details={"endpoint": safe_endpoint_label(url), "reason": str(failure)},
        ) from failure

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as failure:
        raise TheOddsApiError(
            "THE_ODDS_API_JSON_INVALID",
            "The Odds API response must be valid JSON.",
            details={"endpoint": safe_endpoint_label(url), "line": failure.lineno, "column": failure.colno},
        ) from failure
    return payload, {key: str(value) for key, value in dict(headers).items()}


def outcome_price(outcomes, name):
    for outcome in outcomes or []:
        if str(outcome.get("name") or "").strip().lower() == str(name or "").strip().lower():
            try:
                price = float(outcome.get("price"))
            except (TypeError, ValueError):
                return None
            return price if price > 1 else None
    return None


def mean_decimal(values):
    values = [float(value) for value in values if value]
    if not values:
        return None
    return round(statistics.fmean(values), 3)


def consensus_h2h_odds(bookmakers, home_team, away_team):
    home_prices = []
    draw_prices = []
    away_prices = []
    last_updates = []
    bookmaker_count = 0
    for bookmaker in bookmakers or []:
        h2h_market = next((market for market in bookmaker.get("markets") or [] if market.get("key") == "h2h"), None)
        if not h2h_market:
            continue
        outcomes = h2h_market.get("outcomes") or []
        home_price = outcome_price(outcomes, home_team)
        draw_price = outcome_price(outcomes, "Draw")
        away_price = outcome_price(outcomes, away_team)
        if home_price and draw_price and away_price:
            home_prices.append(home_price)
            draw_prices.append(draw_price)
            away_prices.append(away_price)
            bookmaker_count += 1
            if bookmaker.get("last_update"):
                last_updates.append(bookmaker["last_update"])
    if not bookmaker_count:
        return None
    return {
        "decimalOdds": {
            "home": mean_decimal(home_prices),
            "draw": mean_decimal(draw_prices),
            "away": mean_decimal(away_prices),
        },
        "bookmakerCount": bookmaker_count,
        "lastUpdate": max(last_updates) if last_updates else None,
    }


def normalize_odds_event(event, snapshot_time):
    home_team = event.get("home_team")
    away_team = event.get("away_team")
    consensus = consensus_h2h_odds(event.get("bookmakers"), home_team, away_team)
    if not home_team or not away_team or not consensus:
        return None
    return {
        "provider": THE_ODDS_API_PROVIDER_ID,
        "providerEventId": event.get("id"),
        "sportKey": event.get("sport_key"),
        "kickoffAt": event.get("commence_time"),
        "homeTeam": home_team,
        "awayTeam": away_team,
        "decimalOdds": consensus["decimalOdds"],
        "snapshotTime": consensus.get("lastUpdate") or snapshot_time,
        "source": f"{THE_ODDS_API_PROVIDER_ID}:consensus:{consensus['bookmakerCount']}",
        "bookmakerCount": consensus["bookmakerCount"],
    }


def fetch_the_odds_api_snapshots(
    api_key=None,
    sport_key=None,
    regions=None,
    markets=None,
    base_url=None,
    timeout=DEFAULT_TIMEOUT_SECONDS,
    opener=None,
    environ=None,
):
    source = environ if environ is not None else os.environ
    token = api_key or configured_token(environ=source)
    if not token:
        raise TheOddsApiError(
            "THE_ODDS_API_TOKEN_MISSING",
            "The Odds API token is required.",
            details={"env": list(THE_ODDS_API_TOKEN_ENVS)},
        )
    resolved_base_url = base_url or env_value(THE_ODDS_API_BASE_URL_ENV, DEFAULT_BASE_URL, environ=source)
    resolved_sport_key = sport_key or env_value(THE_ODDS_API_SPORT_KEY_ENV, DEFAULT_SPORT_KEY, environ=source)
    resolved_regions = regions or env_value(THE_ODDS_API_REGIONS_ENV, DEFAULT_REGIONS, environ=source)
    resolved_markets = markets or env_value(THE_ODDS_API_MARKETS_ENV, DEFAULT_MARKETS, environ=source)
    url = build_odds_url(resolved_base_url, resolved_sport_key, token, resolved_regions, resolved_markets)
    payload, headers = fetch_json(url, timeout=timeout, opener=opener)
    snapshot_time = utc_now_iso()
    events = payload if isinstance(payload, list) else []
    snapshots = [
        snapshot
        for snapshot in (normalize_odds_event(event, snapshot_time) for event in events)
        if snapshot
    ]
    return {
        "provider": THE_ODDS_API_PROVIDER_ID,
        "sportKey": resolved_sport_key,
        "regions": resolved_regions,
        "markets": resolved_markets,
        "snapshotTime": snapshot_time,
        "requestHeaders": {
            key: headers[key]
            for key in headers
            if key.lower() in {"x-requests-remaining", "x-requests-used", "x-requests-last"}
        },
        "snapshots": snapshots,
    }
