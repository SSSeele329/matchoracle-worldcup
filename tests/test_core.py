from datetime import date
import os
import tempfile

from src.worldcup.lineup_check import calculate_lineup_shock, final_lineup_check, formation_geometry_edge
from src.worldcup.lineup_evidence import build_f04p_expected_lineup
from src.worldcup.market import build_market_analysis, devig_decimal_odds
from src.worldcup.odds_import import import_live_odds_snapshots, import_odds_csv, list_market_odds_snapshots, validate_odds_csv
from src.worldcup.factors import (
    DATA_DIR,
    build_baseline_factors,
    evaluate_f07_data_quality,
    get_team_strength_score,
    load_team_strength_overrides,
    rank_to_score,
    select_result_key,
    weighted_edge,
)
from src.worldcup.lambda_model import adjust_lambdas_with_factor_edge, align_lambdas_with_probabilities, apply_lineup_shock
from src.worldcup.f05_monte_carlo import F05MonteCarloError, match_started_before, run_f05_monte_carlo
from src.worldcup.historical_features import build_team_prematch_profile
from src.worldcup.poisson import apply_dixon_coles_adjustment, filter_scenarios_by_result, generate_score_matrix, get_predicted_score, get_representative_score, outcome_probabilities_from_matrix
from src.worldcup.rules import get_competition_rules, normalize_stage
from src.worldcup.tournament_context import build_tournament_context
from src.worldcup.weights import MODEL_ARCHITECTURE, get_base_weights, validate_weight_table
from app import app
from src.calibration import build_replay_input, rank_goal_priors
from src.worldcup import WorldCupPredictor
from src.worldcup.job_queue import (
    JOB_FAILED,
    JOB_QUEUED,
    JOB_RUNNING,
    JOB_SUCCEEDED,
    JOB_TYPE_F05_MONTE_CARLO,
    JOB_TYPE_STRUCTURED_FACTS_SYNC,
    JOB_TYPE_T60_LINEUP_RECALC,
    claim_next_background_job,
    enqueue_background_job,
    get_background_job,
    mark_background_job_succeeded,
    reap_stale_running_jobs,
)
from src.worldcup.snapshot import prediction_input_hash
from src.worldcup.snapshot_store import (
    PREMATCH_FINAL,
    SnapshotFreezeError,
    append_prediction_snapshot,
    compare_replay,
    get_latest_prematch_final,
    get_last_good_prediction_snapshot,
    get_prediction_snapshot,
    latest_prediction_snapshot,
    list_prediction_snapshots,
)
from src.evaluation_metrics import brier_score, calibration_buckets, compare_with_baselines, log_loss
from src.calibration import render_wc2022_probability_metrics_markdown, run_wc2022_calibration, write_wc2022_probability_metrics_report


PROVIDER_ENV_KEYS = [
    "MATCHORACLE_STRUCTURED_FACTS_PROVIDER",
    "MATCHORACLE_STRUCTURED_FACTS_PROVIDER_CONFIGURED",
    "MATCHORACLE_STRUCTURED_FACTS_API_BASE_URL",
    "MATCHORACLE_STRUCTURED_FACTS_PROVIDER_TOKEN",
    "MATCHORACLE_AI_EVIDENCE_PROVIDER",
    "MATCHORACLE_AI_EVIDENCE_POLICY",
    "MATCHORACLE_AI_ALLOW_FACT_GENERATION",
    "MATCHORACLE_CSV_FALLBACK_ENABLED",
]
OPERATIONS_ENV_KEYS = [
    "MATCHORACLE_JOB_FAILURE_ALERTS_CONFIGURED",
    "MATCHORACLE_STALE_JOB_MONITOR_CONFIGURED",
    "MATCHORACLE_QUEUE_BACKLOG_MONITOR_CONFIGURED",
    "MATCHORACLE_STORE_BACKUP_POLICY_CONFIGURED",
    "MATCHORACLE_STORE_MIGRATION_POLICY_CONFIGURED",
]


def clear_provider_env():
    for key in PROVIDER_ENV_KEYS:
        os.environ.pop(key, None)


def clear_operations_env():
    for key in OPERATIONS_ENV_KEYS:
        os.environ.pop(key, None)


def set_operations_env():
    for key in OPERATIONS_ENV_KEYS:
        os.environ[key] = "1"


def test_weights_are_normalized():
    assert validate_weight_table() == {
        "GROUP_STAGE": 100,
        "KNOCKOUT": 100,
        "SEMI_AND_FINAL": 100,
    }
    assert len(get_base_weights("GROUP_STAGE")) == 15
    assert "F09" not in get_base_weights("GROUP_STAGE")
    assert "F15" not in get_base_weights("GROUP_STAGE")
    assert get_base_weights("GROUP_STAGE")["F03"] == 1
    assert get_base_weights("GROUP_STAGE")["F04"] > get_base_weights("GROUP_STAGE")["F10"]
    assert MODEL_ARCHITECTURE["version"] == "V4-P0"


def test_2026_competition_rules_separate_90_minute_and_advancement_layers():
    assert normalize_stage("1/16") == "ROUND_OF_32"
    group_rules = get_competition_rules("GROUP_STAGE")
    assert group_rules["regularTimeDrawAllowed"] is True
    assert group_rules["advancementRequiresWinner"] is False
    knockout_rules = get_competition_rules("ROUND_OF_32")
    assert knockout_rules["modelOutcomeType"] == "REGULAR_TIME_1X2"
    assert knockout_rules["competitionOutcomeType"] == "ADVANCEMENT_WINNER"
    assert knockout_rules["regularTimeDrawAllowed"] is True
    assert knockout_rules["extraTime"] is True
    assert knockout_rules["penalties"] is True


def test_f07_degradation_rules():
    assert evaluate_f07_data_quality(6, 7)["dataQuality"] == "HIGH"
    assert evaluate_f07_data_quality(4, 7)["effectiveWeight"] == 3.5
    assert evaluate_f07_data_quality(2, 7)["weightTransfer"] == {"F01": 3.5, "F12": 3.5}


def test_rank_to_score_boundaries():
    assert rank_to_score(1) == 100.0
    assert rank_to_score(200) == 20.0
    assert rank_to_score(50) == 80.4


def test_team_strength_overrides_load_from_project_data_dir():
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    assert DATA_DIR == os.path.join(project_root, "data", "worldcup")

    overrides = load_team_strength_overrides()
    score, override = get_team_strength_score("Morocco", 14, overrides)

    assert score == 74.0
    assert override["team"] == "Morocco"
    assert "FIFA排名可能低估" in override["reason"]
    fallback_score, fallback_override = get_team_strength_score("Unlisted Team", 50, overrides)
    assert fallback_score == rank_to_score(50)
    assert fallback_override is None


def test_f01_uses_strength_overrides_for_forward_prediction_inputs():
    factors = build_baseline_factors({
        "match": {
            "homeTeam": "Morocco",
            "awayTeam": "Unlisted Team",
            "stage": "GROUP_STAGE",
        },
        "teamData": {
            "home": {"fifaRank": 14},
            "away": {"fifaRank": 50},
        },
    })
    f01 = next(factor for factor in factors if factor["id"] == "F01")

    assert "Morocco实力分 74.0" in f01["reasoning"]
    assert "使用补丁" in f01["reasoning"]


def test_historical_replay_disables_2026_strength_overrides():
    match = {
        "matchId": "historic-morocco-test",
        "homeTeam": "Morocco",
        "awayTeam": "Unlisted Team",
        "stage": "GROUP_STAGE",
        "date": "2022-11-23",
        "venue": "Test Venue",
    }
    replay_input = build_replay_input(match, {"Morocco": 14, "Unlisted Team": 50})
    factors = build_baseline_factors(replay_input)
    f01 = next(factor for factor in factors if factor["id"] == "F01")

    assert replay_input["teamStrengthOverridesEnabled"] is False
    assert "Morocco实力分 94.8" in f01["reasoning"]
    assert "使用补丁" not in f01["reasoning"]
    assert "历史回放禁用2026静态补丁" in f01["reasoning"]


def test_rank_goal_priors_are_pre_match_strength_proxy():
    elite = rank_goal_priors(1)
    lower = rank_goal_priors(60)
    assert elite["actualGoals_avg"] > lower["actualGoals_avg"]
    assert elite["xGA_avg"] < lower["xGA_avg"]


def test_probability_metrics_score_known_cases():
    perfect = {"home": 1.0, "draw": 0.0, "away": 0.0}
    uncertain = {"home": 0.5, "draw": 0.25, "away": 0.25}
    assert brier_score(perfect, "HOME_WIN") == 0
    assert round(brier_score(uncertain, "HOME_WIN"), 4) == 0.375
    assert log_loss(perfect, "HOME_WIN") < 0.001


def test_calibration_buckets_and_baseline_comparison():
    rows = [
        {
            "actualResult": "HOME_WIN",
            "probabilities": {"home": 0.6, "draw": 0.2, "away": 0.2},
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
        },
        {
            "actualResult": "AWAY_WIN",
            "probabilities": {"home": 0.6, "draw": 0.2, "away": 0.2},
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
        },
    ]
    buckets = calibration_buckets(rows)
    assert buckets[0]["matches"] == 2
    assert buckets[0]["observedAccuracy"] == 0.5
    comparison = compare_with_baselines(rows)
    assert comparison["model"]["brierScore"] > 0
    assert comparison["simpleFavorite"]["matches"] == 2


def test_score_matrix_orders_by_probability():
    matrix = generate_score_matrix(1.2, 1.0)
    assert matrix[0]["probability"] >= matrix[-1]["probability"]
    assert len(matrix) == 36


def test_predicted_score_can_match_result_layer():
    matrix = generate_score_matrix(1.2, 1.2)
    score = get_predicted_score(matrix, "away")
    assert score["away"] > score["home"]


def test_representative_score_is_not_limited_to_modal_one_nil():
    matrix = generate_score_matrix(1.2, 1.2)
    score = get_representative_score(matrix, "home")
    assert score == {"home": 2, "away": 1}


def test_filter_scenarios_by_result():
    matrix = generate_score_matrix(1.2, 1.2)
    away_scores = filter_scenarios_by_result(matrix, "away")
    assert away_scores
    assert all(item["awayGoals"] > item["homeGoals"] for item in away_scores)


def test_outcome_probabilities_come_from_score_matrix():
    matrix = generate_score_matrix(1.8, 0.9, max_goals=7)
    probabilities = outcome_probabilities_from_matrix(matrix)
    assert round(sum(probabilities.values()), 3) == 1.0
    assert probabilities["home"] > probabilities["draw"] > probabilities["away"]


def test_dixon_coles_adjustment_lifts_low_score_draw_dependence():
    matrix = generate_score_matrix(1.2, 1.1, max_goals=7)
    base = outcome_probabilities_from_matrix(matrix)
    adjusted = apply_dixon_coles_adjustment(matrix, 1.2, 1.1, rho=-0.02)
    probabilities = outcome_probabilities_from_matrix(adjusted)
    assert probabilities["draw"] > base["draw"]


def test_historical_profile_uses_only_prematch_rows():
    rows = [
        {
            "date": date(2022, 1, 1),
            "homeTeam": "A",
            "awayTeam": "B",
            "homeScore": 2,
            "awayScore": 0,
            "tournament": "Friendly",
            "neutral": True,
        },
        {
            "date": date(2022, 12, 1),
            "homeTeam": "A",
            "awayTeam": "B",
            "homeScore": 0,
            "awayScore": 5,
            "tournament": "Friendly",
            "neutral": True,
        },
    ]
    profile = build_team_prematch_profile(rows, "A", "2022-06-01")
    assert profile["matchesUsed"] == 1
    assert profile["goalsForAvg"] > profile["goalsAgainstAvg"]


def test_tournament_context_uses_only_prior_group_matches():
    matches = [
        {"matchId": "M1", "stage": "GROUP_STAGE", "group": "Group A", "homeTeam": "A", "awayTeam": "B", "date": "2026-06-01", "time": "12:00", "actualScore": {"home": 1, "away": 0}},
        {"matchId": "M2", "stage": "GROUP_STAGE", "group": "Group A", "homeTeam": "C", "awayTeam": "D", "date": "2026-06-01", "time": "15:00", "actualScore": {"home": 0, "away": 0}},
        {"matchId": "M3", "stage": "GROUP_STAGE", "group": "Group A", "homeTeam": "A", "awayTeam": "C", "date": "2026-06-05", "time": "12:00", "actualScore": {"home": 0, "away": 2}},
        {"matchId": "M4", "stage": "GROUP_STAGE", "group": "Group A", "homeTeam": "B", "awayTeam": "D", "date": "2026-06-05", "time": "12:00", "actualScore": {"home": 4, "away": 0}},
    ]
    context = build_tournament_context(matches, matches[3])
    assert context["matchContext"]["homeGroupRecord"]["played"] == 1
    assert context["matchContext"]["awayGroupRecord"]["played"] == 1
    assert context["restData"]["homeRestDays"] == 4
    assert context["restData"]["awayRestDays"] == 4


def build_wc2026_48_team_schedule():
    matches = []
    for group_index in range(12):
        group_letter = chr(ord("A") + group_index)
        group = f"Group {group_letter}"
        teams = [f"G{group_index + 1:02d}T{slot}" for slot in range(1, 5)]

        def add(match_number, home_index, away_index, date, actual_score=None, probabilities=None):
            match = {
                "matchId": f"G{group_index + 1:02d}-M{match_number}",
                "stage": "GROUP_STAGE",
                "group": group,
                "homeTeam": teams[home_index],
                "awayTeam": teams[away_index],
                "date": date,
                "time": "18:00",
            }
            if actual_score is not None:
                match["actualScore"] = actual_score
            if probabilities is not None:
                match["probabilities"] = probabilities
            matches.append(match)

        add(1, 0, 1, "2026-06-01", {"home": 2, "away": 0})
        add(2, 2, 3, "2026-06-01", {"home": 1, "away": 0})
        add(3, 0, 2, "2026-06-05", {"home": 1, "away": 0})
        add(4, 1, 3, "2026-06-05", {"home": 2, "away": 0})
        add(5, 1, 2, "2026-06-09", probabilities={"home": 0.36, "draw": 0.28, "away": 0.36})
        add(6, 0, 3, "2026-06-09", probabilities={"home": 0.65, "draw": 0.22, "away": 0.13})
    return matches


def f05_payload(matches=None, simulations=120):
    matches = matches or build_wc2026_48_team_schedule()
    return {
        "currentMatchId": "G01-M5",
        "dependencySnapshotLock": {
            "lockType": "T24_DEPENDENCY",
            "snapshotId": "t24-slate-lock-001",
            "lockedAt": "2026-06-08T18:00:00+00:00",
            "source": "unit-test",
        },
        "matches": matches,
        "simulations": simulations,
        "seed": 17,
    }


def test_f05_monte_carlo_requires_t24_dependency_snapshot_lock():
    try:
        run_f05_monte_carlo({"matches": build_wc2026_48_team_schedule(), "currentMatchId": "G01-M5"})
        assert False, "Expected F05MonteCarloError"
    except F05MonteCarloError as error:
        assert error.code == "F05_DEPENDENCY_SNAPSHOT_LOCK_REQUIRED"


def test_f05_monte_carlo_models_48_team_third_place_advancement():
    result = run_f05_monte_carlo(f05_payload(simulations=150))
    total_advancement = sum(team["advancementProbability"] for team in result["teamAdvancement"].values())

    assert result["status"] == "READY"
    assert result["format"] == "WC2026_48"
    assert result["groupCount"] == 12
    assert result["teamCount"] == 48
    assert abs(total_advancement - 32.0) < 0.001
    assert result["teamAdvancement"]["G01T2"]["thirdPlaceProbability"] > 0
    assert set(result["currentMatch"]["homeQualificationByOutcome"]) == {"W", "D", "L"}
    assert result["matchContext"]["qualificationModel"] == "WC2026_48"
    assert result["matchContext"]["dependencySnapshotId"] == "t24-slate-lock-001"


def test_f05_monte_carlo_blocks_t60_lineup_shock_cascade_from_dependencies():
    matches = build_wc2026_48_team_schedule()
    dependency = next(match for match in matches if match["matchId"] == "G02-M5")
    dependency["actualLineup"] = {"homeStarters": ["H1"], "awayStarters": ["A1"]}
    dependency["prediction"] = {"finalLineupCheck": {"lineupShock": {"applied": True}}}

    result = run_f05_monte_carlo(f05_payload(matches=matches, simulations=60))

    assert result["guardrails"]["t60CascadeBlocked"] is True
    assert result["guardrails"]["ignoredT60LineupShockMatchIds"] == ["G02-M5"]


def test_f05_monte_carlo_does_not_order_simultaneous_kickoffs_by_match_id():
    earlier_id = {
        "matchId": "A-early-sort-id",
        "group": "A",
        "homeTeam": "A1",
        "awayTeam": "A2",
        "datetime": "2026-06-20T18:00:00+00:00",
    }
    later_id = {
        "matchId": "Z-late-sort-id",
        "group": "A",
        "homeTeam": "A3",
        "awayTeam": "A4",
        "datetime": "2026-06-20T18:00:00+00:00",
    }

    assert match_started_before(earlier_id, later_id) is False
    assert match_started_before(later_id, earlier_id) is False


def test_lambdas_align_with_away_probability_edge():
    home_lambda, away_lambda = align_lambdas_with_probabilities(1.4, 1.4, {"home": 0.35, "draw": 0.2, "away": 0.45})
    assert away_lambda > home_lambda


def test_factor_edge_adjusts_lambdas_without_total_goal_template():
    home_lambda, away_lambda = adjust_lambdas_with_factor_edge(1.4, 1.4, -0.8)
    assert away_lambda > home_lambda
    assert round(home_lambda + away_lambda, 2) == 2.8


def test_f05_monte_carlo_context_maps_to_lambda_and_rho():
    payload = {
        "matchId": "f05-context-test",
        "match": {"homeTeam": "A", "awayTeam": "B", "stage": "GROUP_STAGE"},
        "teamData": {"home": {"fifaRank": 20}, "away": {"fifaRank": 20}},
        "goalData": {
            "home": {"actualGoals_avg": 1.4, "xGA_avg": 1.1},
            "away": {"actualGoals_avg": 1.4, "xGA_avg": 1.1},
        },
    }
    baseline = WorldCupPredictor().predict(payload)
    pressured = WorldCupPredictor().predict({
        **payload,
        "matchContext": {
            "homeMustWinPressure": 1.0,
            "awayMustWinPressure": 0.0,
            "matchDrawIncentive": 0.75,
        },
    })

    assert pressured["scorePrediction"]["homeLambda"] != baseline["scorePrediction"]["homeLambda"]
    assert pressured["scorePrediction"]["awayLambda"] != baseline["scorePrediction"]["awayLambda"]
    assert pressured["probabilityModel"]["drawAdjustment"]["rho"] < baseline["probabilityModel"]["drawAdjustment"]["rho"]


def test_f07_f08_are_lambda_only_not_factor_edge_inputs():
    factors = build_baseline_factors({
        "match": {"homeTeam": "A", "awayTeam": "B", "stage": "GROUP_STAGE"},
        "teamData": {"home": {"fifaRank": 20}, "away": {"fifaRank": 20}},
        "understatCoverage": {"home": 6, "away": 6},
        "goalData": {
            "home": {"xG_avg": 2.2, "actualGoals_avg": 2.2, "xGA_avg": 0.7},
            "away": {"xG_avg": 0.8, "actualGoals_avg": 0.8, "xGA_avg": 1.7},
        },
    })

    assert next(f for f in factors if f["id"] == "F07")["impactScore"] > 0
    assert next(f for f in factors if f["id"] == "F08")["impactScore"] > 0
    assert next(f for f in factors if f["id"] == "F07")["role"] == "LAMBDA_ONLY"
    assert next(f for f in factors if f["id"] == "F08")["role"] == "LAMBDA_ONLY"
    assert weighted_edge(factors) == 0


def test_knockout_probability_keeps_90_minute_draw():
    factors = build_baseline_factors({
        "match": {"homeTeam": "A", "awayTeam": "B", "stage": "FINAL"},
        "teamData": {"home": {"fifaRank": 10}, "away": {"fifaRank": 11}},
        "understatCoverage": {"home": 6, "away": 6},
        "goalData": {
            "home": {"actualGoals_avg": 1.2, "xGA_avg": 1.1, "setpieceRate": 0.25},
            "away": {"actualGoals_avg": 1.2, "xGA_avg": 1.1, "setpieceRate": 0.25},
        },
    })
    from src.worldcup.factors import probabilities_from_factors
    probabilities = probabilities_from_factors(factors, "FINAL")
    assert probabilities["draw"] > 0


def test_balanced_probability_band_can_select_draw():
    result = select_result_key({"home": 0.3728, "draw": 0.2619, "away": 0.3653}, "FINAL")
    assert result == "draw"
    favorite = select_result_key({"home": 0.42, "draw": 0.25, "away": 0.33}, "GROUP_STAGE")
    assert favorite == "home"


def test_market_devig_and_ev():
    market = devig_decimal_odds({"home": 2.0, "draw": 3.5, "away": 4.0})
    assert market["overround"] > 0
    analysis = build_market_analysis({"home": 0.55, "draw": 0.25, "away": 0.20}, {"home": 2.0, "draw": 3.5, "away": 4.0})
    assert analysis["valueBets"]["home"]["ev"] == 0.1


def test_market_line_movement_and_rlm():
    analysis = build_market_analysis(
        {"home": 0.45, "draw": 0.25, "away": 0.30},
        {"home": 2.4, "draw": 3.2, "away": 2.4},
        {"home": 2.0, "draw": 3.2, "away": 3.3},
        {"home": 80, "draw": 8, "away": 12},
    )
    assert analysis["lineMovement"]
    assert analysis["reverseLineMovement"]["detected"] is True


def test_formation_geometry_edge():
    result = formation_geometry_edge("3-5-2", "4-4-2")
    assert result["impactScore"] > 0
    assert result["dataQuality"] == "MEDIUM"


def test_final_lineup_check_penalizes_large_changes():
    expected = {
        "homeFormation": "4-3-3",
        "awayFormation": "4-2-3-1",
        "homeStarters": [f"H{i}" for i in range(11)],
        "awayStarters": [f"A{i}" for i in range(11)],
    }
    actual = {
        "homeFormation": "5-4-1",
        "awayFormation": "4-2-3-1",
        "homeStarters": [f"H{i}" for i in range(7)] + ["X1", "X2", "X3", "X4"],
        "awayStarters": [f"A{i}" for i in range(11)],
    }
    check = final_lineup_check(expected, actual)
    assert check["confidencePenalty"] == 18
    assert check["riskFlags"]


def test_baseline_factors_use_15_factor_structure():
    factors = build_baseline_factors({
        "match": {"homeTeam": "A", "awayTeam": "B", "stage": "GROUP_STAGE"},
        "teamData": {"home": {"fifaRank": 10}, "away": {"fifaRank": 20}},
        "understatCoverage": {"home": 0, "away": 0},
        "formationData": {"home": "3-5-2", "away": "4-4-2"},
    })
    ids = {factor["id"] for factor in factors}
    assert len(factors) == 15
    assert "F09" not in ids
    assert "F15" not in ids
    assert next(f for f in factors if f["id"] == "F13")["impactScore"] > 0
    assert next(f for f in factors if f["id"] == "F03")["role"] == "EXPLAIN_ONLY"


def test_advanced_manual_inputs_do_not_require_paid_api():
    factors = build_baseline_factors({
        "match": {"homeTeam": "A", "awayTeam": "B", "stage": "KNOCKOUT"},
        "teamData": {"home": {"fifaRank": 10}, "away": {"fifaRank": 20}},
        "understatCoverage": {"home": 6, "away": 6},
        "goalData": {
            "home": {"xGA_avg": 0.8, "setpieceRate": 0.35},
            "away": {"xGA_avg": 1.2, "setpieceRate": 0.20},
        },
        "playerData": {
            "home": {"lineupStrength": 84, "keyAbsenceImpact": 1},
            "away": {"lineupStrength": 78, "keyAbsenceImpact": 2},
        },
        "goalkeeperData": {
            "home": {"score": 82},
            "away": {"score": 74},
        },
        "matchContext": {
            "homeMotivationScore": 2,
            "awayMotivationScore": 1,
            "homeRotationRisk": 0.1,
            "awayRotationRisk": 0.4,
        },
        "formationData": {"home": "3-5-2", "away": "4-4-2"},
        "tacticalData": {"homeContinuityScore": 80, "awayContinuityScore": 65},
        "depthData": {
            "home": {"benchStrength": 82, "penaltyReadiness": 75},
            "away": {"benchStrength": 70, "penaltyReadiness": 65},
        },
    })
    f04 = next(f for f in factors if f["id"] == "F04")
    assert f04["impactScore"] == 0
    assert f04["degraded"] is True
    assert "不再使用0-100阵容强度" in f04["reasoning"]
    assert next(f for f in factors if f["id"] == "F08")["impactScore"] > 0
    assert next(f for f in factors if f["id"] == "F17")["impactScore"] > 0


def test_home_page_keeps_split_names_regex_valid():
    html = app.test_client().get("/manual").get_data(as_text=True)
    assert "return value.split(/[,\\n]/)" in html


def test_home_page_does_not_expose_legacy_f04_subjective_inputs():
    html = app.test_client().get("/manual").get_data(as_text=True)
    assert "预计首发/球员强度 0-100" not in html
    assert "关键缺阵影响 0-5" not in html


def test_home_page_renders_background_queue_status_for_async_prediction_paths():
    html = app.test_client().get("/manual").get_data(as_text=True)
    assert "function renderBackgroundExecution" in html
    assert "function scheduleBackgroundJobPoll" in html
    assert "function demoKickoffTime" in html
    assert "Date.now() + 60 * 60 * 1000" in html
    assert "后台任务状态" in html
    assert "后台任务已排队" in html
    assert "queuedJob" in html
    assert "backgroundExecution" in html


def test_predictor_returns_competition_layers_for_knockout():
    response = app.test_client().post("/api/predict", json={
        "match": {"homeTeam": "A", "awayTeam": "B", "stage": "ROUND_OF_32"},
        "teamData": {"home": {"fifaRank": 5}, "away": {"fifaRank": 7}},
        "understatCoverage": {"home": 6, "away": 6},
        "goalData": {
            "home": {"actualGoals_avg": 1.2, "xGA_avg": 1.1, "setpieceRate": 0.25},
            "away": {"actualGoals_avg": 1.2, "xGA_avg": 1.1, "setpieceRate": 0.25},
        },
    })
    payload = response.get_json()
    assert payload["competitionRules"]["stageType"] == "KNOCKOUT"
    assert payload["predictionLayers"]["regularTime"]["probabilities"]["draw"] > 0
    assert payload["predictionLayers"]["extraTime"]["entryProbability"] == payload["predictionLayers"]["regularTime"]["probabilities"]["draw"]
    assert payload["predictionLayers"]["penalties"]["entryProbability"] > 0
    assert payload["predictionLayers"]["advancement"]["homeAdvances"] > 0


def test_data_reliability_fatal_blocks_prediction_without_core_fields():
    response = app.test_client().post("/api/predict", json={
        "match": {"homeTeam": "A", "awayTeam": "B", "stage": "GROUP_STAGE"},
        "teamData": {"home": {}, "away": {"fifaRank": 20}},
    })
    payload = response.get_json()
    assert payload["verdict"]["result"] == "ABORTED"
    assert payload["dataReliability"]["status"] == "FATAL"
    assert "probabilities" not in payload
    assert payload["canonicalProbability"]["status"] == "ABORTED"
    assert payload["finalRiskNarrative"]["primaryDriver"] == "DATA_RELIABILITY_FATAL"
    assert payload["finalRiskNarrative"]["userActionHint"] == "DATA_INCOMPLETE"


def test_data_reliability_disables_stale_market_divergence_alert():
    response = app.test_client().post("/api/predict", json={
        "match": {"homeTeam": "A", "awayTeam": "B", "stage": "GROUP_STAGE"},
        "teamData": {"home": {"fifaRank": 5}, "away": {"fifaRank": 80}},
        "featureSnapshotTime": "2026-06-01T10:00:00+00:00",
        "oddsSnapshotTime": "2026-06-01T11:00:00+00:00",
        "decimalOdds": {"home": 5.0, "draw": 3.5, "away": 1.7},
        "goalData": {
            "home": {"actualGoals_avg": 1.6, "xGA_avg": 1.0, "setpieceRate": 0.25},
            "away": {"actualGoals_avg": 1.1, "xGA_avg": 1.2, "setpieceRate": 0.25},
        },
    })
    payload = response.get_json()
    assert payload["dataReliability"]["status"] == "CRITICAL"
    assert payload["marketAnalysis"]["temporalAlignment"]["divergenceEnabled"] is False
    assert payload["calibratedProbability"]["status"] == "UNAVAILABLE"
    assert payload["canonicalProbability"]["source"] == "RAW_MODEL"
    assert payload["canonicalProbability"]["probabilities"] == payload["probabilities"]
    assert payload["verdict"]["confidence"] == "LOW"
    assert not any("模型与市场概率分歧超过15%" in flag for flag in payload["riskFlags"])


def test_data_reliability_normalizes_naive_temporal_alignment_to_utc():
    response = app.test_client().post("/api/predict", json={
        "match": {"homeTeam": "A", "awayTeam": "B", "stage": "GROUP_STAGE"},
        "teamData": {"home": {"fifaRank": 5}, "away": {"fifaRank": 80}},
        "featureSnapshotTime": "2026-06-01T10:00:00",
        "oddsSnapshotTime": "2026-06-01T11:00:00+00:00",
        "decimalOdds": {"home": 5.0, "draw": 3.5, "away": 1.7},
        "goalData": {
            "home": {"actualGoals_avg": 1.6, "xGA_avg": 1.0, "setpieceRate": 0.25},
            "away": {"actualGoals_avg": 1.1, "xGA_avg": 1.2, "setpieceRate": 0.25},
        },
    })
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["dataReliability"]["status"] == "CRITICAL"
    assert payload["marketAnalysis"]["temporalAlignment"]["reason"] == "RAW_MODEL_STALE"


def test_market_aligned_canonical_uses_transparent_bounded_blend():
    response = app.test_client().post("/api/predict", json={
        "match": {"homeTeam": "A", "awayTeam": "B", "stage": "GROUP_STAGE"},
        "teamData": {"home": {"fifaRank": 5}, "away": {"fifaRank": 80}},
        "featureSnapshotTime": "2026-06-01T12:00:00+00:00",
        "oddsSnapshotTime": "2026-06-01T11:00:00+00:00",
        "decimalOdds": {"home": 2.2, "draw": 3.2, "away": 3.6},
        "goalData": {
            "home": {"actualGoals_avg": 1.6, "xGA_avg": 1.0, "setpieceRate": 0.25},
            "away": {"actualGoals_avg": 1.1, "xGA_avg": 1.2, "setpieceRate": 0.25},
        },
    })
    payload = response.get_json()
    raw = payload["probabilities"]
    market = payload["marketAnalysis"]["probabilities"]
    canonical = payload["canonicalProbability"]
    calibrated = payload["calibratedProbability"]

    assert payload["marketAnalysis"]["temporalAlignment"]["divergenceEnabled"] is True
    assert calibrated["status"] == "ACTIVE"
    assert canonical["source"] == "MARKET_ALIGNED_CALIBRATED"
    assert canonical["probabilities"] == calibrated["probabilities"]
    assert canonical["probabilities"] != raw
    assert round(sum(canonical["probabilities"].values()), 4) == 1.0
    assert canonical["calibration"]["method"] == "bounded_raw_market_blend"
    assert canonical["calibration"]["marketRole"] == "BASELINE_NOT_BLACK_BOX_REPLACEMENT"
    assert canonical["components"]["rawModel"] == raw
    assert canonical["components"]["market"] == market
    assert abs(canonical["probabilities"]["home"] - raw["home"]) <= 0.081


def test_prediction_display_surfaces_canonical_probability_consistently():
    response = app.test_client().post("/api/predict", json={
        "match": {"homeTeam": "Germany", "awayTeam": "Curaçao", "stage": "GROUP_STAGE"},
        "teamData": {"home": {"fifaRank": 10}, "away": {"fifaRank": 80}},
        "featureSnapshotTime": "2026-06-01T12:00:00+00:00",
        "oddsSnapshotTime": "2026-06-01T11:00:00+00:00",
        "decimalOdds": {"home": 1.86, "draw": 3.9, "away": 4.75},
        "goalData": {
            "home": {"actualGoals_avg": 1.35, "xGA_avg": 1.1, "setpieceRate": 0.25},
            "away": {"actualGoals_avg": 1.25, "xGA_avg": 1.15, "setpieceRate": 0.25},
        },
    })
    payload = response.get_json()
    canonical = payload["canonicalProbability"]["probabilities"]
    raw = payload["probabilities"]

    assert response.status_code == 200
    assert canonical != raw
    assert payload["predictionLayers"]["regularTime"]["probabilities"] == canonical
    assert payload["predictionLayers"]["regularTime"]["rawModelProbabilities"] == raw
    assert f"主胜{round(canonical['home'] * 100, 1)}%" in payload["verdict"]["executiveSummary"]
    assert f"客胜{round(canonical['away'] * 100, 1)}%" in payload["verdict"]["executiveSummary"]


def test_final_risk_narrative_compresses_to_primary_two_secondary_and_action_hint():
    payload = {
        "match": {"homeTeam": "A", "awayTeam": "B", "stage": "GROUP_STAGE"},
        "teamData": {"home": {"fifaRank": 5}, "away": {"fifaRank": 80}},
        "featureSnapshotTime": "2026-06-01T12:00:00+00:00",
        "oddsSnapshotTime": "2026-06-01T11:00:00+00:00",
        "decimalOdds": {"home": 5.0, "draw": 3.5, "away": 1.7},
        "openingDecimalOdds": {"home": 1.5, "draw": 3.8, "away": 6.5},
        "publicTicketPercent": {"home": 75, "draw": 10, "away": 15},
        "goalData": {
            "home": {"actualGoals_avg": 1.7, "xGA_avg": 0.9, "setpieceRate": 0.25},
            "away": {"actualGoals_avg": 1.0, "xGA_avg": 1.3, "setpieceRate": 0.25},
        },
        "expectedLineup": {
            "homeStarters": ["H9", "H2", "H3"],
            "awayStarters": ["A1", "A2", "A3"],
            "homeKeyPlayers": [{"name": "H9", "tier": "TIER_1", "role": "ATTACKER"}],
        },
        "actualLineup": {
            "homeStarters": ["H1", "H2", "H3"],
            "awayStarters": ["A1", "A2", "A3"],
        },
    }
    prediction = WorldCupPredictor().predict(payload)
    narrative = prediction["finalRiskNarrative"]

    assert narrative["primaryDriver"] == "LINEUP_SHOCK"
    assert narrative["secondaryDrivers"] == ["MARKET_DIVERGENCE", "MARKET_MOVED"]
    assert len(narrative["secondaryDrivers"]) <= 2
    assert narrative["userActionHint"] == "READ_WITH_CAUTION"
    assert narrative["suppressedSignals"]
    assert prediction["canonicalProbability"]["probabilities"] == prediction["calibratedProbability"]["probabilities"]


def test_final_risk_narrative_defaults_to_canonical_probability_without_risks():
    prediction = WorldCupPredictor().predict({
        "match": {"homeTeam": "A", "awayTeam": "B", "stage": "GROUP_STAGE"},
        "teamData": {"home": {"fifaRank": 20}, "away": {"fifaRank": 22}},
        "expectedLineup": {"homeStarters": ["H1"], "awayStarters": ["A1"]},
        "goalData": {
            "home": {"actualGoals_avg": 1.2, "xGA_avg": 1.1, "setpieceRate": 0.25},
            "away": {"actualGoals_avg": 1.1, "xGA_avg": 1.2, "setpieceRate": 0.25},
        },
    })
    narrative = prediction["finalRiskNarrative"]

    assert prediction["riskFlags"] == []
    assert narrative["primaryDriver"] == "CANONICAL_PROBABILITY"
    assert narrative["secondaryDrivers"] == []
    assert narrative["userActionHint"] == "NO_ACTION"


def test_lineup_shock_uses_tier_and_position_lambda_mapping():
    shock = calculate_lineup_shock(
        expected={
            "homeKeyPlayers": [
                {"name": "H9", "tier": "TIER_1", "role": "ATTACKER"},
                {"name": "H1", "tier": "TIER_1", "role": "GOALKEEPER"},
            ]
        },
        actual={"homeStarters": ["H2", "H3", "H4"], "awayStarters": ["A1"]},
    )
    assert shock["applied"] is True
    assert shock["homeMultiplier"] == 0.85
    assert shock["awayMultiplier"] == 1.15
    assert len(shock["absences"]) == 2


def test_apply_lineup_shock_adjusts_lambdas_with_floor_and_ceiling():
    result = {
        "lineupShock": {
            "homeMultiplier": 0.85,
            "awayMultiplier": 1.15,
        }
    }
    home_lambda, away_lambda = apply_lineup_shock(1.4, 1.2, result)
    assert home_lambda == 1.19
    assert away_lambda == 1.38


def test_predictor_recalculates_lambda_after_tier_one_absence():
    base_payload = {
        "match": {"homeTeam": "A", "awayTeam": "B", "stage": "GROUP_STAGE"},
        "teamData": {"home": {"fifaRank": 10}, "away": {"fifaRank": 20}},
        "goalData": {
            "home": {"actualGoals_avg": 1.8, "xGA_avg": 0.9, "setpieceRate": 0.25},
            "away": {"actualGoals_avg": 1.2, "xGA_avg": 1.2, "setpieceRate": 0.25},
        },
    }
    predictor = WorldCupPredictor()
    baseline = predictor.predict(base_payload)
    shocked = predictor.predict({
        **base_payload,
        "expectedLineup": {
            "homeKeyPlayers": [{"name": "H9", "tier": "TIER_1", "role": "ATTACKER"}],
        },
        "actualLineup": {
            "homeStarters": ["H1", "H2", "H3"],
            "awayStarters": ["A1", "A2", "A3"],
        },
    })
    assert shocked["finalLineupCheck"]["lineupShock"]["applied"] is True
    assert shocked["scorePrediction"]["homeLambda"] < baseline["scorePrediction"]["homeLambda"]
    assert shocked["scorePrediction"]["preLineupHomeLambda"] == baseline["scorePrediction"]["homeLambda"]
    assert shocked["canonicalProbability"]["source"] == "RAW_MODEL"


def test_predictor_tolerates_null_optional_goal_and_lineup_fields():
    response = app.test_client().post("/api/predict", json={
        "match": {"homeTeam": "A", "awayTeam": "B", "stage": "GROUP_STAGE"},
        "teamData": {"home": {"fifaRank": 10}, "away": {"fifaRank": 20}},
        "goalData": {"home": None, "away": None},
        "expectedLineup": {"homeStarters": None, "awayStarters": None},
        "actualLineup": {"homeStarters": None, "awayStarters": None},
    })
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["dataReliability"]["status"] in {"OK", "WARN"}
    assert payload["probabilities"]


def test_wc2022_calibration_report_includes_strict_probability_metrics():
    report = run_wc2022_calibration()
    summary = report["summary"]
    assert summary["probabilityMetrics"]["brierScore"] > 0
    assert summary["probabilityMetrics"]["logLoss"] > 0
    assert summary["baselineComparison"]["model"]["brierScore"] == summary["probabilityMetrics"]["brierScore"]
    assert summary["baselineComparison"]["simpleFavorite"]["matches"] == summary["matches"]
    assert summary["baselineComparison"]["eloRank"]["matches"] == summary["matches"]
    assert summary["baselineComparison"]["calibrationBuckets"]


def test_wc2022_probability_metrics_markdown_report_is_reproducible():
    report = run_wc2022_calibration()
    markdown = render_wc2022_probability_metrics_markdown(report)
    assert "# 2022 World Cup Probability Metrics" in markdown
    assert "| Brier Score |" in markdown
    assert "| Log Loss |" in markdown
    assert "## Calibration Buckets" in markdown
    assert "Simple Favorite" in markdown

    with tempfile.TemporaryDirectory() as tmp_dir:
        path = os.path.join(tmp_dir, "wc2022_probability_metrics.md")
        written_path = write_wc2022_probability_metrics_report(report, path)
        assert written_path == path
        with open(path, "r", encoding="utf-8") as handle:
            assert handle.read() == markdown


def test_prediction_snapshot_id_is_stable_but_tracks_core_input_changes():
    base_payload = {
        "matchId": "snapshot-hash-test",
        "match": {"homeTeam": "A", "awayTeam": "B", "stage": "GROUP_STAGE"},
        "teamData": {"home": {"fifaRank": 10}, "away": {"fifaRank": 20}},
    }
    predictor = WorldCupPredictor()
    first = predictor.predict(base_payload)
    second = predictor.predict(base_payload)
    with_persistence_controls = {
        **base_payload,
        "snapshotType": PREMATCH_FINAL,
        "persistSnapshot": True,
    }
    controlled = predictor.predict(with_persistence_controls)
    changed = predictor.predict({
        **base_payload,
        "teamData": {"home": {"fifaRank": 80}, "away": {"fifaRank": 1}},
    })

    assert first["predictionSnapshotId"] == second["predictionSnapshotId"]
    assert first["predictionSnapshotId"] == controlled["predictionSnapshotId"]
    assert first["predictionSnapshotId"] != changed["predictionSnapshotId"]
    assert first["predictionManifest"]["inputSnapshotHash"] == prediction_input_hash(base_payload)
    assert prediction_input_hash(base_payload) == prediction_input_hash(with_persistence_controls)


def test_prediction_response_includes_consistent_prediction_view_model():
    response = app.test_client().post("/api/predict", json={
        "matchId": "view-model-test",
        "match": {"homeTeam": "A", "awayTeam": "B", "stage": "GROUP_STAGE"},
        "teamData": {"home": {"fifaRank": 10}, "away": {"fifaRank": 20}},
    })
    payload = response.get_json()
    snapshot_id = payload["predictionSnapshotId"]
    view_model = payload["predictionViewModel"]

    assert response.status_code == 200
    assert view_model["predictionSnapshotId"] == snapshot_id
    assert view_model["probabilitySnapshotId"] == snapshot_id
    assert view_model["narrativeSnapshotId"] == snapshot_id
    assert view_model["reliabilitySnapshotId"] == snapshot_id
    assert view_model["snapshotConsistency"]["status"] == "CONSISTENT"


def test_snapshot_store_appends_latest_and_fetches_by_id():
    prediction = WorldCupPredictor().predict({
        "matchId": "snap-test",
        "match": {"homeTeam": "A", "awayTeam": "B", "stage": "GROUP_STAGE"},
        "teamData": {"home": {"fifaRank": 10}, "away": {"fifaRank": 20}},
    })
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = os.path.join(tmp_dir, "snapshots.jsonl")
        request_payload = {
            "matchId": "snap-test",
            "match": {"homeTeam": "A", "awayTeam": "B", "stage": "GROUP_STAGE"},
            "teamData": {"home": {"fifaRank": 10}, "away": {"fifaRank": 20}},
        }
        record = append_prediction_snapshot(prediction, request_payload=request_payload, path=path)
        assert record["predictionSnapshotId"] == prediction["predictionSnapshotId"]
        assert record["requestPayload"] == request_payload
        assert get_prediction_snapshot(prediction["predictionSnapshotId"], path=path)["matchId"] == "snap-test"
        assert latest_prediction_snapshot("snap-test", path=path)["prediction"]["matchId"] == "snap-test"
        assert get_last_good_prediction_snapshot("snap-test", path=path)["predictionSnapshotId"] == prediction["predictionSnapshotId"]
        listing = list_prediction_snapshots(match_id="snap-test", path=path)
        assert listing[0]["predictionSnapshotId"] == prediction["predictionSnapshotId"]
        replayed = WorldCupPredictor().predict(record["requestPayload"])
        assert compare_replay(record["prediction"], replayed)["matches"] is True


def test_sqlite_snapshot_store_persists_immutable_prematch_final():
    request_payload = {
        "snapshotType": PREMATCH_FINAL,
        "matchId": "final-freeze-test",
        "match": {
            "homeTeam": "A",
            "awayTeam": "B",
            "stage": "GROUP_STAGE",
            "datetime": "2026-06-01T20:00:00+00:00",
        },
        "teamData": {"home": {"fifaRank": 10}, "away": {"fifaRank": 20}},
    }
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = os.path.join(tmp_dir, "prediction_snapshots.sqlite3")
        os.environ["MATCHORACLE_NOW"] = "2026-06-01T19:00:00+00:00"
        try:
            prediction = WorldCupPredictor().predict(request_payload)
            record = append_prediction_snapshot(prediction, request_payload=request_payload, path=path)
            assert record["snapshotType"] == PREMATCH_FINAL
            assert record["freezeStatus"] == "FROZEN"
            assert get_latest_prematch_final("final-freeze-test", path=path)["snapshotRecordId"] == record["snapshotRecordId"]

            changed_payload = {
                **request_payload,
                "teamData": {"home": {"fifaRank": 80}, "away": {"fifaRank": 1}},
            }
            changed_prediction = WorldCupPredictor().predict(changed_payload)
            duplicate = append_prediction_snapshot(changed_prediction, request_payload=changed_payload, path=path)
            assert duplicate["storageOperation"] == "PREMATCH_FINAL_ALREADY_EXISTS"
            assert duplicate["snapshotRecordId"] == record["snapshotRecordId"]
            listing = list_prediction_snapshots(match_id="final-freeze-test", snapshot_type=PREMATCH_FINAL, path=path)
            assert len(listing) == 1
        finally:
            os.environ.pop("MATCHORACLE_NOW", None)


def test_prematch_final_cannot_be_created_after_kickoff():
    request_payload = {
        "snapshotType": PREMATCH_FINAL,
        "matchId": "late-final-test",
        "match": {
            "homeTeam": "A",
            "awayTeam": "B",
            "stage": "GROUP_STAGE",
            "datetime": "2026-06-01T20:00:00+00:00",
        },
        "teamData": {"home": {"fifaRank": 10}, "away": {"fifaRank": 20}},
    }
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = os.path.join(tmp_dir, "prediction_snapshots.sqlite3")
        os.environ["MATCHORACLE_NOW"] = "2026-06-01T21:00:00+00:00"
        try:
            prediction = WorldCupPredictor().predict(request_payload)
            try:
                append_prediction_snapshot(prediction, request_payload=request_payload, path=path)
                assert False, "Expected SnapshotFreezeError"
            except SnapshotFreezeError as error:
                assert error.code == "PREMATCH_FINAL_CUTOFF_PASSED"
        finally:
            os.environ.pop("MATCHORACLE_NOW", None)


def test_snapshot_api_can_persist_and_replay_prediction():
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.environ["MATCHORACLE_SNAPSHOT_STORE"] = os.path.join(tmp_dir, "api-snapshots.jsonl")
        try:
            response = app.test_client().post("/api/predict?save=1", json={
                "matchId": "api-snap-test",
                "match": {"homeTeam": "A", "awayTeam": "B", "stage": "GROUP_STAGE"},
                "teamData": {"home": {"fifaRank": 10}, "away": {"fifaRank": 20}},
            })
            payload = response.get_json()
            snapshot_id = payload["predictionSnapshotId"]
            assert payload["savedSnapshot"]["predictionSnapshotId"] == snapshot_id

            latest = app.test_client().get("/api/snapshots/latest?matchId=api-snap-test").get_json()
            assert latest["prediction"]["matchId"] == "api-snap-test"

            replay = app.test_client().get(f"/api/snapshots/{snapshot_id}").get_json()
            assert replay["prediction"]["predictionSnapshotId"] == snapshot_id
            assert replay["requestPayload"]["matchId"] == "api-snap-test"

            replay_result = app.test_client().post(f"/api/snapshots/{snapshot_id}/replay").get_json()
            assert replay_result["replay"]["matches"] is True

            listing = app.test_client().get("/api/snapshots?matchId=api-snap-test").get_json()
            assert listing["snapshots"][0]["predictionSnapshotId"] == snapshot_id
        finally:
            os.environ.pop("MATCHORACLE_SNAPSHOT_STORE", None)


def test_prediction_card_bound_snapshot_serves_stored_prediction():
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.environ["MATCHORACLE_SNAPSHOT_STORE"] = os.path.join(tmp_dir, "api-snapshots.sqlite3")
        try:
            base_payload = {
                "matchId": "bound-card-test",
                "match": {"homeTeam": "A", "awayTeam": "B", "stage": "GROUP_STAGE"},
                "teamData": {"home": {"fifaRank": 10}, "away": {"fifaRank": 20}},
            }
            saved = app.test_client().post("/api/predict?save=1", json=base_payload).get_json()
            snapshot_id = saved["predictionSnapshotId"]

            changed_payload = {
                **base_payload,
                "predictionSnapshotId": snapshot_id,
                "teamData": {"home": {"fifaRank": 80}, "away": {"fifaRank": 1}},
            }
            bound = app.test_client().post("/api/predict", json=changed_payload).get_json()
            view_model = bound["predictionViewModel"]

            assert bound["predictionSnapshotId"] == snapshot_id
            assert bound["servedFromSnapshot"]["reason"] == "PREDICTION_CARD_BOUND_SNAPSHOT"
            assert view_model["predictionSnapshotId"] == snapshot_id
            assert view_model["probabilitySnapshotId"] == snapshot_id
            assert view_model["snapshotConsistency"]["status"] == "CONSISTENT"
        finally:
            os.environ.pop("MATCHORACLE_SNAPSHOT_STORE", None)


def test_missing_bound_snapshot_uses_match_last_good_fallback():
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.environ["MATCHORACLE_SNAPSHOT_STORE"] = os.path.join(tmp_dir, "api-snapshots.sqlite3")
        try:
            base_payload = {
                "matchId": "last-good-fallback-test",
                "match": {"homeTeam": "A", "awayTeam": "B", "stage": "GROUP_STAGE"},
                "teamData": {"home": {"fifaRank": 10}, "away": {"fifaRank": 20}},
            }
            saved = app.test_client().post("/api/predict?save=1", json=base_payload).get_json()
            fallback = app.test_client().post("/api/predict", json={
                **base_payload,
                "predictionSnapshotId": "missing-snapshot-id",
                "teamData": {"home": {"fifaRank": 80}, "away": {"fifaRank": 1}},
            }).get_json()
            last_good = app.test_client().get("/api/snapshots/last-good?matchId=last-good-fallback-test").get_json()

            assert fallback["predictionSnapshotId"] == saved["predictionSnapshotId"]
            assert fallback["fallback"]["mode"] == "LAST_GOOD_SNAPSHOT"
            assert fallback["servedFromSnapshot"]["reason"] == "BOUND_SNAPSHOT_NOT_FOUND"
            assert fallback["predictionViewModel"]["snapshotConsistency"]["status"] == "FALLBACK"
            assert last_good["predictionSnapshotId"] == saved["predictionSnapshotId"]
        finally:
            os.environ.pop("MATCHORACLE_SNAPSHOT_STORE", None)


def test_missing_bound_snapshot_without_last_good_returns_static_fallback():
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.environ["MATCHORACLE_SNAPSHOT_STORE"] = os.path.join(tmp_dir, "api-snapshots.sqlite3")
        try:
            response = app.test_client().post("/api/predict", json={
                "predictionSnapshotId": "missing-static-snapshot",
                "matchId": "static-fallback-test",
                "match": {"homeTeam": "A", "awayTeam": "B", "stage": "GROUP_STAGE"},
                "teamData": {"home": {"fifaRank": 10}, "away": {"fifaRank": 20}},
            })
            payload = response.get_json()

            assert response.status_code == 200
            assert payload["predictionSnapshotId"].startswith("static-")
            assert payload["verdict"]["result"] == "ABORTED"
            assert payload["canonicalProbability"]["status"] == "FALLBACK_STATIC"
            assert "probabilities" not in payload
            assert payload["fallback"]["mode"] == "STATIC_FALLBACK"
            assert payload["predictionViewModel"]["snapshotConsistency"]["status"] == "FALLBACK"
        finally:
            os.environ.pop("MATCHORACLE_SNAPSHOT_STORE", None)


def test_snapshot_api_serves_prematch_final_after_kickoff():
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.environ["MATCHORACLE_SNAPSHOT_STORE"] = os.path.join(tmp_dir, "api-snapshots.sqlite3")
        os.environ["MATCHORACLE_NOW"] = "2026-06-01T19:00:00+00:00"
        try:
            base_payload = {
                "snapshotType": PREMATCH_FINAL,
                "matchId": "api-final-freeze-test",
                "match": {
                    "homeTeam": "A",
                    "awayTeam": "B",
                    "stage": "GROUP_STAGE",
                    "datetime": "2026-06-01T20:00:00+00:00",
                },
                "teamData": {"home": {"fifaRank": 10}, "away": {"fifaRank": 20}},
            }
            first = app.test_client().post("/api/predict?save=1", json=base_payload).get_json()
            snapshot_id = first["predictionSnapshotId"]
            assert first["savedSnapshot"]["snapshotType"] == PREMATCH_FINAL

            os.environ["MATCHORACLE_NOW"] = "2026-06-01T21:00:00+00:00"
            changed_payload = {
                **base_payload,
                "snapshotType": "PREMATCH_DRAFT",
                "teamData": {"home": {"fifaRank": 90}, "away": {"fifaRank": 1}},
            }
            frozen = app.test_client().post("/api/predict", json=changed_payload).get_json()
            assert frozen["predictionSnapshotId"] == snapshot_id
            assert frozen["servedFromSnapshot"]["reason"] == "PREMATCH_FINAL_FROZEN_AFTER_KICKOFF"
        finally:
            os.environ.pop("MATCHORACLE_SNAPSHOT_STORE", None)
            os.environ.pop("MATCHORACLE_NOW", None)


def test_snapshot_api_blocks_new_saved_prematch_snapshot_after_kickoff_without_final():
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.environ["MATCHORACLE_SNAPSHOT_STORE"] = os.path.join(tmp_dir, "api-snapshots.sqlite3")
        os.environ["MATCHORACLE_NOW"] = "2026-06-01T21:00:00+00:00"
        try:
            response = app.test_client().post("/api/predict?save=1", json={
                "matchId": "api-late-save-test",
                "match": {
                    "homeTeam": "A",
                    "awayTeam": "B",
                    "stage": "GROUP_STAGE",
                    "datetime": "2026-06-01T20:00:00+00:00",
                },
                "teamData": {"home": {"fifaRank": 10}, "away": {"fifaRank": 20}},
            })
            payload = response.get_json()
            assert response.status_code == 409
            assert payload["error"] == "PREMATCH_SNAPSHOT_CUTOFF_PASSED"
        finally:
            os.environ.pop("MATCHORACLE_SNAPSHOT_STORE", None)
            os.environ.pop("MATCHORACLE_NOW", None)


def test_background_job_queue_claims_once_and_respects_concurrency_limit():
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = os.path.join(tmp_dir, "background_jobs.sqlite3")
        first = enqueue_background_job(
            JOB_TYPE_T60_LINEUP_RECALC,
            {"requestPayload": {"matchId": "queue-a"}},
            path=path,
        )
        enqueue_background_job(
            JOB_TYPE_T60_LINEUP_RECALC,
            {"requestPayload": {"matchId": "queue-b"}},
            path=path,
        )

        claimed = claim_next_background_job("worker-a", concurrency_limit=1, path=path)
        blocked = claim_next_background_job("worker-b", concurrency_limit=1, path=path)
        completed = mark_background_job_succeeded(claimed["jobId"], {"ok": True}, path=path)
        next_claimed = claim_next_background_job("worker-b", concurrency_limit=1, path=path)

        assert first["status"] == "QUEUED"
        assert claimed["jobId"] == first["jobId"]
        assert blocked is None
        assert completed["status"] == JOB_SUCCEEDED
        assert next_claimed["payload"]["requestPayload"]["matchId"] == "queue-b"


def test_stale_running_job_is_requeued_after_lease_timeout():
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = os.path.join(tmp_dir, "background_jobs.sqlite3")
        os.environ["MATCHORACLE_NOW"] = "2026-06-01T10:00:00+00:00"
        os.environ["MATCHORACLE_JOB_LEASE_TIMEOUT_SECONDS"] = "60"
        try:
            job = enqueue_background_job(
                JOB_TYPE_T60_LINEUP_RECALC,
                {"requestPayload": {"matchId": "stale-requeue"}},
                max_attempts=2,
                path=path,
            )
            claimed = claim_next_background_job("worker-a", concurrency_limit=1, path=path)

            os.environ["MATCHORACLE_NOW"] = "2026-06-01T10:01:01+00:00"
            reaped = reap_stale_running_jobs(path=path)
            reclaimed = claim_next_background_job("worker-b", concurrency_limit=1, path=path)

            assert claimed["status"] == JOB_RUNNING
            assert reaped[0]["jobId"] == job["jobId"]
            assert reaped[0]["status"] == JOB_QUEUED
            assert reaped[0]["error"]["code"] == "BACKGROUND_JOB_LEASE_TIMEOUT"
            assert reaped[0]["error"]["requeued"] is True
            assert reclaimed["jobId"] == job["jobId"]
            assert reclaimed["attempts"] == 2
            assert reclaimed["lockedBy"] == "worker-b"
        finally:
            os.environ.pop("MATCHORACLE_NOW", None)
            os.environ.pop("MATCHORACLE_JOB_LEASE_TIMEOUT_SECONDS", None)


def test_stale_running_job_fails_after_max_attempts_and_frees_concurrency_slot():
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = os.path.join(tmp_dir, "background_jobs.sqlite3")
        os.environ["MATCHORACLE_NOW"] = "2026-06-01T10:00:00+00:00"
        os.environ["MATCHORACLE_JOB_LEASE_TIMEOUT_SECONDS"] = "60"
        try:
            first = enqueue_background_job(
                JOB_TYPE_T60_LINEUP_RECALC,
                {"requestPayload": {"matchId": "stale-fail"}},
                max_attempts=1,
                path=path,
            )
            second = enqueue_background_job(
                JOB_TYPE_T60_LINEUP_RECALC,
                {"requestPayload": {"matchId": "after-stale"}},
                path=path,
            )
            claim_next_background_job("worker-a", concurrency_limit=1, path=path)

            os.environ["MATCHORACLE_NOW"] = "2026-06-01T10:01:01+00:00"
            next_claimed = claim_next_background_job("worker-b", concurrency_limit=1, path=path)
            failed = get_background_job(first["jobId"], path=path)

            assert failed["status"] == JOB_FAILED
            assert failed["error"]["code"] == "BACKGROUND_JOB_LEASE_TIMEOUT"
            assert failed["error"]["requeued"] is False
            assert next_claimed["jobId"] == second["jobId"]
            assert next_claimed["status"] == JOB_RUNNING
        finally:
            os.environ.pop("MATCHORACLE_NOW", None)
            os.environ.pop("MATCHORACLE_JOB_LEASE_TIMEOUT_SECONDS", None)


def test_worker_endpoint_requires_token_in_production():
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.environ["MATCHORACLE_APP_ENV"] = "production"
        os.environ["MATCHORACLE_JOB_QUEUE_STORE"] = os.path.join(tmp_dir, "background_jobs.sqlite3")
        try:
            blocked = app.test_client().post(
                "/api/jobs/run-next",
                headers={"X-MatchOracle-Worker": "1", "X-MatchOracle-Worker-Id": "prod-worker"},
            )
            payload = blocked.get_json()
            assert blocked.status_code == 403
            assert payload["error"] == "WORKER_AUTH_REQUIRED"
            assert payload["workerAuth"]["tokenRequired"] is True
            assert payload["workerAuth"]["tokenConfigured"] is False
        finally:
            os.environ.pop("MATCHORACLE_APP_ENV", None)
            os.environ.pop("MATCHORACLE_JOB_QUEUE_STORE", None)


def test_worker_endpoint_accepts_configured_token_in_production():
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.environ["MATCHORACLE_APP_ENV"] = "production"
        os.environ["MATCHORACLE_WORKER_TOKEN"] = "prod-secret"
        os.environ["MATCHORACLE_JOB_QUEUE_STORE"] = os.path.join(tmp_dir, "background_jobs.sqlite3")
        try:
            wrong = app.test_client().post(
                "/api/jobs/run-next",
                headers={"X-MatchOracle-Worker": "1", "X-MatchOracle-Worker-Id": "prod-worker"},
            )
            allowed = app.test_client().post(
                "/api/jobs/run-next",
                headers={
                    "X-MatchOracle-Worker-Token": "prod-secret",
                    "X-MatchOracle-Worker-Id": "prod-worker",
                },
            )
            assert wrong.status_code == 403
            assert allowed.status_code == 200
            assert allowed.get_json()["reason"] == "NO_RUNNABLE_JOB_OR_CONCURRENCY_LIMIT"
        finally:
            os.environ.pop("MATCHORACLE_APP_ENV", None)
            os.environ.pop("MATCHORACLE_WORKER_TOKEN", None)
            os.environ.pop("MATCHORACLE_JOB_QUEUE_STORE", None)


def test_job_detail_hides_payload_by_default_and_requires_token_to_include_it():
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.environ["MATCHORACLE_JOB_QUEUE_STORE"] = os.path.join(tmp_dir, "background_jobs.sqlite3")
        os.environ["MATCHORACLE_WORKER_TOKEN"] = "job-secret"
        try:
            job = enqueue_background_job(
                JOB_TYPE_T60_LINEUP_RECALC,
                {"requestPayload": {"matchId": "hidden-payload"}},
            )

            public_response = app.test_client().get(f"/api/jobs/{job['jobId']}")
            blocked_response = app.test_client().get(f"/api/jobs/{job['jobId']}?includePayload=1")
            admin_response = app.test_client().get(
                f"/api/jobs/{job['jobId']}?includePayload=1",
                headers={"X-MatchOracle-Worker-Token": "job-secret"},
            )

            public_payload = public_response.get_json()
            blocked_payload = blocked_response.get_json()
            admin_payload = admin_response.get_json()

            assert public_response.status_code == 200
            assert "payload" not in public_payload
            assert "lockedBy" not in public_payload
            assert public_payload["status"] == JOB_QUEUED
            assert blocked_response.status_code == 403
            assert blocked_payload["error"] == "JOB_PAYLOAD_AUTH_REQUIRED"
            assert admin_response.status_code == 200
            assert admin_payload["payload"]["requestPayload"]["matchId"] == "hidden-payload"
        finally:
            os.environ.pop("MATCHORACLE_JOB_QUEUE_STORE", None)
            os.environ.pop("MATCHORACLE_WORKER_TOKEN", None)


def test_readiness_blocks_production_without_worker_runtime_and_token():
    clear_provider_env()
    clear_operations_env()
    os.environ["MATCHORACLE_APP_ENV"] = "production"
    try:
        response = app.test_client().get("/api/readiness")
        payload = response.get_json()
        assert response.status_code == 503
        assert payload["status"] == "BLOCKED"
        assert "workerAuth" in payload["blockingChecks"]
        assert "workerRuntime" in payload["blockingChecks"]
        assert "predictionSnapshotStore" in payload["blockingChecks"]
        assert "backgroundJobStore" in payload["blockingChecks"]
        assert "marketOddsStore" in payload["blockingChecks"]
        assert "structuredFactsProvider" in payload["blockingChecks"]
        assert "jobFailureAlerts" in payload["blockingChecks"]
        assert "staleJobMonitor" in payload["blockingChecks"]
        assert "queueBacklogMonitor" in payload["blockingChecks"]
        assert "storeBackupPolicy" in payload["blockingChecks"]
        assert "storeMigrationPolicy" in payload["blockingChecks"]
    finally:
        os.environ.pop("MATCHORACLE_APP_ENV", None)
        clear_provider_env()
        clear_operations_env()


def test_readiness_blocks_production_without_explicit_stores():
    clear_provider_env()
    clear_operations_env()
    os.environ["MATCHORACLE_APP_ENV"] = "production"
    os.environ["MATCHORACLE_WORKER_TOKEN"] = "prod-secret"
    os.environ["MATCHORACLE_WORKER_RUNTIME_CONFIGURED"] = "1"
    try:
        response = app.test_client().get("/api/readiness")
        payload = response.get_json()
        assert response.status_code == 503
        assert payload["status"] == "BLOCKED"
        assert payload["blockingChecks"] == [
            "predictionSnapshotStore",
            "backgroundJobStore",
            "marketOddsStore",
            "structuredFactsStore",
            "structuredFactsProvider",
            "jobFailureAlerts",
            "staleJobMonitor",
            "queueBacklogMonitor",
            "storeBackupPolicy",
            "storeMigrationPolicy",
        ]
    finally:
        os.environ.pop("MATCHORACLE_APP_ENV", None)
        os.environ.pop("MATCHORACLE_WORKER_TOKEN", None)
        os.environ.pop("MATCHORACLE_WORKER_RUNTIME_CONFIGURED", None)
        clear_provider_env()
        clear_operations_env()


def test_readiness_passes_when_production_runtime_is_configured():
    with tempfile.TemporaryDirectory() as tmp_dir:
        clear_provider_env()
        clear_operations_env()
        os.environ["MATCHORACLE_APP_ENV"] = "production"
        os.environ["MATCHORACLE_WORKER_TOKEN"] = "prod-secret"
        os.environ["MATCHORACLE_WORKER_RUNTIME_CONFIGURED"] = "1"
        os.environ["MATCHORACLE_SNAPSHOT_STORE"] = os.path.join(tmp_dir, "prediction_snapshots.sqlite3")
        os.environ["MATCHORACLE_JOB_QUEUE_STORE"] = os.path.join(tmp_dir, "background_jobs.sqlite3")
        os.environ["MATCHORACLE_ODDS_STORE"] = os.path.join(tmp_dir, "market_odds.sqlite3")
        os.environ["MATCHORACLE_STRUCTURED_FACTS_STORE"] = os.path.join(tmp_dir, "structured_facts.sqlite3")
        os.environ["MATCHORACLE_STRUCTURED_FACTS_PROVIDER"] = "contract_provider"
        os.environ["MATCHORACLE_STRUCTURED_FACTS_PROVIDER_CONFIGURED"] = "1"
        os.environ["MATCHORACLE_STRUCTURED_FACTS_API_BASE_URL"] = "https://provider.example/structured-facts"
        os.environ["MATCHORACLE_STRUCTURED_FACTS_PROVIDER_TOKEN"] = "provider-secret-token"
        set_operations_env()
        try:
            response = app.test_client().get("/api/readiness")
            payload = response.get_json()
            assert response.status_code == 200
            assert payload["status"] == "READY"
            assert payload["blockingChecks"] == []
            assert payload["warningChecks"] == []
            provider_check = next(check for check in payload["checks"] if check["name"] == "structuredFactsProvider")
            assert provider_check["category"] == "STRUCTURED_FACT_DATA_SOURCE"
            assert provider_check["status"] == "PASS"
            operations_check = next(check for check in payload["checks"] if check["name"] == "jobFailureAlerts")
            assert operations_check["category"] == "DEPLOYMENT_AGNOSTIC_OPERATIONS"
            assert operations_check["status"] == "PASS"
        finally:
            os.environ.pop("MATCHORACLE_APP_ENV", None)
            os.environ.pop("MATCHORACLE_WORKER_TOKEN", None)
            os.environ.pop("MATCHORACLE_WORKER_RUNTIME_CONFIGURED", None)
            os.environ.pop("MATCHORACLE_SNAPSHOT_STORE", None)
            os.environ.pop("MATCHORACLE_JOB_QUEUE_STORE", None)
            os.environ.pop("MATCHORACLE_ODDS_STORE", None)
            os.environ.pop("MATCHORACLE_STRUCTURED_FACTS_STORE", None)
            clear_provider_env()
            clear_operations_env()


def test_api_t60_lineup_request_queues_job_and_serves_last_good_snapshot():
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.environ["MATCHORACLE_SNAPSHOT_STORE"] = os.path.join(tmp_dir, "api-snapshots.sqlite3")
        os.environ["MATCHORACLE_JOB_QUEUE_STORE"] = os.path.join(tmp_dir, "background_jobs.sqlite3")
        os.environ["MATCHORACLE_NOW"] = "2026-05-31T12:00:00+00:00"
        try:
            base_payload = {
                "matchId": "t60-queue-test",
                "match": {
                    "homeTeam": "A",
                    "awayTeam": "B",
                    "stage": "GROUP_STAGE",
                    "datetime": "2026-06-01T20:00:00+00:00",
                },
                "teamData": {"home": {"fifaRank": 10}, "away": {"fifaRank": 20}},
            }
            saved = app.test_client().post("/api/predict?save=1", json=base_payload).get_json()
            queued_response = app.test_client().post("/api/predict", json={
                **base_payload,
                "expectedLineup": {
                    "homeKeyPlayers": [{"name": "H9", "tier": "TIER_1", "role": "ATTACKER"}],
                },
                "actualLineup": {
                    "homeStarters": ["H1", "H2", "H3"],
                    "awayStarters": ["A1", "A2", "A3"],
                },
            })
            queued = queued_response.get_json()
            jobs = app.test_client().get("/api/jobs?status=QUEUED").get_json()["jobs"]

            assert queued_response.status_code == 202
            assert queued["predictionSnapshotId"] == saved["predictionSnapshotId"]
            assert queued["queuedJob"]["jobType"] == JOB_TYPE_T60_LINEUP_RECALC
            assert queued["fallback"]["mode"] == "LAST_GOOD_SNAPSHOT"
            assert queued["servedFromSnapshot"]["reason"] == "BACKGROUND_JOB_QUEUED"
            assert jobs[0]["jobType"] == JOB_TYPE_T60_LINEUP_RECALC
        finally:
            os.environ.pop("MATCHORACLE_SNAPSHOT_STORE", None)
            os.environ.pop("MATCHORACLE_JOB_QUEUE_STORE", None)
            os.environ.pop("MATCHORACLE_NOW", None)


def test_worker_runs_t60_job_and_saves_recalculated_snapshot():
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.environ["MATCHORACLE_SNAPSHOT_STORE"] = os.path.join(tmp_dir, "api-snapshots.sqlite3")
        os.environ["MATCHORACLE_JOB_QUEUE_STORE"] = os.path.join(tmp_dir, "background_jobs.sqlite3")
        os.environ["MATCHORACLE_NOW"] = "2026-05-31T12:00:00+00:00"
        try:
            base_payload = {
                "matchId": "t60-worker-test",
                "match": {
                    "homeTeam": "A",
                    "awayTeam": "B",
                    "stage": "GROUP_STAGE",
                    "datetime": "2026-06-01T20:00:00+00:00",
                },
                "teamData": {"home": {"fifaRank": 10}, "away": {"fifaRank": 20}},
            }
            app.test_client().post("/api/predict?save=1", json=base_payload)
            queued = app.test_client().post("/api/predict", json={
                **base_payload,
                "expectedLineup": {
                    "homeKeyPlayers": [{"name": "H9", "tier": "TIER_1", "role": "ATTACKER"}],
                },
                "actualLineup": {
                    "homeStarters": ["H1", "H2", "H3"],
                    "awayStarters": ["A1", "A2", "A3"],
                },
            }).get_json()
            worker_response = app.test_client().post(
                "/api/jobs/run-next",
                headers={"X-MatchOracle-Worker": "1", "X-MatchOracle-Worker-Id": "test-worker"},
            )
            worker_job = worker_response.get_json()["job"]
            latest = app.test_client().get("/api/snapshots/latest?matchId=t60-worker-test").get_json()

            assert queued["queuedJob"]["status"] == "QUEUED"
            assert worker_response.status_code == 200
            assert worker_job["status"] == JOB_SUCCEEDED
            assert worker_job["result"]["savedSnapshot"]["matchId"] == "t60-worker-test"
            assert latest["prediction"]["predictionSnapshotId"] == worker_job["result"]["predictionSnapshotId"]
            assert latest["prediction"]["finalLineupCheck"]["lineupShock"]["applied"] is True
            assert latest["prediction"]["predictionViewModel"]["source"] == "BACKGROUND_JOB"
        finally:
            os.environ.pop("MATCHORACLE_SNAPSHOT_STORE", None)
            os.environ.pop("MATCHORACLE_JOB_QUEUE_STORE", None)
            os.environ.pop("MATCHORACLE_NOW", None)


def test_api_f05_monte_carlo_runs_in_background_worker():
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.environ["MATCHORACLE_JOB_QUEUE_STORE"] = os.path.join(tmp_dir, "background_jobs.sqlite3")
        try:
            queued_response = app.test_client().post("/api/f05/monte-carlo", json=f05_payload(simulations=50))
            queued = queued_response.get_json()
            worker_response = app.test_client().post(
                "/api/jobs/run-next",
                headers={"X-MatchOracle-Worker": "1", "X-MatchOracle-Worker-Id": "test-worker"},
            )
            worker_job = worker_response.get_json()["job"]

            assert queued_response.status_code == 202
            assert queued["queuedJob"]["jobType"] == JOB_TYPE_F05_MONTE_CARLO
            assert worker_response.status_code == 200
            assert worker_job["status"] == JOB_SUCCEEDED
            assert worker_job["result"]["status"] == "READY"
            assert worker_job["result"]["matchContext"]["dependencySnapshotId"] == "t24-slate-lock-001"
        finally:
            os.environ.pop("MATCHORACLE_JOB_QUEUE_STORE", None)


def test_api_f05_monte_carlo_requires_worker_auth_when_configured():
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.environ["MATCHORACLE_JOB_QUEUE_STORE"] = os.path.join(tmp_dir, "background_jobs.sqlite3")
        os.environ["MATCHORACLE_WORKER_TOKEN"] = "f05-secret"
        try:
            response = app.test_client().post("/api/f05/monte-carlo", json=f05_payload(simulations=50))
            payload = response.get_json()

            assert response.status_code == 403
            assert payload["error"] == "F05_MONTE_CARLO_AUTH_REQUIRED"
        finally:
            os.environ.pop("MATCHORACLE_JOB_QUEUE_STORE", None)
            os.environ.pop("MATCHORACLE_WORKER_TOKEN", None)


def test_structured_facts_sync_api_requires_worker_auth():
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.environ["MATCHORACLE_JOB_QUEUE_STORE"] = os.path.join(tmp_dir, "background_jobs.sqlite3")
        try:
            response = app.test_client().post("/api/structured-facts/sync", json={"matchId": "M1"})
            payload = response.get_json()

            assert response.status_code == 403
            assert payload["error"] == "STRUCTURED_FACTS_SYNC_AUTH_REQUIRED"
        finally:
            os.environ.pop("MATCHORACLE_JOB_QUEUE_STORE", None)


def test_structured_facts_sync_api_queues_worker_and_ingests(monkeypatch):
    calls = []

    def fake_fetch(**kwargs):
        calls.append(kwargs)
        return {
            "status": "INGESTED",
            "source": "contract-http-provider",
            "snapshotTime": kwargs["snapshot_time"],
            "factKeys": ["fixtures"],
            "ingestion": {"storageOperation": "INSERTED"},
        }

    monkeypatch.setattr("app.fetch_validate_and_optionally_ingest_structured_facts", fake_fetch)
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.environ["MATCHORACLE_JOB_QUEUE_STORE"] = os.path.join(tmp_dir, "background_jobs.sqlite3")
        try:
            queued_response = app.test_client().post(
                "/api/structured-facts/sync",
                json={
                    "matchId": "M1",
                    "snapshotTime": "2026-06-01T12:00:00+00:00",
                },
                headers={"X-MatchOracle-Worker": "1"},
            )
            queued = queued_response.get_json()
            worker_response = app.test_client().post(
                "/api/jobs/run-next",
                headers={"X-MatchOracle-Worker": "1", "X-MatchOracle-Worker-Id": "facts-worker"},
            )
            worker_job = worker_response.get_json()["job"]

            assert queued_response.status_code == 202
            assert queued["queuedJob"]["jobType"] == JOB_TYPE_STRUCTURED_FACTS_SYNC
            assert worker_response.status_code == 200
            assert worker_job["status"] == JOB_SUCCEEDED
            assert worker_job["result"]["status"] == "INGESTED"
            assert calls == [{
                "match_id": "M1",
                "snapshot_time": "2026-06-01T12:00:00+00:00",
                "dry_run": False,
                "created_by": "background_structured_facts_sync",
            }]
        finally:
            os.environ.pop("MATCHORACLE_JOB_QUEUE_STORE", None)


def test_structured_facts_sync_worker_surfaces_provider_errors(monkeypatch):
    from src.worldcup.structured_facts_http_provider import StructuredFactsHttpProviderError

    def fake_fetch(**kwargs):
        raise StructuredFactsHttpProviderError(
            "STRUCTURED_FACTS_PROVIDER_HTTP_ERROR",
            "Structured facts provider returned an HTTP error.",
            details={"status": 401, "endpoint": "https://provider.example/structured-facts"},
        )

    monkeypatch.setattr("app.fetch_validate_and_optionally_ingest_structured_facts", fake_fetch)
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.environ["MATCHORACLE_JOB_QUEUE_STORE"] = os.path.join(tmp_dir, "background_jobs.sqlite3")
        try:
            app.test_client().post(
                "/api/structured-facts/sync",
                json={"matchId": "M1"},
                headers={"X-MatchOracle-Worker": "1"},
            )
            worker_response = app.test_client().post(
                "/api/jobs/run-next",
                headers={"X-MatchOracle-Worker": "1", "X-MatchOracle-Worker-Id": "facts-worker"},
            )
            worker_job = worker_response.get_json()["job"]

            assert worker_response.status_code == 409
            assert worker_job["status"] == JOB_FAILED
            assert worker_job["error"]["code"] == "STRUCTURED_FACTS_PROVIDER_HTTP_ERROR"
            assert "token" not in str(worker_job["error"]).lower()
        finally:
            os.environ.pop("MATCHORACLE_JOB_QUEUE_STORE", None)


def test_odds_csv_import_validates_and_stores_market_snapshots():
    csv_text = (
        "year,date,home_team,away_team,home_odds,draw_odds,away_odds,snapshot_time,source,odds_type\n"
        "2026,2026-06-11T20:00:00+00:00,Mexico,South Africa,2.10,3.25,3.80,2026-06-11T12:00:00+00:00,manual,OPENING\n"
        "2026,2026-06-11T20:00:00+00:00,Mexico,South Africa,2.04,3.30,3.95,2026-06-11T19:00:00+00:00,manual,PREMATCH\n"
    )
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = os.path.join(tmp_dir, "market_odds.sqlite3")
        result = import_odds_csv(
            csv_text,
            source_name="unit-test",
            known_teams=["Mexico", "South Africa"],
            path=path,
        )
        snapshots = list_market_odds_snapshots(year=2026, home_team="Mexico", away_team="South Africa", path=path)

        assert result["status"] == "IMPORTED"
        assert result["importedCount"] == 2
        assert len(snapshots) == 2
        assert snapshots[0]["oddsType"] == "PREMATCH"
        assert round(sum(snapshots[0]["marketProbabilities"].values()), 3) == 1.0


def test_live_odds_snapshots_are_persisted_and_deduplicated():
    snapshots = [{
        "homeTeam": "Germany",
        "awayTeam": "Curaçao",
        "kickoffAt": "2026-06-14T17:00:00+00:00",
        "snapshotTime": "2026-06-14T10:00:00+00:00",
        "source": "the_odds_api:consensus:8",
        "decimalOdds": {"home": 1.86, "draw": 3.9, "away": 4.75},
    }, {
        "homeTeam": "After",
        "awayTeam": "Kickoff",
        "kickoffAt": "2026-06-14T17:00:00+00:00",
        "snapshotTime": "2026-06-14T18:00:00+00:00",
        "source": "the_odds_api:consensus:8",
        "decimalOdds": {"home": 1.86, "draw": 3.9, "away": 4.75},
    }]
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = os.path.join(tmp_dir, "market_odds.sqlite3")
        first = import_live_odds_snapshots(snapshots, source_name="the_odds_api", path=path)
        second = import_live_odds_snapshots(snapshots, source_name="the_odds_api", path=path)
        stored = list_market_odds_snapshots(year=2026, home_team="Germany", away_team="Curaçao", path=path)

        assert first["importedCount"] == 1
        assert first["rejectedCount"] == 1
        assert second["importedCount"] == 0
        assert second["skippedExistingCount"] == 1
        assert stored[0]["decimalOdds"] == {"home": 1.86, "draw": 3.9, "away": 4.75}


def test_odds_csv_validation_rejects_row_errors_without_partial_import():
    csv_text = (
        "year,date,home_team,away_team,home_odds,draw_odds,away_odds,snapshot_time,source,odds_type\n"
        "2026,2026-06-11T20:00:00+00:00,Mexico,South Africa,2.10,3.25,3.80,2026-06-11T21:00:00+00:00,manual,PREMATCH\n"
        "2026,2026-06-11T20:00:00+00:00,Mexico,South Africa,1.00,3.25,3.80,2026-06-11T12:00:00+00:00,manual,PREMATCH\n"
        "2026,2026-06-11T20:00:00+00:00,Mexico,Atlantis,2.10,3.25,3.80,2026-06-11T12:00:00+00:00,manual,PREMATCH\n"
        "2026,2026-06-12T20:00:00+00:00,Mexico,South Africa,2.10,3.25,3.80,2026-06-12T12:00:00+00:00,manual,OPENING\n"
        "2026,2026-06-12T20:00:00+00:00,Mexico,South Africa,2.10,3.25,3.80,2026-06-12T12:00:00+00:00,manual,OPENING\n"
    )
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = os.path.join(tmp_dir, "market_odds.sqlite3")
        result = import_odds_csv(
            csv_text,
            known_teams=["Mexico", "South Africa"],
            path=path,
        )
        error_codes = {error["code"] for error in result["rowErrors"]}

        assert result["status"] == "REJECTED"
        assert result["importedCount"] == 0
        assert "SNAPSHOT_NOT_PREMATCH" in error_codes
        assert "INVALID_DECIMAL_ODDS" in error_codes
        assert "TEAM_MAPPING_FAILED" in error_codes
        assert "DUPLICATE_ROW" in error_codes
        assert list_market_odds_snapshots(path=path) == []


def test_odds_csv_schema_validation_rejects_unknown_columns():
    validation = validate_odds_csv(
        "year,date,home_team,away_team,home_odds,draw_odds,away_odds,snapshot_time,source,bad_column\n"
        "2026,2026-06-11T20:00:00+00:00,Mexico,South Africa,2.10,3.25,3.80,2026-06-11T12:00:00+00:00,manual,x\n"
    )
    assert validation["valid"] is False
    assert validation["globalErrors"][0]["code"] == "UNKNOWN_COLUMN"


def test_odds_import_api_queues_worker_and_exposes_snapshots():
    csv_text = (
        "year,date,home_team,away_team,home_odds,draw_odds,away_odds,snapshot_time,source,odds_type\n"
        "2026,2026-06-11T20:00:00+00:00,Mexico,South Africa,2.10,3.25,3.80,2026-06-11T12:00:00+00:00,manual,OPENING\n"
    )
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.environ["MATCHORACLE_JOB_QUEUE_STORE"] = os.path.join(tmp_dir, "background_jobs.sqlite3")
        os.environ["MATCHORACLE_ODDS_STORE"] = os.path.join(tmp_dir, "market_odds.sqlite3")
        try:
            queued_response = app.test_client().post("/api/odds/import", json={
                "csvText": csv_text,
                "sourceName": "api-test",
                "knownTeams": ["Mexico", "South Africa"],
            })
            queued = queued_response.get_json()
            worker_response = app.test_client().post(
                "/api/jobs/run-next",
                headers={"X-MatchOracle-Worker": "1", "X-MatchOracle-Worker-Id": "odds-worker"},
            )
            worker_job = worker_response.get_json()["job"]
            snapshots = app.test_client().get(
                "/api/odds/snapshots?year=2026&homeTeam=Mexico&awayTeam=South%20Africa"
            ).get_json()["snapshots"]

            assert queued_response.status_code == 202
            assert queued["queuedJob"]["jobType"] == "ODDS_IMPORT"
            assert worker_response.status_code == 200
            assert worker_job["result"]["status"] == "IMPORTED"
            assert worker_job["result"]["importedCount"] == 1
            assert snapshots[0]["source"] == "manual"
        finally:
            os.environ.pop("MATCHORACLE_JOB_QUEUE_STORE", None)
            os.environ.pop("MATCHORACLE_ODDS_STORE", None)


def test_odds_import_api_requires_worker_auth_when_configured():
    csv_text = (
        "year,date,home_team,away_team,home_odds,draw_odds,away_odds,snapshot_time,source,odds_type\n"
        "2026,2026-06-11T20:00:00+00:00,Mexico,South Africa,2.10,3.25,3.80,2026-06-11T12:00:00+00:00,manual,OPENING\n"
    )
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.environ["MATCHORACLE_JOB_QUEUE_STORE"] = os.path.join(tmp_dir, "background_jobs.sqlite3")
        os.environ["MATCHORACLE_WORKER_TOKEN"] = "odds-secret"
        try:
            response = app.test_client().post("/api/odds/import", json={
                "csvText": csv_text,
                "knownTeams": ["Mexico", "South Africa"],
            })
            payload = response.get_json()

            assert response.status_code == 403
            assert payload["error"] == "ODDS_IMPORT_AUTH_REQUIRED"
        finally:
            os.environ.pop("MATCHORACLE_JOB_QUEUE_STORE", None)
            os.environ.pop("MATCHORACLE_WORKER_TOKEN", None)


def test_odds_import_api_rejects_public_path_payload():
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.environ["MATCHORACLE_JOB_QUEUE_STORE"] = os.path.join(tmp_dir, "background_jobs.sqlite3")
        try:
            response = app.test_client().post("/api/odds/import", json={
                "path": os.path.join(tmp_dir, "market_odds.csv"),
            })
            payload = response.get_json()

            assert response.status_code == 403
            assert payload["error"] == "ODDS_IMPORT_PATH_AUTH_REQUIRED"
        finally:
            os.environ.pop("MATCHORACLE_JOB_QUEUE_STORE", None)


def test_odds_import_api_rejects_authenticated_path_outside_whitelist():
    with tempfile.TemporaryDirectory() as allowed_dir, tempfile.TemporaryDirectory() as other_dir:
        os.environ["MATCHORACLE_JOB_QUEUE_STORE"] = os.path.join(allowed_dir, "background_jobs.sqlite3")
        os.environ["MATCHORACLE_ODDS_IMPORT_PATH_ROOT"] = allowed_dir
        outside_path = os.path.join(other_dir, "market_odds.csv")
        with open(outside_path, "w", encoding="utf-8") as handle:
            handle.write("year,date,home_team,away_team,home_odds,draw_odds,away_odds,snapshot_time,source,odds_type\n")
        try:
            response = app.test_client().post(
                "/api/odds/import",
                json={"path": outside_path},
                headers={"X-MatchOracle-Worker": "1"},
            )
            payload = response.get_json()

            assert response.status_code == 400
            assert payload["error"] == "ODDS_IMPORT_PATH_NOT_ALLOWED"
        finally:
            os.environ.pop("MATCHORACLE_JOB_QUEUE_STORE", None)
            os.environ.pop("MATCHORACLE_ODDS_IMPORT_PATH_ROOT", None)


def test_odds_import_api_allows_authenticated_whitelisted_path():
    csv_text = (
        "year,date,home_team,away_team,home_odds,draw_odds,away_odds,snapshot_time,source,odds_type\n"
        "2026,2026-06-11T20:00:00+00:00,Mexico,South Africa,2.10,3.25,3.80,2026-06-11T12:00:00+00:00,manual,OPENING\n"
    )
    with tempfile.TemporaryDirectory() as tmp_dir:
        csv_path = os.path.join(tmp_dir, "market_odds.csv")
        with open(csv_path, "w", encoding="utf-8") as handle:
            handle.write(csv_text)
        os.environ["MATCHORACLE_JOB_QUEUE_STORE"] = os.path.join(tmp_dir, "background_jobs.sqlite3")
        os.environ["MATCHORACLE_ODDS_STORE"] = os.path.join(tmp_dir, "market_odds.sqlite3")
        os.environ["MATCHORACLE_ODDS_IMPORT_PATH_ROOT"] = tmp_dir
        try:
            queued_response = app.test_client().post(
                "/api/odds/import",
                json={
                    "path": csv_path,
                    "knownTeams": ["Mexico", "South Africa"],
                },
                headers={"X-MatchOracle-Worker": "1"},
            )
            worker_response = app.test_client().post(
                "/api/jobs/run-next",
                headers={"X-MatchOracle-Worker": "1", "X-MatchOracle-Worker-Id": "odds-worker"},
            )
            worker_job = worker_response.get_json()["job"]

            assert queued_response.status_code == 202
            assert worker_response.status_code == 200
            assert worker_job["result"]["status"] == "IMPORTED"
            assert worker_job["result"]["importedCount"] == 1
            assert worker_job["result"]["sourceName"] == "local-path-import"
            assert csv_path not in str(worker_job["result"])
        finally:
            os.environ.pop("MATCHORACLE_JOB_QUEUE_STORE", None)
            os.environ.pop("MATCHORACLE_ODDS_STORE", None)
            os.environ.pop("MATCHORACLE_ODDS_IMPORT_PATH_ROOT", None)


def test_odds_import_worker_returns_row_errors_for_rejected_csv():
    bad_csv = (
        "year,date,home_team,away_team,home_odds,draw_odds,away_odds,snapshot_time,source,odds_type\n"
        "2026,2026-06-11T20:00:00+00:00,Mexico,South Africa,1.00,3.25,3.80,2026-06-11T12:00:00+00:00,manual,PREMATCH\n"
    )
    with tempfile.TemporaryDirectory() as tmp_dir:
        os.environ["MATCHORACLE_JOB_QUEUE_STORE"] = os.path.join(tmp_dir, "background_jobs.sqlite3")
        os.environ["MATCHORACLE_ODDS_STORE"] = os.path.join(tmp_dir, "market_odds.sqlite3")
        try:
            app.test_client().post("/api/odds/import", json={
                "csvText": bad_csv,
                "knownTeams": ["Mexico", "South Africa"],
            })
            worker_response = app.test_client().post(
                "/api/jobs/run-next",
                headers={"X-MatchOracle-Worker": "1"},
            )
            worker_job = worker_response.get_json()["job"]

            assert worker_response.status_code == 409
            assert worker_job["status"] == "FAILED"
            assert worker_job["error"]["code"] == "ODDS_CSV_IMPORT_REJECTED"
            assert worker_job["error"]["rowErrors"][0]["row"] == 2
            assert worker_job["error"]["rowErrors"][0]["field"] == "home_odds"
        finally:
            os.environ.pop("MATCHORACLE_JOB_QUEUE_STORE", None)
            os.environ.pop("MATCHORACLE_ODDS_STORE", None)


def test_f04p_evidence_calculates_start_probability_from_fields_not_ai_probability():
    result = build_f04p_expected_lineup({
        "match": {"datetime": "2026-06-11T20:00:00+00:00"},
        "expectedLineupEvidence": {
            "snapshotTime": "2026-06-10T20:00:00+00:00",
            "players": [{
                "teamSide": "home",
                "player": "H9",
                "playerTier": "TIER_1",
                "roleGroup": "ATTACKER",
                "expectedRole": "STARTER",
                "trainedWithTeam": "FULL",
                "coachQuote": {"available": True, "source": "press conference", "publishedAt": "2026-06-10T18:00:00+00:00"},
                "reliableReporterSignal": "POSITIVE",
                "recentMinutes": 240,
                "injuryStatus": "FIT",
                "sources": [
                    {"name": "official training", "publishedAt": "2026-06-10T18:00:00+00:00"},
                    {"name": "beat reporter", "publishedAt": "2026-06-10T19:00:00+00:00"},
                ],
                "startProbability": 0.01,
            }],
        },
    })
    player = result["players"][0]

    assert result["status"] == "AVAILABLE"
    assert player["startProbability"] >= 0.70
    assert player["directProbabilityIgnored"] is True
    assert result["expectedLineup"]["homeStarters"] == ["H9"]
    assert result["expectedLineup"]["homeKeyPlayers"][0]["startProbability"] == player["startProbability"]
    assert result["historicalBacktestEligible"] is False
    assert result["validationMode"] == "FORWARD_VALIDATION_ONLY"


def test_f04p_missing_timestamp_or_evidence_outputs_unknown_without_inventing_probability():
    result = build_f04p_expected_lineup({
        "match": {"datetime": "2026-06-11T20:00:00+00:00"},
        "expectedLineupEvidence": {
            "players": [{
                "teamSide": "away",
                "player": "A10",
                "playerTier": "TIER_1",
                "roleGroup": "CREATOR",
                "sources": [],
            }],
        },
    })
    player = result["players"][0]

    assert result["status"] == "UNKNOWN"
    assert player["startProbability"] is None
    assert player["status"] == "UNKNOWN"
    assert "EVIDENCE_TIMESTAMP_MISSING" in player["issues"]
    assert "NO_PROBABILITY_EVIDENCE" in player["issues"]
    assert result["expectedLineup"]["awayStarters"] == []


def test_predictor_uses_f04p_expected_lineup_as_t60_lineup_shock_baseline():
    base_payload = {
        "matchId": "f04p-shock-test",
        "match": {"homeTeam": "A", "awayTeam": "B", "stage": "GROUP_STAGE", "datetime": "2026-06-11T20:00:00+00:00"},
        "teamData": {"home": {"fifaRank": 10}, "away": {"fifaRank": 20}},
        "goalData": {
            "home": {"actualGoals_avg": 1.8, "xGA_avg": 0.9, "setpieceRate": 0.25},
            "away": {"actualGoals_avg": 1.2, "xGA_avg": 1.2, "setpieceRate": 0.25},
        },
        "expectedLineupEvidence": {
            "snapshotTime": "2026-06-10T20:00:00+00:00",
            "players": [{
                "teamSide": "home",
                "player": "H9",
                "playerTier": "TIER_1",
                "roleGroup": "ATTACKER",
                "expectedRole": "STARTER",
                "trainedWithTeam": "FULL",
                "reliableReporterSignal": "POSITIVE",
                "recentMinutes": 240,
                "injuryStatus": "FIT",
                "sources": [
                    {"name": "official training", "publishedAt": "2026-06-10T18:00:00+00:00"},
                    {"name": "beat reporter", "publishedAt": "2026-06-10T19:00:00+00:00"},
                ],
            }],
        },
    }
    baseline = WorldCupPredictor().predict(base_payload)
    shocked = WorldCupPredictor().predict({
        **base_payload,
        "actualLineup": {
            "homeStarters": ["H1", "H2", "H3"],
            "awayStarters": ["A1", "A2", "A3"],
        },
    })
    f04_factor = next(factor for factor in baseline["factors"] if factor["id"] == "F04")

    assert baseline["f04PExpectedLineup"]["expectedLineup"]["homeKeyPlayers"][0]["name"] == "H9"
    assert baseline["dataReliability"]["lineupReliability"] == 80
    assert f04_factor["impactScore"] == 0
    assert f04_factor["dataQuality"] == "MEDIUM"
    assert f04_factor["evidence"][0]["historicalBacktestEligible"] is False
    assert shocked["finalLineupCheck"]["lineupShock"]["applied"] is True
    assert shocked["scorePrediction"]["homeLambda"] < shocked["scorePrediction"]["preLineupHomeLambda"]
