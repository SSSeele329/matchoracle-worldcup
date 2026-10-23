from src.worldcup import WorldCupPredictor
from src.worldcup.upset_risk import build_upset_risk


def test_upset_risk_stays_low_without_clear_favorite():
    risk = build_upset_risk(
        {"match": {"homeTeam": "A", "awayTeam": "B", "stage": "GROUP_STAGE"}},
        {"home": 0.39, "draw": 0.28, "away": 0.33},
    )

    assert risk["upsetRiskLevel"] == "LOW"
    assert risk["clearFavorite"] is False
    assert risk["riskFlags"] == []


def test_upset_risk_flags_favorite_rotation_and_underdog_pressure():
    risk = build_upset_risk(
        {
            "match": {"homeTeam": "Favorite", "awayTeam": "Underdog", "stage": "GROUP_STAGE", "matchday": 3},
            "matchContext": {
                "homeQualificationStatus": "ALREADY_QUALIFIED",
                "awayQualificationStatus": "MUST_WIN",
                "homeRotationRisk": 0.55,
                "awayMustWinPressure": 0.52,
                "awayMotivationScore": 3.1,
                "homeMotivationScore": 0.4,
                "pathIncentiveRisk": 0.4,
                "matchDrawIncentive": 0.3,
            },
            "goalData": {
                "home": {"setpieceRate": 0.21},
                "away": {"setpieceRate": 0.34},
            },
            "decimalOdds": {"home": 1.45, "draw": 4.3, "away": 7.5},
            "publicTicketPercent": {"home": 72, "draw": 12, "away": 16},
        },
        {"home": 0.63, "draw": 0.22, "away": 0.15},
        market_analysis={"probabilities": {"home": 0.70, "draw": 0.20, "away": 0.10}},
    )

    assert risk["upsetRiskLevel"] == "HIGH"
    assert risk["favoriteTeam"] == "Favorite"
    assert "FAVORITE_ALREADY_QUALIFIED" in risk["riskFlags"]
    assert "UNDERDOG_MUST_TAKE_POINTS" in risk["riskFlags"]
    assert "SETPIECE_VOLATILITY" in risk["riskFlags"]
    assert risk["confidencePenalty"] == 12


def test_predictor_outputs_upset_risk_without_changing_probability_shape():
    result = WorldCupPredictor().predict({
        "matchId": "upset-layer-test",
        "match": {"homeTeam": "Favorite", "awayTeam": "Underdog", "stage": "GROUP_STAGE", "matchday": 3},
        "teamData": {"home": {"fifaRank": 2}, "away": {"fifaRank": 45}},
        "matchContext": {
            "homeQualificationStatus": "ALREADY_QUALIFIED",
            "awayQualificationStatus": "MUST_WIN",
            "homeRotationRisk": 0.5,
            "awayMustWinPressure": 0.5,
            "awayMotivationScore": 3.0,
            "homeMotivationScore": 0.5,
        },
        "goalData": {
            "home": {"actualGoals_avg": 2.0, "xGA_avg": 0.8, "setpieceRate": 0.20},
            "away": {"actualGoals_avg": 0.9, "xGA_avg": 1.7, "setpieceRate": 0.34},
        },
    })

    assert "upsetRisk" in result
    assert result["upsetRisk"]["upsetRiskLevel"] in {"MEDIUM", "HIGH"}
    assert any(flag.startswith("爆冷风险层：") for flag in result["riskFlags"])
    assert result["finalRiskNarrative"]["primaryDriver"] in {
        "UPSET_RISK",
        "DATA_RELIABILITY_DROP",
        "WAIT_FOR_LINEUP",
    }
