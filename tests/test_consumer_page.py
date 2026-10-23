from app import app
from src.worldcup.api_football_adapter import AVAILABILITY_CACHE
from src.worldcup.provider_contracts import STRUCTURED_FACTS_CATEGORY
from src.worldcup.structured_facts_store import ingest_structured_facts_payload


def isolate_structured_facts_store(monkeypatch, tmp_path):
    store_path = tmp_path / "structured_facts.sqlite3"
    monkeypatch.setenv("MATCHORACLE_STRUCTURED_FACTS_STORE", str(store_path))
    return store_path


def test_consumer_home_page_is_delivery_experience_not_manual_dashboard():
    response = app.test_client().get("/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "MatchOracle 世界杯预测中心" in html
    assert "/api/featured-matches" in html
    assert "/api/predict" in html
    assert "全部已接入赛事" in html
    assert "fixture-rail" in html
    assert "match-deck" in html
    assert "match-visual" in html
    assert "probability-strip" in html
    assert "form-dot" in html
    assert "必须展示" in html
    assert "展开查看" in html
    assert "languageToggle" in html
    assert "sourceBadges" in html
    assert "模型因素" in html
    assert "关键球员" in html
    assert "爆冷风险" in html
    assert "出线动机" in html
    assert "AUTO_REFRESH_MS" in html
    assert "setInterval" in html
    assert "数据源状态" in html
    assert "MATCHORACLE_FOOTBALL_DATA_ORG_TOKEN" not in html
    assert "付费内容" not in html
    assert "杯赛通行证" not in html
    assert "付费位已预留" not in html
    assert "实时源接入中" not in html
    assert "DEMO_READY" not in html
    assert "Ops board" not in html
    assert "主队FIFA排名" not in html
    assert "id=\"homeRank\"" not in html
    assert "function renderBackgroundExecution" not in html


def test_consumer_page_labels_scorelines_and_market_as_separate_probability_scopes():
    html = app.test_client().get("/").get_data(as_text=True)

    assert "胜平负使用同一组 canonical 概率" in html
    assert "比分列表展示单个比分概率" in html
    assert "市场隐含概率单独展示" in html
    assert "Scoreline probability" in html
    assert "function hasCanonicalProbabilities" in html
    assert "numberText(best.evPercent" not in html
    assert "valueSide" in html


def test_consumer_page_percent_display_handles_values_already_in_percent_units():
    html = app.test_client().get("/").get_data(as_text=True)

    assert "const normalized = number > 1 && number <= 100 ? number / 100 : number;" in html
    assert "function probabilityWidth(value)" in html


def test_featured_matches_feed_contains_flags_players_prediction_payloads_and_fallback_status(monkeypatch, tmp_path):
    isolate_structured_facts_store(monkeypatch, tmp_path)
    monkeypatch.delenv("MATCHORACLE_API_FOOTBALL_KEY", raising=False)
    monkeypatch.delenv("MATCHORACLE_API_SPORTS_KEY", raising=False)
    AVAILABILITY_CACHE.clear()

    response = app.test_client().get("/api/featured-matches")
    payload = response.get_json()
    first = payload["sampleMatches"][0]

    assert response.status_code == 200
    assert payload["feedStatus"]["sourceMode"] == "FALLBACK_STATIC_SAMPLE"
    assert payload["feedStatus"]["fallback"] is True
    assert payload["matches"] == []
    assert payload["sampleMatches"]
    assert payload["feedStatus"]["primaryBlocker"] in {"FOOTBALL_DATA_ORG_TOKEN_MISSING", "STRUCTURED_FACTS_EMPTY"}
    assert "connected" in payload["feedStatus"]["apiConnections"]["footballDataOrg"]
    assert "connected" in payload["feedStatus"]["apiConnections"]["theOddsApi"]
    assert payload["feedStatus"]["apiConnections"]["lineupProvider"]["mode"] == "TOKEN_MISSING"
    assert payload["feedStatus"]["apiConnections"]["apiFootball"]["role"] == "lineups_injuries_players"
    assert payload["tournament"]["path"]
    assert first["isDemoData"] is True
    assert first["sourceStatus"]["mode"] == "FALLBACK_STATIC_SAMPLE"
    assert first["home"]["flag"]
    assert first["away"]["flag"]
    assert first["home"]["nameZh"]
    assert first["lineups"]["homePlayers"]
    assert first["lineups"]["awayPlayers"]
    assert first["predictionPayload"]["match"]["homeTeam"] == first["home"]["name"]
    assert first["predictionPayload"]["expectedLineup"]["homeStarters"]


def test_featured_matches_feed_reads_verified_structured_facts(monkeypatch, tmp_path):
    store_path = isolate_structured_facts_store(monkeypatch, tmp_path)
    ingest_structured_facts_payload(
        {
            "provider": {
                "category": STRUCTURED_FACTS_CATEGORY,
                "providerId": "football-data.org",
            },
            "source": "football-data.org",
            "snapshotTime": "2026-06-13T08:00:00+00:00",
            "auditContext": {"requestId": "consumer-feed-test"},
            "facts": {
                "fixtures": [{
                    "matchId": "football-data-org:100",
                    "providerMatchId": 100,
                    "homeTeam": "Brazil",
                    "awayTeam": "Morocco",
                    "stage": "GROUP_STAGE",
                    "group": "Group F",
                    "matchday": 1,
                    "kickoffAt": "2026-06-18T20:00:00+00:00",
                    "venue": "MetLife Stadium",
                }, {
                    "matchId": "football-data-org:200",
                    "providerMatchId": 200,
                    "homeTeam": None,
                    "awayTeam": None,
                    "stage": "ROUND_OF_32",
                    "group": None,
                    "matchday": None,
                    "kickoffAt": "2026-06-29T20:00:00+00:00",
                    "venue": None,
                }],
                "match_status": [{
                    "matchId": "football-data-org:100",
                    "status": "FINISHED",
                }, {
                    "matchId": "football-data-org:200",
                    "status": "TIMED",
                }],
                "scores": [{
                    "matchId": "football-data-org:100",
                    "status": "FINISHED",
                    "winner": "HOME_TEAM",
                    "duration": "REGULAR",
                    "fullTime": {"home": 2, "away": 1},
                }],
                "official_lineups": [{
                    "matchId": "football-data-org:100",
                    "homeFormation": "4-3-3",
                    "awayFormation": "4-2-3-1",
                    "homeStarters": [
                        {"name": "Alisson", "role": "GK", "tier": "TIER_1"},
                        {"name": "Vinicius Junior", "role": "LW", "tier": "TIER_1"},
                    ],
                    "awayStarters": ["Bono", "Achraf Hakimi"],
                }],
                "standings": [
                    {"group": "Group F", "team": "Brazil", "position": 1, "playedGames": 0, "points": 0, "goalDifference": 0},
                    {"group": "Group F", "team": "Morocco", "position": 2, "playedGames": 0, "points": 0, "goalDifference": 0},
                ],
            },
        },
        path=str(store_path),
        created_by="consumer-test",
    )

    response = app.test_client().get("/api/featured-matches?limit=4")
    payload = response.get_json()
    first = payload["matches"][0]

    assert response.status_code == 200
    assert payload["feedStatus"]["sourceMode"] == "LIVE_STRUCTURED_FACTS"
    assert payload["feedStatus"]["fallback"] is False
    assert "apiConnections" in payload["feedStatus"]
    assert len(payload["matches"]) == 2
    assert first["id"] == "football-data-org:100"
    assert first.get("isDemoData") is None
    assert first["home"]["nameZh"] == "巴西"
    assert first["away"]["nameZh"] == "摩洛哥"
    assert first["score"] == {"home": 2, "away": 1, "winner": "HOME_TEAM", "status": "FINISHED", "duration": "REGULAR"}
    assert first["lineups"]["homeFormation"] == "4-3-3"
    assert first["lineups"]["homePlayers"][0]["name"] == "Alisson"
    assert first["lineups"]["homePlayers"][0]["role"] == "GK"
    assert first["lineups"]["awayPlayers"][0]["name"] == "Bono"
    assert first["predictionPayload"]["expectedLineup"]["homeStarters"] == ["Alisson", "Vinicius Junior"]
    assert first["predictionPayload"]["expectedLineup"]["awayStarters"] == ["Bono", "Achraf Hakimi"]
    assert first["predictionPayload"]["inputQuality"]["lineup"] == "OFFICIAL_LINEUPS"
    assert all(item in {"W", "D", "L"} for item in first["home"]["form"].split("-") if item)
    assert payload["matches"][1]["predictionAvailable"] is False
    assert payload["matches"][1]["displayTitle"].startswith("M2")
    assert first["sourceStatus"]["mode"] == "LIVE_STRUCTURED_FACTS"
    assert first["predictionPayload"]["inputQuality"]["fixture"] == "STRUCTURED_FACTS"
    assert payload["tournament"]["groups"][0]["label"] == "F组"


def test_featured_match_payload_runs_through_prediction_api(monkeypatch, tmp_path):
    isolate_structured_facts_store(monkeypatch, tmp_path)
    matches = app.test_client().get("/api/featured-matches").get_json()["sampleMatches"]
    response = app.test_client().post("/api/predict", json=matches[0]["predictionPayload"])
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["probabilities"]
    assert payload["scorePrediction"]["predicted"]
    assert payload["upsetRisk"]["upsetRiskLevel"] in {"LOW", "MEDIUM", "HIGH"}
