import math

from src.evaluation_metrics import (
    brier_score,
    calibration_buckets,
    compare_with_baselines,
    draw_diagnostics,
    log_loss,
    summarize_probability_metrics,
)
from src.cross_validate_worldcups import (
    apply_draw_aware_probability_calibration,
    build_calibration_decision_gate,
    evaluate_calibration_candidate,
    flatten_match_row,
    render_cross_validation_markdown,
)

MOCK_ROWS = [
    {
        "actualResult": "HOME_WIN",
        "predictedResult": "HOME_WIN",
        "probabilities": {"home": 0.7, "draw": 0.2, "away": 0.1},
        "baselines": {
            "simpleFavorite": {"probabilities": {"home": 0.5, "draw": 0.25, "away": 0.25}, "predictedResult": "HOME_WIN"},
            "eloRank": {"probabilities": {"home": 0.6, "draw": 0.2, "away": 0.2}, "predictedResult": "HOME_WIN"},
        },
    },
    {
        "actualResult": "DRAW",
        "predictedResult": "DRAW",
        "probabilities": {"home": 0.4, "draw": 0.4, "away": 0.2},
        "baselines": {
            "simpleFavorite": {"probabilities": {"home": 0.4, "draw": 0.3, "away": 0.3}, "predictedResult": "HOME_WIN"},
            "eloRank": {"probabilities": {"home": 0.45, "draw": 0.3, "away": 0.25}, "predictedResult": "HOME_WIN"},
        },
    },
    {
        "actualResult": "AWAY_WIN",
        "predictedResult": "AWAY_WIN",
        "probabilities": {"home": 0.1, "draw": 0.2, "away": 0.7},
        "baselines": {
            "simpleFavorite": {"probabilities": {"home": 0.2, "draw": 0.3, "away": 0.5}, "predictedResult": "AWAY_WIN"},
            "eloRank": {"probabilities": {"home": 0.2, "draw": 0.2, "away": 0.6}, "predictedResult": "AWAY_WIN"},
        },
    },
]

def test_brier_score():
    # HOME_WIN prediction, HOME_WIN actual
    score1 = brier_score({"home": 0.7, "draw": 0.2, "away": 0.1}, "HOME_WIN")
    assert round(score1, 2) == round((0.7-1)**2 + (0.2-0)**2 + (0.1-0)**2, 2)

    # DRAW prediction, AWAY_WIN actual
    score2 = brier_score({"home": 0.4, "draw": 0.4, "away": 0.2}, "AWAY_WIN")
    assert round(score2, 2) == round((0.4-0)**2 + (0.4-0)**2 + (0.2-1)**2, 2)

def test_log_loss():
    loss1 = log_loss({"home": 0.7, "draw": 0.2, "away": 0.1}, "HOME_WIN")
    assert round(loss1, 4) == round(-math.log(0.7), 4)

    loss2 = log_loss({"home": 0.4, "draw": 0.4, "away": 0.2}, "DRAW")
    assert round(loss2, 4) == round(-math.log(0.4), 4)

def test_summarize_probability_metrics():
    metrics = summarize_probability_metrics(MOCK_ROWS)
    assert "brierScore" in metrics
    assert "logLoss" in metrics
    assert metrics["brierScore"] > 0
    assert metrics["logLoss"] > 0

def test_calibration_buckets():
    buckets = calibration_buckets(MOCK_ROWS)
    assert len(buckets) > 0
    for bucket in buckets:
        assert "bucket" in bucket
        assert "matches" in bucket
        assert "averageConfidence" in bucket
        assert "observedAccuracy" in bucket
        assert "calibrationError" in bucket

def test_compare_with_baselines():
    comparison = compare_with_baselines(MOCK_ROWS)
    assert "model" in comparison
    assert "simpleFavorite" in comparison
    assert "eloRank" in comparison
    assert "calibrationBuckets" in comparison
    assert "drawDiagnostics" in comparison
    assert comparison["model"]["brierScore"] < comparison["simpleFavorite"]["brierScore"]
    assert comparison["model"]["logLoss"] < comparison["simpleFavorite"]["logLoss"]
    assert comparison["eloRank"]["brierScore"] > 0
    assert comparison["eloRank"]["logLoss"] > 0


def test_draw_diagnostics_counts_draw_headlines_and_probability():
    diagnostics = draw_diagnostics(MOCK_ROWS)
    assert diagnostics["predictedDraws"] == 1
    assert diagnostics["actualDraws"] == 1
    assert diagnostics["predictedDrawRate"] == 0.3333
    assert diagnostics["actualDrawRate"] == 0.3333
    assert diagnostics["averageDrawProbability"] > 0
    assert diagnostics["actualDrawAverageProbability"] == 0.4


def test_draw_aware_calibration_promotes_only_close_draw_candidate():
    close = apply_draw_aware_probability_calibration(
        {"home": 0.39, "draw": 0.38, "away": 0.23},
        {
            "favoriteExponent": 1.0,
            "drawMultiplier": 1.0,
            "favoriteBoost": 0.0,
            "drawCandidateMargin": 0.02,
            "minDrawProbability": 0.30,
            "drawPromotionEpsilon": 0.001,
        },
    )
    far = apply_draw_aware_probability_calibration(
        {"home": 0.50, "draw": 0.25, "away": 0.25},
        {
            "favoriteExponent": 1.0,
            "drawMultiplier": 1.0,
            "favoriteBoost": 0.0,
            "drawCandidateMargin": 0.02,
            "minDrawProbability": 0.30,
            "drawPromotionEpsilon": 0.001,
        },
    )
    assert close["draw"] > close["home"]
    assert far["home"] > far["draw"]


def gate_summary(brier, loss, predicted_draw_rate, weighted_error=0.05, max_error=0.09):
    matches = 256
    actual_draw_rate = 0.25
    return {
        "matches": matches,
        "resultHits": 140,
        "resultAccuracy": 0.5469,
        "top5ScoreHits": 0,
        "top5ScoreCoverage": 0,
        "predictedResultDistribution": {
            "HOME_WIN": 128,
            "DRAW": round(matches * predicted_draw_rate),
            "AWAY_WIN": 128 - round(matches * predicted_draw_rate),
        },
        "actualResultDistribution": {"HOME_WIN": 96, "DRAW": 64, "AWAY_WIN": 96},
        "probabilityMetrics": {"brierScore": brier, "logLoss": loss},
        "baselineComparison": {
            "simpleFavorite": {"resultAccuracy": 0.55, "brierScore": 0.60, "logLoss": 1.00},
            "eloRank": {"resultAccuracy": 0.55, "brierScore": 0.59, "logLoss": 0.99},
            "calibrationBuckets": [
                {
                    "bucket": "0.4-0.5",
                    "matches": 128,
                    "averageConfidence": 0.45,
                    "observedAccuracy": 0.50,
                    "calibrationError": weighted_error,
                },
                {
                    "bucket": "0.5-0.6",
                    "matches": 128,
                    "averageConfidence": 0.55,
                    "observedAccuracy": 0.46,
                    "calibrationError": max_error,
                },
            ],
            "drawDiagnostics": {
                "matches": matches,
                "predictedDraws": round(matches * predicted_draw_rate),
                "predictedDrawRate": predicted_draw_rate,
                "actualDraws": 64,
                "actualDrawRate": actual_draw_rate,
                "averageDrawProbability": 0.25,
                "actualDrawAverageProbability": 0.26,
            },
        },
    }


def test_calibration_decision_gate_approves_only_candidates_passing_all_guards():
    baseline_summary = gate_summary(0.61, 1.02, 0.15)
    approved_summary = gate_summary(0.58, 0.98, 0.15)
    zero_draw_summary = gate_summary(0.58, 0.98, 0.0)

    approved = evaluate_calibration_candidate("Approved Candidate", approved_summary, baseline_summary)
    rejected = evaluate_calibration_candidate("Zero Draw Candidate", zero_draw_summary, baseline_summary)

    assert approved["approvedForCanonical"]
    assert rejected["status"] == "REJECTED_DIAGNOSTIC_ONLY"
    assert "draw headline rate floor" in rejected["failureReasons"]


def test_calibration_decision_gate_returns_no_approval_when_current_candidates_fail():
    rolling = {
        "pooledTestSummary": gate_summary(0.6056, 1.0132, 0.1484),
        "pooledCalibratedTestSummary": gate_summary(0.5867, 0.9897, 0.0),
        "pooledDrawAwareCalibratedTestSummary": gate_summary(0.5906, 0.9934, 0.0469),
    }
    gate = build_calibration_decision_gate(rolling)
    assert gate["approvedCandidates"] == []
    assert "keep current default output unchanged" in gate["defaultCanonicalDecision"]


def test_cross_validation_markdown_renders_probability_quality_metrics():
    summary = {
        "matches": 3,
        "resultHits": 2,
        "resultAccuracy": 0.6667,
        "top5ScoreHits": 1,
        "top5ScoreCoverage": 0.3333,
        "predictedResultDistribution": {"HOME_WIN": 1, "DRAW": 1, "AWAY_WIN": 1},
        "actualResultDistribution": {"HOME_WIN": 1, "DRAW": 1, "AWAY_WIN": 1},
        "probabilityMetrics": {"brierScore": 0.5, "logLoss": 0.9},
        "baselineComparison": {
            "simpleFavorite": {"resultAccuracy": 0.3333, "brierScore": 0.7, "logLoss": 1.1},
            "eloRank": {"resultAccuracy": 0.3333, "brierScore": 0.65, "logLoss": 1.0},
            "calibrationBuckets": [
                {
                    "bucket": "0.5-0.6",
                    "matches": 3,
                    "averageConfidence": 0.55,
                    "observedAccuracy": 0.6667,
                    "calibrationError": 0.1167,
                }
            ],
            "drawDiagnostics": {
                "matches": 3,
                "predictedDraws": 1,
                "predictedDrawRate": 0.3333,
                "actualDraws": 1,
                "actualDrawRate": 0.3333,
                "averageDrawProbability": 0.2667,
                "actualDrawAverageProbability": 0.4,
            },
        },
    }
    report = {
        "sources": {"worldCupResults": "fixture", "eloSnapshots": "elo", "historicalFeatures": "history"},
        "parameterGrid": {"lambdaScale": [1.0], "drawAdjustmentRho": [0], "tournamentContextScale": [0]},
        "rollingOriginValidation": {
            "folds": [
                    {
                        "trainYears": [2018],
                        "testYears": [2022],
                        "selectedParams": {"lambdaScale": 1.0, "drawAdjustmentRho": 0, "tournamentContextScale": 0},
                        "selectedProbabilityCalibration": {
                            "favoriteExponent": 1.2,
                            "drawMultiplier": 1.05,
                            "favoriteBoost": 0.1,
                        },
                        "selectedDrawAwareCalibration": {
                            "favoriteExponent": 1.2,
                            "drawMultiplier": 1.05,
                            "favoriteBoost": 0.1,
                            "drawCandidateMargin": 0.04,
                            "minDrawProbability": 0.24,
                            "drawPromotionEpsilon": 0.001,
                        },
                        "testSummary": summary,
                        "calibratedTestSummary": summary,
                        "drawAwareCalibratedTestSummary": summary,
                    }
                ],
                "pooledTestSummary": summary,
                "pooledCalibratedTestSummary": summary,
                "pooledDrawAwareCalibratedTestSummary": summary,
            },
            "fixed2014_2018Validation": {
                "selectedParams": {"lambdaScale": 1.0, "drawAdjustmentRho": 0, "tournamentContextScale": 0},
                "selectedProbabilityCalibration": {
                    "favoriteExponent": 1.2,
                    "drawMultiplier": 1.05,
                    "favoriteBoost": 0.1,
                },
                "selectedDrawAwareCalibration": {
                    "favoriteExponent": 1.2,
                    "drawMultiplier": 1.05,
                    "favoriteBoost": 0.1,
                    "drawCandidateMargin": 0.04,
                    "minDrawProbability": 0.24,
                    "drawPromotionEpsilon": 0.001,
                },
                "yearReports": [
                    {
                        "year": 2022,
                        "summary": summary,
                        "calibratedSummary": summary,
                        "drawAwareCalibratedSummary": summary,
                    }
                ],
                "allYearsSummary": summary,
                "allYearsCalibratedSummary": summary,
                "allYearsDrawAwareCalibratedSummary": summary,
            },
        }
    markdown = render_cross_validation_markdown(report)
    assert "Brier Score" in markdown
    assert "Log Loss" in markdown
    assert "Simple Favorite" in markdown
    assert "Raw MatchOracle" in markdown
    assert "Calibration Decision Gate" in markdown
    assert "Draw-aware Calibrated Candidate" in markdown
    assert "Draw Diagnostics" in markdown
    assert "Calibration Buckets" in markdown
    assert "66.67%" in markdown


def test_cross_validation_match_row_csv_flattening_includes_per_match_metrics():
    row = {
        "validationType": "rolling_origin",
        "year": 2022,
        "trainYears": [2014, 2018],
        "testYears": [2022],
        "selectedParams": {"lambdaScale": 1.2, "drawAdjustmentRho": 0, "tournamentContextScale": 0},
        "matchId": "M1",
        "match": "A vs B",
        "stage": "GROUP_STAGE",
        "predictedResult": "HOME_WIN",
        "actualResult": "HOME_WIN",
        "predictedScoreText": "2-1",
        "actualScoreText": "1-0",
        "topScoreHit": False,
        "probabilities": {"home": 0.6, "draw": 0.25, "away": 0.15},
        "baselines": {
            "simpleFavorite": {
                "predictedResult": "HOME_WIN",
                "probabilities": {"home": 0.5, "draw": 0.25, "away": 0.25},
            },
            "eloRank": {
                "predictedResult": "HOME_WIN",
                "probabilities": {"home": 0.55, "draw": 0.26, "away": 0.19},
            },
        },
    }
    flattened = flatten_match_row(row)
    assert flattened["modelBrier"] > 0
    assert flattened["modelLogLoss"] > 0
    assert flattened["simpleFavoriteBrier"] > 0
    assert flattened["eloRankLogLoss"] > 0
    assert flattened["trainYears"] == "2014,2018"
