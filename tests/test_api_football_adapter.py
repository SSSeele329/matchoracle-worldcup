import json

from src.worldcup.api_football_adapter import api_football_worldcup_availability


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_api_football_availability_reports_free_plan_2026_block():
    def opener(request, timeout=20):
        assert request.headers["X-apisports-key"] == "secret-token"
        assert "season=2026" in request.full_url
        return FakeResponse({
            "results": 0,
            "errors": {"plan": "Free plans do not have access to this season, try from 2022 to 2024."},
            "response": [],
        })

    status = api_football_worldcup_availability(api_key="secret-token", opener=opener)

    assert status["connected"] is False
    assert status["keyConfigured"] is True
    assert status["mode"] == "PLAN_BLOCKED_FOR_2026_FREE"
    assert "free plans" in status["reason"].lower()


def test_api_football_availability_reports_live_api_when_worldcup_available():
    def opener(request, timeout=20):
        return FakeResponse({
            "results": 1,
            "errors": [],
            "response": [{"league": {"id": 1, "name": "World Cup"}}],
        })

    status = api_football_worldcup_availability(api_key="secret-token", opener=opener)

    assert status["connected"] is True
    assert status["mode"] == "LIVE_API"
