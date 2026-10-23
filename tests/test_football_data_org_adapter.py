import http.client
import json
import urllib.error

import pytest

from src.worldcup.football_data_org_adapter import (
    FOOTBALL_DATA_ORG_PROVIDER_ID,
    FootballDataOrgAdapterError,
    build_competition_url,
    build_structured_facts_payload,
    fetch_worldcup_structured_facts_payload,
)
from src.worldcup.provider_adapter_acceptance import (
    find_inline_raw_payload_paths,
    find_sensitive_field_paths,
    validate_provider_adapter_output,
)


class FakeResponse:
    def __init__(self, payload, headers=None):
        self.payload = payload
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def matches_payload():
    return {
        "matches": [
            {
                "id": 1,
                "utcDate": "2026-06-12T19:00:00Z",
                "status": "FINISHED",
                "matchday": 1,
                "stage": "GROUP_STAGE",
                "group": "Group A",
                "lastUpdated": "2026-06-12T21:00:00Z",
                "homeTeam": {"id": 101, "name": "Mexico", "shortName": "Mexico", "tla": "MEX"},
                "awayTeam": {"id": 102, "name": "South Africa", "shortName": "South Africa", "tla": "RSA"},
                "score": {
                    "winner": "HOME_TEAM",
                    "duration": "REGULAR",
                    "fullTime": {"home": 2, "away": 0},
                    "halfTime": {"home": 1, "away": 0},
                },
            },
            {
                "id": 2,
                "utcDate": "2026-06-13T01:00:00Z",
                "status": "TIMED",
                "matchday": 1,
                "stage": "GROUP_STAGE",
                "group": "Group A",
                "homeTeam": {"id": 103, "name": "Canada", "shortName": "Canada", "tla": "CAN"},
                "awayTeam": {"id": 104, "name": "Brazil", "shortName": "Brazil", "tla": "BRA"},
                "score": {"winner": None, "duration": "REGULAR", "fullTime": {"home": None, "away": None}},
            },
        ]
    }


def standings_payload():
    return {
        "standings": [
            {
                "stage": "GROUP_STAGE",
                "group": "Group A",
                "table": [
                    {
                        "position": 1,
                        "team": {"id": 101, "name": "Mexico", "tla": "MEX"},
                        "playedGames": 1,
                        "won": 1,
                        "draw": 0,
                        "lost": 0,
                        "points": 3,
                        "goalsFor": 2,
                        "goalsAgainst": 0,
                        "goalDifference": 2,
                    }
                ],
            }
        ]
    }


def test_build_competition_url_encodes_query_params():
    url = build_competition_url("https://api.football-data.org/v4/", "WC", "matches", {"season": 2026})

    assert url == "https://api.football-data.org/v4/competitions/WC/matches?season=2026"


def test_adapter_builds_contract_payload_without_raw_or_sensitive_fields():
    payload = build_structured_facts_payload(
        matches_payload(),
        standings_payload=standings_payload(),
        snapshot_time="2026-06-13T00:00:00+00:00",
    )

    result = validate_provider_adapter_output(
        payload,
        expected_provider_id=FOOTBALL_DATA_ORG_PROVIDER_ID,
        required_fact_keys=["fixtures", "kickoff_time", "match_status", "standings"],
    )

    assert result["status"] == "PASS"
    assert result["factCounts"]["fixtures"] == 2
    assert result["factCounts"]["scores"] == 1
    assert payload["facts"]["fixtures"][0]["matchId"] == "football-data-org:1"
    assert payload["facts"]["match_status"][1]["period"] == "PREMATCH"
    assert payload["facts"]["scores"][0]["fullTime"] == {"home": 2, "away": 0}
    assert payload["facts"]["standings"][0]["team"] == "Mexico"
    assert find_sensitive_field_paths(payload) == []
    assert find_inline_raw_payload_paths(payload) == []


def test_adapter_can_filter_to_one_match():
    payload = build_structured_facts_payload(
        matches_payload(),
        standings_payload=standings_payload(),
        snapshot_time="2026-06-13T00:00:00+00:00",
        match_id="2",
    )

    assert [row["providerMatchId"] for row in payload["facts"]["fixtures"]] == [2]
    assert payload["facts"]["scores"] == []


def test_fetch_worldcup_payload_uses_x_auth_token_and_captures_throttling_headers():
    calls = []

    def opener(request, timeout=20):
        calls.append((request, timeout))
        if request.full_url.endswith("/matches?season=2026"):
            return FakeResponse(matches_payload(), headers={"X-Requests-Available-Minute": "9"})
        return FakeResponse(standings_payload(), headers={"X-RequestCounter-Reset": "60"})

    payload = fetch_worldcup_structured_facts_payload(
        token="secret-token",
        snapshot_time="2026-06-13T00:00:00+00:00",
        opener=opener,
    )

    assert calls[0][0].headers["X-auth-token"] == "secret-token"
    assert calls[0][1] == 20
    assert payload["auditContext"]["rateLimitHeaders"]["matches"] == {"X-Requests-Available-Minute": "9"}
    assert payload["auditContext"]["rateLimitHeaders"]["standings"] == {"X-RequestCounter-Reset": "60"}
    assert find_sensitive_field_paths(payload) == []


def test_fetch_worldcup_payload_can_degrade_when_standings_fail():
    def opener(request, timeout=20):
        if request.full_url.endswith("/matches?season=2026"):
            return FakeResponse(matches_payload())
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", hdrs=None, fp=None)

    payload = fetch_worldcup_structured_facts_payload(
        token="secret-token",
        snapshot_time="2026-06-13T00:00:00+00:00",
        opener=opener,
    )

    assert payload["facts"]["fixtures"]
    assert payload["facts"]["standings"] == []
    assert payload["auditContext"]["standingsFetch"] == "FAILED"
    assert payload["auditContext"]["standingsErrorCode"] == "FOOTBALL_DATA_ORG_HTTP_ERROR"


def test_fetch_worldcup_payload_can_require_standings():
    def opener(request, timeout=20):
        if request.full_url.endswith("/matches?season=2026"):
            return FakeResponse(matches_payload())
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", hdrs=None, fp=None)

    with pytest.raises(FootballDataOrgAdapterError) as error:
        fetch_worldcup_structured_facts_payload(
            token="secret-token",
            allow_partial_standings=False,
            opener=opener,
        )

    assert error.value.code == "FOOTBALL_DATA_ORG_HTTP_ERROR"


def test_fetch_worldcup_payload_wraps_remote_disconnect():
    def opener(request, timeout=20):
        raise http.client.RemoteDisconnected("Remote end closed connection without response")

    with pytest.raises(FootballDataOrgAdapterError) as error:
        fetch_worldcup_structured_facts_payload(token="secret-token", opener=opener)

    assert error.value.code == "FOOTBALL_DATA_ORG_REQUEST_FAILED"
    assert "secret-token" not in str(error.value.details)


def test_fetch_worldcup_payload_requires_token():
    with pytest.raises(FootballDataOrgAdapterError) as error:
        fetch_worldcup_structured_facts_payload(token="", opener=lambda request, timeout=20: None)

    assert error.value.code == "FOOTBALL_DATA_ORG_TOKEN_MISSING"
    assert "secret" not in str(error.value.details).lower()
