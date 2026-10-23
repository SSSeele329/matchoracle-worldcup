import json
import urllib.error

import pytest

from src.worldcup.the_odds_api_adapter import (
    TheOddsApiError,
    fetch_the_odds_api_snapshots,
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


def test_the_odds_api_normalizes_consensus_h2h_decimal_odds():
    def opener(request, timeout=20):
        assert "apiKey=secret-token" in request.full_url
        assert "markets=h2h" in request.full_url
        return FakeResponse([
            {
                "id": "event-1",
                "sport_key": "soccer_fifa_world_cup",
                "commence_time": "2026-06-14T19:00:00Z",
                "home_team": "Qatar",
                "away_team": "Switzerland",
                "bookmakers": [{
                    "key": "book_a",
                    "last_update": "2026-06-14T10:00:00Z",
                    "markets": [{
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Qatar", "price": 4.2},
                            {"name": "Draw", "price": 3.4},
                            {"name": "Switzerland", "price": 1.92},
                        ],
                    }],
                }, {
                    "key": "book_b",
                    "last_update": "2026-06-14T10:05:00Z",
                    "markets": [{
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Qatar", "price": 4.0},
                            {"name": "Draw", "price": 3.5},
                            {"name": "Switzerland", "price": 1.95},
                        ],
                    }],
                }],
            }
        ])

    payload = fetch_the_odds_api_snapshots(api_key="secret-token", opener=opener)

    assert payload["sportKey"] == "soccer_fifa_world_cup"
    assert len(payload["snapshots"]) == 1
    snapshot = payload["snapshots"][0]
    assert snapshot["homeTeam"] == "Qatar"
    assert snapshot["awayTeam"] == "Switzerland"
    assert snapshot["decimalOdds"] == {"home": 4.1, "draw": 3.45, "away": 1.935}
    assert snapshot["snapshotTime"] == "2026-06-14T10:05:00Z"
    assert snapshot["bookmakerCount"] == 2


def test_the_odds_api_errors_do_not_expose_token():
    def opener(request, timeout=20):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", hdrs=None, fp=None)

    with pytest.raises(TheOddsApiError) as error:
        fetch_the_odds_api_snapshots(api_key="secret-token", opener=opener)

    assert error.value.code == "THE_ODDS_API_HTTP_ERROR"
    assert "secret-token" not in str(error.value.details)
