import csv
import json
import os
from argparse import ArgumentParser
from itertools import product

from .calibration import (
    CALIBRATION_DIR,
    actual_result,
    build_historical_replay_input,
    load_elo_rank_proxy,
    load_json,
    regular_time_score,
    summarize_rows,
)
from .evaluation_metrics import brier_score, log_loss
from .worldcup import WorldCupPredictor
from .worldcup.historical_features import DEFAULT_RESULTS_PATH, load_international_results

YEARS = [2002, 2006, 2010, 2014, 2018, 2022]
MATCH_FILES = {
    2002: "wc2002_matches_openfootball.json",
    2006: "wc2006_matches_openfootball.json",
    2010: "wc2010_matches_openfootball.json",
    2014: "wc2014_matches_openfootball.json",
    2018: "wc2018_matches_openfootball.json",
    2022: "wc2022_matches_openfootball.json",
}
PARAM_GRID = {
    "lambdaScale": [1.0, 1.1, 1.2, 1.3, 1.4, 1.5],
    "drawAdjustmentRho": [0, -0.01, -0.02, -0.03, -0.05],
    "tournamentContextScale": [0, 0.5, 1.0],
}
PROBABILITY_CALIBRATION_GRID = {
    "favoriteExponent": [1.0, 1.2, 1.4, 1.6, 1.8, 2.0],
    "drawMultiplier": [0.85, 0.95, 1.0, 1.05],
    "favoriteBoost": [0.0, 0.1, 0.2, 0.3],
}
DRAW_AWARE_CALIBRATION_GRID = {
    "drawCandidateMargin": [0.06, 0.08, 0.10, 0.12],
    "minDrawProbability": [0.18, 0.20, 0.22, 0.24],
    "drawPromotionEpsilon": [0.001],
}
CALIBRATION_DECISION_GATE = {
    "minOutOfSampleMatches": 200,
    "minDrawRateVsActual": 0.50,
    "maxDrawRateVsActual": 1.50,
    "maxWeightedCalibrationError": 0.12,
    "maxBucketCalibrationError": 0.20,
    "baselineNames": ["simpleFavorite", "eloRank"],
}

REPORTS_DIR = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")), "reports")
DEFAULT_JSON_REPORT = os.path.join(REPORTS_DIR, "worldcup_cross_validation.json")
DEFAULT_MD_REPORT = os.path.join(REPORTS_DIR, "worldcup_cross_validation.md")
DEFAULT_ROWS_CSV_REPORT = os.path.join(REPORTS_DIR, "worldcup_cross_validation_rows.csv")


def score_text(score):
    return f"{score['home']}-{score['away']}"


def load_year_matches(year):
    return load_json(os.path.join(CALIBRATION_DIR, MATCH_FILES[year]))


def build_year_cases(year, history_rows=None):
    history_rows = history_rows if history_rows is not None else load_international_results(DEFAULT_RESULTS_PATH)
    ranks = load_elo_rank_proxy(year)
    year_matches = load_year_matches(year)
    cases = []
    for match in year_matches:
        cases.append({
            "match": match,
            "predictionInput": build_historical_replay_input(match, ranks, history_rows, year_matches),
        })
    return cases


def build_year_cases_by_year(years, history_rows=None):
    history_rows = history_rows if history_rows is not None else load_international_results(DEFAULT_RESULTS_PATH)
    return {year: build_year_cases(year, history_rows) for year in years}


def apply_params_to_input(base_input, params):
    prediction_input = dict(base_input)
    prediction_input["matchContext"] = dict(base_input.get("matchContext", {}))
    prediction_input["restData"] = dict(base_input.get("restData", {}))
    prediction_input["lambdaScale"] = params["lambdaScale"]
    prediction_input["drawAdjustmentRho"] = params["drawAdjustmentRho"]
    prediction_input["matchContext"]["scale"] = params.get("tournamentContextScale", 1.0)
    prediction_input["restData"]["scale"] = params.get("tournamentContextScale", 1.0)
    return prediction_input


def run_year(year, params, history_rows=None, predictor=None, year_cases=None):
    predictor = predictor if predictor is not None else WorldCupPredictor()
    cases = year_cases if year_cases is not None else build_year_cases(year, history_rows)
    rows = []
    for case in cases:
        match = case["match"]
        prediction_input = apply_params_to_input(case["predictionInput"], params)
        prediction = predictor.predict(prediction_input)
        actual_score = regular_time_score(match)
        actual_score_text = score_text(actual_score)
        predicted_score = prediction["scorePrediction"]["predicted"]
        top_scores = [item["score"] for item in prediction["scorePrediction"]["topScenarios"]]
        rows.append({
            "year": year,
            "matchId": match["matchId"],
            "match": f"{match['homeTeam']} vs {match['awayTeam']}",
            "stage": match["stage"],
            "predictedResult": prediction["verdict"]["result"],
            "actualResult": actual_result(actual_score),
            "probabilities": prediction["probabilities"],
            "predictedScore": predicted_score,
            "predictedScoreText": score_text(predicted_score),
            "actualScore": actual_score,
            "actualScoreText": actual_score_text,
            "topScoreHit": actual_score_text in top_scores,
            "baselines": prediction_input.get("rankBaselines", {}),
        })
    return rows


def run_years(years, params, history_rows=None, predictor=None, year_cases_by_year=None):
    rows = []
    for year in years:
        year_cases = year_cases_by_year.get(year) if year_cases_by_year else None
        rows.extend(run_year(year, params, history_rows, predictor, year_cases))
    return rows


def normalized_probabilities(probabilities):
    total = sum(probabilities.values())
    if not total:
        return {"home": 0.0, "draw": 0.0, "away": 0.0}
    return {key: value / total for key, value in probabilities.items()}


def apply_probability_calibration(probabilities, calibration_params):
    exponent = float(calibration_params.get("favoriteExponent", 1.0))
    draw_multiplier = float(calibration_params.get("drawMultiplier", 1.0))
    favorite_boost = float(calibration_params.get("favoriteBoost", 0.0))
    calibrated = {
        key: max(1e-12, float(value)) ** exponent
        for key, value in probabilities.items()
    }
    calibrated["draw"] *= draw_multiplier
    favorite_key = max(("home", "away"), key=lambda key: probabilities.get(key, 0))
    calibrated[favorite_key] *= 1 + favorite_boost
    return normalized_probabilities(calibrated)


def result_from_probability_keys(probabilities):
    result_key = max(("home", "draw", "away"), key=lambda key: probabilities.get(key, 0))
    return {"home": "HOME_WIN", "draw": "DRAW", "away": "AWAY_WIN"}[result_key]


def apply_probability_calibration_to_rows(rows, calibration_params, validation_type_suffix=None):
    calibrated_rows = []
    for row in rows:
        item = dict(row)
        probabilities = apply_probability_calibration(row["probabilities"], calibration_params)
        item["probabilities"] = {key: round(value, 4) for key, value in probabilities.items()}
        item["predictedResult"] = result_from_probability_keys(probabilities)
        item["probabilityCalibration"] = dict(calibration_params)
        if validation_type_suffix:
            item["validationType"] = f"{item.get('validationType', 'unknown')}_{validation_type_suffix}"
        calibrated_rows.append(item)
    return calibrated_rows


def apply_draw_aware_probability_calibration(probabilities, calibration_params):
    calibrated = apply_probability_calibration(probabilities, calibration_params)
    favorite_key = max(("home", "away"), key=lambda key: calibrated.get(key, 0))
    margin = float(calibration_params.get("drawCandidateMargin", 0))
    min_draw = float(calibration_params.get("minDrawProbability", 0))
    epsilon = float(calibration_params.get("drawPromotionEpsilon", 0.001))
    if calibrated["draw"] >= min_draw and calibrated[favorite_key] - calibrated["draw"] <= margin:
        promoted = dict(calibrated)
        target_draw = min(1 - 1e-12, promoted[favorite_key] + epsilon)
        delta = max(0, target_draw - promoted["draw"])
        promoted["draw"] += delta
        promoted[favorite_key] = max(1e-12, promoted[favorite_key] - delta)
        calibrated = normalized_probabilities(promoted)
    return calibrated


def apply_draw_aware_probability_calibration_to_rows(rows, calibration_params, validation_type_suffix=None):
    calibrated_rows = []
    for row in rows:
        item = dict(row)
        probabilities = apply_draw_aware_probability_calibration(row["probabilities"], calibration_params)
        item["probabilities"] = {key: round(value, 4) for key, value in probabilities.items()}
        item["predictedResult"] = result_from_probability_keys(probabilities)
        item["probabilityCalibration"] = dict(calibration_params)
        item["calibrationCandidate"] = "draw_aware"
        if validation_type_suffix:
            item["validationType"] = f"{item.get('validationType', 'unknown')}_{validation_type_suffix}"
        calibrated_rows.append(item)
    return calibrated_rows


def annotate_rows(rows, validation_type, selected_params, train_years=None, test_years=None, year=None):
    annotated = []
    for row in rows:
        item = dict(row)
        item["validationType"] = validation_type
        item["selectedParams"] = dict(selected_params)
        if train_years is not None:
            item["trainYears"] = list(train_years)
        if test_years is not None:
            item["testYears"] = list(test_years)
        if year is not None:
            item["year"] = year
        annotated.append(item)
    return annotated


def candidate_params():
    for lambda_scale, rho, context_scale in product(
        PARAM_GRID["lambdaScale"],
        PARAM_GRID["drawAdjustmentRho"],
        PARAM_GRID["tournamentContextScale"],
    ):
        yield {
            "lambdaScale": lambda_scale,
            "drawAdjustmentRho": rho,
            "tournamentContextScale": context_scale,
        }


def calibration_score(summary):
    metrics = summary["probabilityMetrics"]
    return (
        -metrics["logLoss"],
        -metrics["brierScore"],
        summary["resultAccuracy"],
    )


def select_params(train_years, history_rows, predictor, year_cases_by_year=None):
    candidates = []
    for params in candidate_params():
        rows = run_years(train_years, params, history_rows, predictor, year_cases_by_year)
        summary = summarize_rows(rows)
        candidates.append({
            "params": params,
            "summary": summary,
            "score": calibration_score(summary),
        })
    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates[0], candidates[:5]


def candidate_probability_calibrations():
    for exponent, draw_multiplier, favorite_boost in product(
        PROBABILITY_CALIBRATION_GRID["favoriteExponent"],
        PROBABILITY_CALIBRATION_GRID["drawMultiplier"],
        PROBABILITY_CALIBRATION_GRID["favoriteBoost"],
    ):
        yield {
            "favoriteExponent": exponent,
            "drawMultiplier": draw_multiplier,
            "favoriteBoost": favorite_boost,
        }


def probability_calibration_score(summary):
    metrics = summary["probabilityMetrics"]
    return (
        -metrics["logLoss"],
        -metrics["brierScore"],
        summary["resultAccuracy"],
    )


def select_probability_calibration(train_rows):
    candidates = []
    for params in candidate_probability_calibrations():
        rows = apply_probability_calibration_to_rows(train_rows, params)
        summary = summarize_rows(rows)
        candidates.append({
            "params": params,
            "summary": summary,
            "score": probability_calibration_score(summary),
        })
    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates[0], candidates[:5]


def candidate_draw_aware_probability_calibrations():
    for base_params in candidate_probability_calibrations():
        for margin, min_draw, epsilon in product(
            DRAW_AWARE_CALIBRATION_GRID["drawCandidateMargin"],
            DRAW_AWARE_CALIBRATION_GRID["minDrawProbability"],
            DRAW_AWARE_CALIBRATION_GRID["drawPromotionEpsilon"],
        ):
            params = dict(base_params)
            params.update({
                "drawCandidateMargin": margin,
                "minDrawProbability": min_draw,
                "drawPromotionEpsilon": epsilon,
            })
            yield params


def draw_aware_probability_calibration_score(summary):
    metrics = summary["probabilityMetrics"]
    simple = summary["baselineComparison"]["simpleFavorite"]
    predicted_draws = summary["predictedResultDistribution"].get("DRAW", 0)
    viable_probability_quality = (
        predicted_draws > 0
        and metrics["brierScore"] <= simple["brierScore"]
        and metrics["logLoss"] <= simple["logLoss"]
    )
    actual_draw_rate = summary["actualResultDistribution"].get("DRAW", 0) / summary["matches"] if summary["matches"] else 0
    predicted_draw_rate = predicted_draws / summary["matches"] if summary["matches"] else 0
    capped_draw_target = min(actual_draw_rate, 0.18)
    return (
        1 if viable_probability_quality else 0,
        -metrics["logLoss"],
        -metrics["brierScore"],
        -abs(predicted_draw_rate - capped_draw_target),
        summary["resultAccuracy"],
    )


def select_draw_aware_probability_calibration(train_rows):
    candidates = []
    for params in candidate_draw_aware_probability_calibrations():
        rows = apply_draw_aware_probability_calibration_to_rows(train_rows, params)
        summary = summarize_rows(rows)
        candidates.append({
            "params": params,
            "summary": summary,
            "score": draw_aware_probability_calibration_score(summary),
        })
    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates[0], candidates[:5]


def rolling_origin_validation():
    history_rows = load_international_results(DEFAULT_RESULTS_PATH)
    predictor = WorldCupPredictor()
    year_cases_by_year = build_year_cases_by_year(YEARS, history_rows)
    folds = [
        {"trainYears": [2002, 2006], "testYears": [2010]},
        {"trainYears": [2002, 2006, 2010], "testYears": [2014]},
        {"trainYears": [2002, 2006, 2010, 2014], "testYears": [2018]},
        {"trainYears": [2002, 2006, 2010, 2014, 2018], "testYears": [2022]},
    ]
    fold_reports = []
    pooled_test_rows = []
    pooled_calibrated_test_rows = []
    pooled_draw_aware_calibrated_test_rows = []
    for fold in folds:
        selected, top_candidates = select_params(fold["trainYears"], history_rows, predictor, year_cases_by_year)
        train_rows = run_years(fold["trainYears"], selected["params"], history_rows, predictor, year_cases_by_year)
        selected_calibration, top_calibrations = select_probability_calibration(train_rows)
        selected_draw_aware_calibration, top_draw_aware_calibrations = select_draw_aware_probability_calibration(train_rows)
        test_rows = run_years(fold["testYears"], selected["params"], history_rows, predictor, year_cases_by_year)
        annotated_test_rows = annotate_rows(
            test_rows,
            "rolling_origin",
            selected["params"],
            train_years=fold["trainYears"],
            test_years=fold["testYears"],
        )
        calibrated_test_rows = apply_probability_calibration_to_rows(
            annotated_test_rows,
            selected_calibration["params"],
            validation_type_suffix="probability_calibrated",
        )
        draw_aware_calibrated_test_rows = apply_draw_aware_probability_calibration_to_rows(
            annotated_test_rows,
            selected_draw_aware_calibration["params"],
            validation_type_suffix="draw_aware_calibrated",
        )
        pooled_test_rows.extend(annotated_test_rows)
        pooled_calibrated_test_rows.extend(calibrated_test_rows)
        pooled_draw_aware_calibrated_test_rows.extend(draw_aware_calibrated_test_rows)
        fold_reports.append({
            "trainYears": fold["trainYears"],
            "testYears": fold["testYears"],
            "selectedParams": selected["params"],
            "selectedProbabilityCalibration": selected_calibration["params"],
            "selectedDrawAwareCalibration": selected_draw_aware_calibration["params"],
            "trainSummary": selected["summary"],
            "probabilityCalibrationTrainSummary": selected_calibration["summary"],
            "drawAwareCalibrationTrainSummary": selected_draw_aware_calibration["summary"],
            "testSummary": summarize_rows(test_rows),
            "calibratedTestSummary": summarize_rows(calibrated_test_rows),
            "drawAwareCalibratedTestSummary": summarize_rows(draw_aware_calibrated_test_rows),
            "testRows": annotated_test_rows,
            "calibratedTestRows": calibrated_test_rows,
            "drawAwareCalibratedTestRows": draw_aware_calibrated_test_rows,
            "topCandidateParams": [
                {"params": item["params"], "summary": item["summary"]}
                for item in top_candidates
            ],
            "topProbabilityCalibrations": [
                {"params": item["params"], "summary": item["summary"]}
                for item in top_calibrations
            ],
            "topDrawAwareCalibrations": [
                {"params": item["params"], "summary": item["summary"]}
                for item in top_draw_aware_calibrations
            ],
        })
    return {
        "method": "rolling_origin",
        "rule": "Each fold selects parameters only on earlier World Cup years, then evaluates later unseen year(s).",
        "folds": fold_reports,
        "pooledTestRows": pooled_test_rows,
        "pooledCalibratedTestRows": pooled_calibrated_test_rows,
        "pooledDrawAwareCalibratedTestRows": pooled_draw_aware_calibrated_test_rows,
        "pooledTestSummary": summarize_rows(pooled_test_rows),
        "pooledCalibratedTestSummary": summarize_rows(pooled_calibrated_test_rows),
        "pooledDrawAwareCalibratedTestSummary": summarize_rows(pooled_draw_aware_calibrated_test_rows),
    }


def fixed_2014_2018_model_validation():
    history_rows = load_international_results(DEFAULT_RESULTS_PATH)
    predictor = WorldCupPredictor()
    year_cases_by_year = build_year_cases_by_year(YEARS, history_rows)
    selected, top_candidates = select_params([2014, 2018], history_rows, predictor, year_cases_by_year)
    year_reports = []
    all_rows = []
    all_calibrated_rows = []
    all_draw_aware_calibrated_rows = []
    train_rows = run_years([2014, 2018], selected["params"], history_rows, predictor, year_cases_by_year)
    selected_calibration, top_calibrations = select_probability_calibration(train_rows)
    selected_draw_aware_calibration, top_draw_aware_calibrations = select_draw_aware_probability_calibration(train_rows)
    for year in YEARS:
        rows = run_year(year, selected["params"], history_rows, predictor, year_cases_by_year[year])
        annotated_rows = annotate_rows(rows, "fixed_2014_2018", selected["params"], year=year)
        calibrated_rows = apply_probability_calibration_to_rows(
            annotated_rows,
            selected_calibration["params"],
            validation_type_suffix="probability_calibrated",
        )
        draw_aware_calibrated_rows = apply_draw_aware_probability_calibration_to_rows(
            annotated_rows,
            selected_draw_aware_calibration["params"],
            validation_type_suffix="draw_aware_calibrated",
        )
        all_rows.extend(annotated_rows)
        all_calibrated_rows.extend(calibrated_rows)
        all_draw_aware_calibrated_rows.extend(draw_aware_calibrated_rows)
        year_reports.append({
            "year": year,
            "summary": summarize_rows(rows),
            "calibratedSummary": summarize_rows(calibrated_rows),
            "drawAwareCalibratedSummary": summarize_rows(draw_aware_calibrated_rows),
            "rows": annotated_rows,
            "calibratedRows": calibrated_rows,
            "drawAwareCalibratedRows": draw_aware_calibrated_rows,
        })
    return {
        "method": "fixed_2014_2018_params",
        "rule": "Select parameters on 2014 and 2018 only, then replay every available year with the same parameters.",
        "selectedParams": selected["params"],
        "selectedProbabilityCalibration": selected_calibration["params"],
        "selectedDrawAwareCalibration": selected_draw_aware_calibration["params"],
        "trainSummary2014_2018": selected["summary"],
        "probabilityCalibrationTrainSummary2014_2018": selected_calibration["summary"],
        "drawAwareCalibrationTrainSummary2014_2018": selected_draw_aware_calibration["summary"],
        "topCandidateParams": [
            {"params": item["params"], "summary": item["summary"]}
            for item in top_candidates
        ],
        "topProbabilityCalibrations": [
            {"params": item["params"], "summary": item["summary"]}
            for item in top_calibrations
        ],
        "topDrawAwareCalibrations": [
            {"params": item["params"], "summary": item["summary"]}
            for item in top_draw_aware_calibrations
        ],
        "yearReports": year_reports,
        "allYearsSummary": summarize_rows(all_rows),
        "allYearsCalibratedSummary": summarize_rows(all_calibrated_rows),
        "allYearsDrawAwareCalibratedSummary": summarize_rows(all_draw_aware_calibrated_rows),
    }


def calibration_bucket_error_summary(summary):
    buckets = summary.get("baselineComparison", {}).get("calibrationBuckets", [])
    if not buckets:
        return {"weightedCalibrationError": 1, "maxCalibrationBucketError": 1}
    total_matches = sum(bucket.get("matches", 0) for bucket in buckets)
    weighted_error = (
        sum(bucket.get("calibrationError", 0) * bucket.get("matches", 0) for bucket in buckets) / total_matches
        if total_matches
        else 1
    )
    max_error = max(bucket.get("calibrationError", 0) for bucket in buckets)
    return {
        "weightedCalibrationError": round(weighted_error, 4),
        "maxCalibrationBucketError": round(max_error, 4),
    }


def criterion(name, passed, actual, threshold):
    return {
        "name": name,
        "passed": bool(passed),
        "actual": actual,
        "threshold": threshold,
    }


def evaluate_calibration_candidate(name, summary, baseline_summary, gate_policy=None):
    gate_policy = gate_policy or CALIBRATION_DECISION_GATE
    metrics = summary["probabilityMetrics"]
    baselines = baseline_summary["baselineComparison"]
    draw = summary.get("baselineComparison", {}).get("drawDiagnostics", {})
    bucket_errors = calibration_bucket_error_summary(summary)
    actual_draw_rate = draw.get("actualDrawRate", 0)
    predicted_draw_rate = draw.get("predictedDrawRate", 0)
    min_draw_rate = actual_draw_rate * gate_policy["minDrawRateVsActual"]
    max_draw_rate = actual_draw_rate * gate_policy["maxDrawRateVsActual"]
    criteria = [
        criterion(
            "minimum rolling-origin sample size",
            summary["matches"] >= gate_policy["minOutOfSampleMatches"],
            summary["matches"],
            f">= {gate_policy['minOutOfSampleMatches']}",
        ),
        criterion(
            "draw headline rate floor",
            predicted_draw_rate >= min_draw_rate,
            round(predicted_draw_rate, 4),
            f">= {round(min_draw_rate, 4)} ({pct(gate_policy['minDrawRateVsActual'])} of actual draw rate)",
        ),
        criterion(
            "draw headline rate ceiling",
            predicted_draw_rate <= max_draw_rate,
            round(predicted_draw_rate, 4),
            f"<= {round(max_draw_rate, 4)} ({pct(gate_policy['maxDrawRateVsActual'])} of actual draw rate)",
        ),
        criterion(
            "weighted calibration bucket error",
            bucket_errors["weightedCalibrationError"] <= gate_policy["maxWeightedCalibrationError"],
            bucket_errors["weightedCalibrationError"],
            f"<= {gate_policy['maxWeightedCalibrationError']}",
        ),
        criterion(
            "max calibration bucket error",
            bucket_errors["maxCalibrationBucketError"] <= gate_policy["maxBucketCalibrationError"],
            bucket_errors["maxCalibrationBucketError"],
            f"<= {gate_policy['maxBucketCalibrationError']}",
        ),
    ]
    for baseline_name in gate_policy["baselineNames"]:
        baseline_metrics = baselines[baseline_name]
        criteria.extend([
            criterion(
                f"Brier beats {baseline_name}",
                metrics["brierScore"] < baseline_metrics["brierScore"],
                metrics["brierScore"],
                f"< {baseline_metrics['brierScore']}",
            ),
            criterion(
                f"Log Loss beats {baseline_name}",
                metrics["logLoss"] < baseline_metrics["logLoss"],
                metrics["logLoss"],
                f"< {baseline_metrics['logLoss']}",
            ),
        ])
    failed = [item["name"] for item in criteria if not item["passed"]]
    status = "APPROVED_FOR_CANONICAL" if not failed else "REJECTED_DIAGNOSTIC_ONLY"
    return {
        "candidate": name,
        "status": status,
        "approvedForCanonical": status == "APPROVED_FOR_CANONICAL",
        "summary": {
            "matches": summary["matches"],
            "resultAccuracy": summary["resultAccuracy"],
            "brierScore": metrics["brierScore"],
            "logLoss": metrics["logLoss"],
            "headlineDistribution": dict(summary.get("predictedResultDistribution", {})),
            "actualDistribution": dict(summary.get("actualResultDistribution", {})),
            "drawDiagnostics": dict(draw),
            **bucket_errors,
        },
        "criteria": criteria,
        "failureReasons": failed,
    }


def build_calibration_decision_gate(rolling_validation, gate_policy=None):
    gate_policy = gate_policy or CALIBRATION_DECISION_GATE
    baseline_summary = rolling_validation["pooledTestSummary"]
    candidates = [
        ("Raw MatchOracle", rolling_validation["pooledTestSummary"]),
        ("Probability-Calibrated Candidate", rolling_validation["pooledCalibratedTestSummary"]),
        ("Draw-aware Calibrated Candidate", rolling_validation["pooledDrawAwareCalibratedTestSummary"]),
    ]
    evaluations = [
        evaluate_calibration_candidate(name, summary, baseline_summary, gate_policy)
        for name, summary in candidates
    ]
    approved = [item["candidate"] for item in evaluations if item["approvedForCanonical"]]
    return {
        "scope": "rolling_origin_pooled_only",
        "policy": dict(gate_policy),
        "approvedCandidates": approved,
        "defaultCanonicalDecision": (
            "No candidate is approved for default canonical promotion; keep current default output unchanged."
            if not approved
            else f"{approved[0]} is eligible for default canonical promotion."
        ),
        "evaluations": evaluations,
    }


def pct(value):
    return f"{value * 100:.2f}%"


def hit_rate(summary, hits_key, rate_key):
    return f"{summary[hits_key]}/{summary['matches']} = {pct(summary[rate_key])}"


def params_text(params):
    return ", ".join(f"{key}={value}" for key, value in params.items())


def wdl(summary, key="predictedResultDistribution"):
    distribution = summary.get(key, {})
    return "-".join(str(distribution.get(result, 0)) for result in ("HOME_WIN", "DRAW", "AWAY_WIN"))


def metric(summary, key):
    return summary.get("probabilityMetrics", {}).get(key, "-")


def draw_diag(summary, key):
    return summary.get("baselineComparison", {}).get("drawDiagnostics", {}).get(key, "-")


def baseline(summary, baseline_name, key):
    return summary.get("baselineComparison", {}).get(baseline_name, {}).get(key, "-")


def baseline_pct(summary, baseline_name, key):
    value = baseline(summary, baseline_name, key)
    return "-" if value == "-" else pct(value)


def model_vs_baseline_rows(summary):
    return [
        ("MatchOracle", pct(summary["resultAccuracy"]), metric(summary, "brierScore"), metric(summary, "logLoss")),
        (
            "Simple Favorite",
            baseline_pct(summary, "simpleFavorite", "resultAccuracy"),
            baseline(summary, "simpleFavorite", "brierScore"),
            baseline(summary, "simpleFavorite", "logLoss"),
        ),
        (
            "Elo Rank",
            baseline_pct(summary, "eloRank", "resultAccuracy"),
            baseline(summary, "eloRank", "brierScore"),
            baseline(summary, "eloRank", "logLoss"),
        ),
    ]


def candidate_comparison_rows(raw_summary, calibrated_summary, draw_aware_summary):
    return [
        ("Raw MatchOracle", pct(raw_summary["resultAccuracy"]), metric(raw_summary, "brierScore"), metric(raw_summary, "logLoss"), wdl(raw_summary)),
        (
            "Probability-Calibrated Candidate",
            pct(calibrated_summary["resultAccuracy"]),
            metric(calibrated_summary, "brierScore"),
            metric(calibrated_summary, "logLoss"),
            wdl(calibrated_summary),
        ),
        (
            "Draw-aware Calibrated Candidate",
            pct(draw_aware_summary["resultAccuracy"]),
            metric(draw_aware_summary, "brierScore"),
            metric(draw_aware_summary, "logLoss"),
            wdl(draw_aware_summary),
        ),
        (
            "Simple Favorite",
            baseline_pct(raw_summary, "simpleFavorite", "resultAccuracy"),
            baseline(raw_summary, "simpleFavorite", "brierScore"),
            baseline(raw_summary, "simpleFavorite", "logLoss"),
            "-",
        ),
        (
            "Elo Rank",
            baseline_pct(raw_summary, "eloRank", "resultAccuracy"),
            baseline(raw_summary, "eloRank", "brierScore"),
            baseline(raw_summary, "eloRank", "logLoss"),
            "-",
        ),
    ]


def render_candidate_comparison_table(raw_summary, calibrated_summary, draw_aware_summary):
    lines = [
        "| Candidate | 1X2 accuracy | Brier Score | Log Loss | H-D-A headline |",
        "|---|---:|---:|---:|---|",
    ]
    for name, accuracy, brier, loss, distribution in candidate_comparison_rows(raw_summary, calibrated_summary, draw_aware_summary):
        lines.append(f"| {name} | {accuracy} | {brier} | {loss} | {distribution} |")
    return "\n".join(lines)


def render_draw_diagnostics_table(named_summaries):
    lines = [
        "| Candidate | Predicted draws | Predicted draw rate | Actual draws | Actual draw rate | Avg draw probability | Avg draw probability on actual draws |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, summary in named_summaries:
        predicted_rate = draw_diag(summary, "predictedDrawRate")
        actual_rate = draw_diag(summary, "actualDrawRate")
        average_draw = draw_diag(summary, "averageDrawProbability")
        actual_draw_average = draw_diag(summary, "actualDrawAverageProbability")
        lines.append(
            "| {name} | {predicted_draws} | {predicted_rate} | {actual_draws} | {actual_rate} | {average_draw} | {actual_draw_average} |".format(
                name=name,
                predicted_draws=draw_diag(summary, "predictedDraws"),
                predicted_rate="-" if predicted_rate == "-" else pct(predicted_rate),
                actual_draws=draw_diag(summary, "actualDraws"),
                actual_rate="-" if actual_rate == "-" else pct(actual_rate),
                average_draw="-" if average_draw == "-" else pct(average_draw),
                actual_draw_average="-" if actual_draw_average == "-" else pct(actual_draw_average),
            )
        )
    return "\n".join(lines)


def render_model_vs_baseline_table(summary):
    lines = [
        "| Model | 1X2 accuracy | Brier Score | Log Loss |",
        "|---|---:|---:|---:|",
    ]
    for name, accuracy, brier, loss in model_vs_baseline_rows(summary):
        lines.append(f"| {name} | {accuracy} | {brier} | {loss} |")
    return "\n".join(lines)


def render_calibration_buckets(summary):
    buckets = summary.get("baselineComparison", {}).get("calibrationBuckets", [])
    if not buckets:
        return "_No calibration buckets available._"
    lines = [
        "| Bucket | Matches | Avg confidence | Observed accuracy | Error |",
        "|---|---:|---:|---:|---:|",
    ]
    for bucket in buckets:
        lines.append(
            "| {bucket} | {matches} | {confidence} | {observed} | {error} |".format(
                bucket=bucket["bucket"],
                matches=bucket["matches"],
                confidence=pct(bucket["averageConfidence"]),
                observed=pct(bucket["observedAccuracy"]),
                error=pct(bucket["calibrationError"]),
            )
        )
    return "\n".join(lines)


def render_calibration_decision_gate(gate):
    policy = gate["policy"]
    lines = [
        "## Calibration Decision Gate",
        "",
        f"Decision: {gate['defaultCanonicalDecision']}",
        "",
        "Promotion policy:",
        f"- Rolling-origin sample size must be at least {policy['minOutOfSampleMatches']} matches.",
        "- Brier Score and Log Loss must beat both Simple Favorite and Elo Rank.",
        f"- Predicted draw headline rate must be between {pct(policy['minDrawRateVsActual'])} and {pct(policy['maxDrawRateVsActual'])} of the actual draw rate.",
        f"- Weighted calibration bucket error must be <= {policy['maxWeightedCalibrationError']}; max bucket error must be <= {policy['maxBucketCalibrationError']}.",
        "",
        "| Candidate | Gate status | 1X2 accuracy | Brier | Log Loss | H-D-A headline | Draw rate | Weighted bucket error | Max bucket error | Failed criteria |",
        "|---|---|---:|---:|---:|---|---:|---:|---:|---|",
    ]
    for item in gate["evaluations"]:
        summary = item["summary"]
        draw = summary.get("drawDiagnostics", {})
        failed = "; ".join(item["failureReasons"]) if item["failureReasons"] else "-"
        lines.append(
            "| {candidate} | {status} | {accuracy} | {brier} | {loss} | {headline} | {draw_rate} | {weighted_error} | {max_error} | {failed} |".format(
                candidate=item["candidate"],
                status=item["status"],
                accuracy=pct(summary["resultAccuracy"]),
                brier=summary["brierScore"],
                loss=summary["logLoss"],
                headline="-".join(
                    str(summary.get("headlineDistribution", {}).get(result, 0))
                    for result in ("HOME_WIN", "DRAW", "AWAY_WIN")
                ),
                draw_rate=pct(draw.get("predictedDrawRate", 0)),
                weighted_error=summary["weightedCalibrationError"],
                max_error=summary["maxCalibrationBucketError"],
                failed=failed,
            )
        )
    return "\n".join(lines)


def iter_report_match_rows(report):
    for fold in report["rollingOriginValidation"]["folds"]:
        for row in fold.get("testRows", []):
            yield row
        for row in fold.get("calibratedTestRows", []):
            yield row
        for row in fold.get("drawAwareCalibratedTestRows", []):
            yield row
    for year_report in report["fixed2014_2018Validation"]["yearReports"]:
        for row in year_report.get("rows", []):
            yield row
        for row in year_report.get("calibratedRows", []):
            yield row
        for row in year_report.get("drawAwareCalibratedRows", []):
            yield row


def flatten_match_row(row):
    simple = row.get("baselines", {}).get("simpleFavorite", {})
    elo = row.get("baselines", {}).get("eloRank", {})
    simple_probabilities = simple.get("probabilities", {})
    elo_probabilities = elo.get("probabilities", {})
    probabilities = row.get("probabilities", {})
    actual = row["actualResult"]
    return {
        "validationType": row.get("validationType", ""),
        "year": row.get("year", ""),
        "trainYears": ",".join(map(str, row.get("trainYears", []))),
        "testYears": ",".join(map(str, row.get("testYears", []))),
        "selectedParams": json.dumps(row.get("selectedParams", {}), sort_keys=True),
        "probabilityCalibration": json.dumps(row.get("probabilityCalibration", {}), sort_keys=True),
        "calibrationCandidate": row.get("calibrationCandidate", ""),
        "matchId": row["matchId"],
        "match": row["match"],
        "stage": row["stage"],
        "predictedResult": row["predictedResult"],
        "actualResult": actual,
        "predictedScore": row["predictedScoreText"],
        "actualScore": row["actualScoreText"],
        "topScoreHit": row["topScoreHit"],
        "modelHome": probabilities.get("home"),
        "modelDraw": probabilities.get("draw"),
        "modelAway": probabilities.get("away"),
        "modelBrier": round(brier_score(probabilities, actual), 4),
        "modelLogLoss": round(log_loss(probabilities, actual), 4),
        "simpleFavoritePredictedResult": simple.get("predictedResult"),
        "simpleFavoriteHome": simple_probabilities.get("home"),
        "simpleFavoriteDraw": simple_probabilities.get("draw"),
        "simpleFavoriteAway": simple_probabilities.get("away"),
        "simpleFavoriteBrier": round(brier_score(simple_probabilities, actual), 4) if simple_probabilities else "",
        "simpleFavoriteLogLoss": round(log_loss(simple_probabilities, actual), 4) if simple_probabilities else "",
        "eloRankPredictedResult": elo.get("predictedResult"),
        "eloRankHome": elo_probabilities.get("home"),
        "eloRankDraw": elo_probabilities.get("draw"),
        "eloRankAway": elo_probabilities.get("away"),
        "eloRankBrier": round(brier_score(elo_probabilities, actual), 4) if elo_probabilities else "",
        "eloRankLogLoss": round(log_loss(elo_probabilities, actual), 4) if elo_probabilities else "",
    }


def write_match_rows_csv(report, csv_path=DEFAULT_ROWS_CSV_REPORT):
    rows = [flatten_match_row(row) for row in iter_report_match_rows(report)]
    if not rows:
        return csv_path
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    with open(csv_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return csv_path


def render_cross_validation_markdown(report):
    lines = [
        "# World Cup Cross Validation Report",
        "",
        "Generated by `python3 -m src.cross_validate_worldcups --write-reports`.",
        "Labels use 90-minute regular-time scores. Brier Score and Log Loss are lower-is-better probability quality metrics.",
        "Calibration buckets use 0.1 confidence-width bins.",
        "Per-match replay rows are written to `reports/worldcup_cross_validation_rows.csv` when using `--write-reports`.",
        "",
        "## Data Sources",
    ]
    for key, value in report["sources"].items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Parameter Grid"])
    for key, value in report["parameterGrid"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Probability Calibration Grids"])
    for key, value in report.get("probabilityCalibrationGrid", {}).items():
        lines.append(f"- {key}: {value}")
    for key, value in report.get("drawAwareCalibrationGrid", {}).items():
        lines.append(f"- drawAware.{key}: {value}")

    rolling = report["rollingOriginValidation"]
    fixed = report["fixed2014_2018Validation"]
    decision_gate = report.get("calibrationDecisionGate") or build_calibration_decision_gate(rolling)
    lines.extend([
        "",
        "## Key Findings",
        "- Rolling-origin out-of-sample performance is the main truth check.",
        "- Raw MatchOracle still does not beat Simple Favorite / Elo Rank on rolling-origin probability quality.",
        f"- Rolling pooled Raw MatchOracle: {pct(rolling['pooledTestSummary']['resultAccuracy'])} 1X2, Brier {metric(rolling['pooledTestSummary'], 'brierScore')}, Log Loss {metric(rolling['pooledTestSummary'], 'logLoss')}.",
        f"- Rolling pooled Simple Favorite: {baseline_pct(rolling['pooledTestSummary'], 'simpleFavorite', 'resultAccuracy')} 1X2, Brier {baseline(rolling['pooledTestSummary'], 'simpleFavorite', 'brierScore')}, Log Loss {baseline(rolling['pooledTestSummary'], 'simpleFavorite', 'logLoss')}.",
        f"- Rolling pooled Probability-Calibrated Candidate: {pct(rolling['pooledCalibratedTestSummary']['resultAccuracy'])} 1X2, Brier {metric(rolling['pooledCalibratedTestSummary'], 'brierScore')}, Log Loss {metric(rolling['pooledCalibratedTestSummary'], 'logLoss')}.",
        f"- Rolling pooled Draw-aware Calibrated Candidate: {pct(rolling['pooledDrawAwareCalibratedTestSummary']['resultAccuracy'])} 1X2, Brier {metric(rolling['pooledDrawAwareCalibratedTestSummary'], 'brierScore')}, Log Loss {metric(rolling['pooledDrawAwareCalibratedTestSummary'], 'logLoss')}, H-D-A {wdl(rolling['pooledDrawAwareCalibratedTestSummary'])}.",
        f"- Draw-aware vs Simple Favorite: better Brier / Log Loss ({metric(rolling['pooledDrawAwareCalibratedTestSummary'], 'brierScore')} / {metric(rolling['pooledDrawAwareCalibratedTestSummary'], 'logLoss')} vs {baseline(rolling['pooledTestSummary'], 'simpleFavorite', 'brierScore')} / {baseline(rolling['pooledTestSummary'], 'simpleFavorite', 'logLoss')}).",
        f"- Draw-aware vs Elo Rank: worse Brier but better Log Loss ({metric(rolling['pooledDrawAwareCalibratedTestSummary'], 'brierScore')} / {metric(rolling['pooledDrawAwareCalibratedTestSummary'], 'logLoss')} vs {baseline(rolling['pooledTestSummary'], 'eloRank', 'brierScore')} / {baseline(rolling['pooledTestSummary'], 'eloRank', 'logLoss')}).",
        f"- Calibration decision gate: {decision_gate['defaultCanonicalDecision']}",
        "- The original calibrated candidate improves probability metrics, but it suppresses draw as a headline pick. The draw-aware candidate restores some draw headlines with a probability-quality tradeoff, so both remain diagnostic only and not shippable defaults.",
        f"- Fixed 2014/2018 replay has higher Raw MatchOracle 1X2 accuracy ({pct(fixed['allYearsSummary']['resultAccuracy'])}) than Simple Favorite ({baseline_pct(fixed['allYearsSummary'], 'simpleFavorite', 'resultAccuracy')}), but still worse Brier / Log Loss.",
    ])

    lines.extend(["", render_calibration_decision_gate(decision_gate)])

    lines.extend([
        "",
        "## Rolling-Origin Blind Tests",
        "| Train years | Test year | Selected params | Probability calibration | Draw-aware calibration | Raw 1X2 | Calibrated 1X2 | Draw-aware 1X2 | Simple Favorite 1X2 | Elo 1X2 | Top5 | Raw Brier | Calibrated Brier | Draw-aware Brier | Simple Brier | Elo Brier | Raw Log Loss | Calibrated Log Loss | Draw-aware Log Loss | Simple Log Loss | Elo Log Loss | Raw H-D-A | Calibrated H-D-A | Draw-aware H-D-A | Actual H-D-A |",
        "|---|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|",
    ])
    for fold in rolling["folds"]:
        summary = fold["testSummary"]
        calibrated_summary = fold["calibratedTestSummary"]
        draw_aware_summary = fold["drawAwareCalibratedTestSummary"]
        lines.append(
            "| {train} | {test} | {params} | {calibration} | {draw_calibration} | {model_acc} | {cal_acc} | {draw_acc} | {simple_acc} | {elo_acc} | {top5} | {model_brier} | {cal_brier} | {draw_brier} | {simple_brier} | {elo_brier} | {model_loss} | {cal_loss} | {draw_loss} | {simple_loss} | {elo_loss} | {predicted} | {cal_predicted} | {draw_predicted} | {actual} |".format(
                train=", ".join(map(str, fold["trainYears"])),
                test=", ".join(map(str, fold["testYears"])),
                params=params_text(fold["selectedParams"]),
                calibration=params_text(fold["selectedProbabilityCalibration"]),
                draw_calibration=params_text(fold["selectedDrawAwareCalibration"]),
                model_acc=hit_rate(summary, "resultHits", "resultAccuracy"),
                cal_acc=hit_rate(calibrated_summary, "resultHits", "resultAccuracy"),
                draw_acc=hit_rate(draw_aware_summary, "resultHits", "resultAccuracy"),
                simple_acc=baseline_pct(summary, "simpleFavorite", "resultAccuracy"),
                elo_acc=baseline_pct(summary, "eloRank", "resultAccuracy"),
                top5=hit_rate(summary, "top5ScoreHits", "top5ScoreCoverage"),
                model_brier=metric(summary, "brierScore"),
                cal_brier=metric(calibrated_summary, "brierScore"),
                draw_brier=metric(draw_aware_summary, "brierScore"),
                simple_brier=baseline(summary, "simpleFavorite", "brierScore"),
                elo_brier=baseline(summary, "eloRank", "brierScore"),
                model_loss=metric(summary, "logLoss"),
                cal_loss=metric(calibrated_summary, "logLoss"),
                draw_loss=metric(draw_aware_summary, "logLoss"),
                simple_loss=baseline(summary, "simpleFavorite", "logLoss"),
                elo_loss=baseline(summary, "eloRank", "logLoss"),
                predicted=wdl(summary),
                cal_predicted=wdl(calibrated_summary),
                draw_predicted=wdl(draw_aware_summary),
                actual=wdl(summary, "actualResultDistribution"),
            )
        )

    lines.extend([
        "",
        "### Rolling Pooled Candidate Comparison",
        render_candidate_comparison_table(
            rolling["pooledTestSummary"],
            rolling["pooledCalibratedTestSummary"],
            rolling["pooledDrawAwareCalibratedTestSummary"],
        ),
        "",
        "### Rolling Pooled Draw Diagnostics",
        render_draw_diagnostics_table([
            ("Raw MatchOracle", rolling["pooledTestSummary"]),
            ("Probability-Calibrated Candidate", rolling["pooledCalibratedTestSummary"]),
            ("Draw-aware Calibrated Candidate", rolling["pooledDrawAwareCalibratedTestSummary"]),
        ]),
        "",
        "### Rolling Pooled Probability Quality",
        render_model_vs_baseline_table(rolling["pooledTestSummary"]),
        "",
        "### Rolling Pooled Probability-Calibrated Candidate",
        render_model_vs_baseline_table(rolling["pooledCalibratedTestSummary"]),
        "",
        "### Rolling Pooled Draw-aware Calibrated Candidate",
        render_model_vs_baseline_table(rolling["pooledDrawAwareCalibratedTestSummary"]),
        "",
        f"Rolling pooled Top5 score coverage: {hit_rate(rolling['pooledTestSummary'], 'top5ScoreHits', 'top5ScoreCoverage')}.",
        "",
        "### Rolling Pooled Calibration Buckets",
        render_calibration_buckets(rolling["pooledTestSummary"]),
    ])

    lines.extend([
        "",
        "## Fixed 2014/2018 Parameter Replay",
        f"Selected on 2014/2018 only: {params_text(fixed['selectedParams'])}",
        f"Selected probability calibration on 2014/2018: {params_text(fixed['selectedProbabilityCalibration'])}",
        f"Selected draw-aware calibration on 2014/2018: {params_text(fixed['selectedDrawAwareCalibration'])}",
        "",
        "| Year | Raw 1X2 | Calibrated 1X2 | Draw-aware 1X2 | Simple Favorite 1X2 | Elo 1X2 | Top5 | Raw Brier | Calibrated Brier | Draw-aware Brier | Simple Brier | Elo Brier | Raw Log Loss | Calibrated Log Loss | Draw-aware Log Loss | Simple Log Loss | Elo Log Loss | Raw H-D-A | Calibrated H-D-A | Draw-aware H-D-A | Actual H-D-A |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|",
    ])
    for year_report in fixed["yearReports"]:
        summary = year_report["summary"]
        calibrated_summary = year_report["calibratedSummary"]
        draw_aware_summary = year_report["drawAwareCalibratedSummary"]
        lines.append(
            "| {year} | {model_acc} | {cal_acc} | {draw_acc} | {simple_acc} | {elo_acc} | {top5} | {model_brier} | {cal_brier} | {draw_brier} | {simple_brier} | {elo_brier} | {model_loss} | {cal_loss} | {draw_loss} | {simple_loss} | {elo_loss} | {predicted} | {cal_predicted} | {draw_predicted} | {actual} |".format(
                year=year_report["year"],
                model_acc=hit_rate(summary, "resultHits", "resultAccuracy"),
                cal_acc=hit_rate(calibrated_summary, "resultHits", "resultAccuracy"),
                draw_acc=hit_rate(draw_aware_summary, "resultHits", "resultAccuracy"),
                simple_acc=baseline_pct(summary, "simpleFavorite", "resultAccuracy"),
                elo_acc=baseline_pct(summary, "eloRank", "resultAccuracy"),
                top5=hit_rate(summary, "top5ScoreHits", "top5ScoreCoverage"),
                model_brier=metric(summary, "brierScore"),
                cal_brier=metric(calibrated_summary, "brierScore"),
                draw_brier=metric(draw_aware_summary, "brierScore"),
                simple_brier=baseline(summary, "simpleFavorite", "brierScore"),
                elo_brier=baseline(summary, "eloRank", "brierScore"),
                model_loss=metric(summary, "logLoss"),
                cal_loss=metric(calibrated_summary, "logLoss"),
                draw_loss=metric(draw_aware_summary, "logLoss"),
                simple_loss=baseline(summary, "simpleFavorite", "logLoss"),
                elo_loss=baseline(summary, "eloRank", "logLoss"),
                predicted=wdl(summary),
                cal_predicted=wdl(calibrated_summary),
                draw_predicted=wdl(draw_aware_summary),
                actual=wdl(summary, "actualResultDistribution"),
            )
        )

    lines.extend([
        "",
        "### Fixed All-Year Candidate Comparison",
        render_candidate_comparison_table(
            fixed["allYearsSummary"],
            fixed["allYearsCalibratedSummary"],
            fixed["allYearsDrawAwareCalibratedSummary"],
        ),
        "",
        "### Fixed All-Year Draw Diagnostics",
        render_draw_diagnostics_table([
            ("Raw MatchOracle", fixed["allYearsSummary"]),
            ("Probability-Calibrated Candidate", fixed["allYearsCalibratedSummary"]),
            ("Draw-aware Calibrated Candidate", fixed["allYearsDrawAwareCalibratedSummary"]),
        ]),
        "",
        "### Fixed All-Year Probability Quality",
        render_model_vs_baseline_table(fixed["allYearsSummary"]),
        "",
        "### Fixed All-Year Probability-Calibrated Candidate",
        render_model_vs_baseline_table(fixed["allYearsCalibratedSummary"]),
        "",
        "### Fixed All-Year Draw-aware Calibrated Candidate",
        render_model_vs_baseline_table(fixed["allYearsDrawAwareCalibratedSummary"]),
        "",
        f"Fixed all-year Top5 score coverage: {hit_rate(fixed['allYearsSummary'], 'top5ScoreHits', 'top5ScoreCoverage')}.",
        "",
        "### Fixed Replay Calibration Buckets by Year",
        "| Year | Bucket | Matches | Avg confidence | Observed accuracy | Error |",
        "|---:|---|---:|---:|---:|---:|",
    ])
    for year_report in fixed["yearReports"]:
        year = year_report["year"]
        for bucket in year_report["summary"].get("baselineComparison", {}).get("calibrationBuckets", []):
            lines.append(
                "| {year} | {bucket} | {matches} | {confidence} | {observed} | {error} |".format(
                    year=year,
                    bucket=bucket["bucket"],
                    matches=bucket["matches"],
                    confidence=pct(bucket["averageConfidence"]),
                    observed=pct(bucket["observedAccuracy"]),
                    error=pct(bucket["calibrationError"]),
                )
            )

    lines.extend([
        "",
        "## Caveats",
        "- F05/F06 tournament context is available, but current validation still does not prove it should be active in the stable score.",
        "- Draw-aware calibration is diagnostic only: it reduces the zero-draw headline artifact but is not approved as the default canonical probability.",
        "- Draw prediction and probability calibration remain the main weaknesses.",
        "- Simple Favorite and Elo Rank are sanity baselines, not optimized market models.",
        "- No odds baseline is included here; F12 CSV import is still a later step.",
        "",
    ])
    return "\n".join(lines)


def build_cross_validation_report():
    rolling_validation = rolling_origin_validation()
    fixed_validation = fixed_2014_2018_model_validation()
    return {
        "dataYears": YEARS,
        "sources": {
            "worldCupResults": "openfootball/worldcup.json for 2002-2022",
            "eloSnapshots": "international-football.net pre-tournament tables",
            "historicalFeatures": "martj42/international_results rows dated before each kickoff",
        },
        "parameterGrid": PARAM_GRID,
        "probabilityCalibrationGrid": PROBABILITY_CALIBRATION_GRID,
        "drawAwareCalibrationGrid": DRAW_AWARE_CALIBRATION_GRID,
        "calibrationDecisionGate": build_calibration_decision_gate(rolling_validation),
        "rollingOriginValidation": rolling_validation,
        "fixed2014_2018Validation": fixed_validation,
    }


def write_report_files(report, json_path=DEFAULT_JSON_REPORT, md_path=DEFAULT_MD_REPORT, rows_csv_path=DEFAULT_ROWS_CSV_REPORT):
    os.makedirs(os.path.dirname(json_path), exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write(render_cross_validation_markdown(report))
    write_match_rows_csv(report, rows_csv_path)
    return {"json": json_path, "markdown": md_path, "rowsCsv": rows_csv_path}


def parse_args():
    parser = ArgumentParser(description="Run World Cup rolling-origin cross validation.")
    parser.add_argument("--write-reports", action="store_true", help="Write JSON and Markdown reports under reports/.")
    parser.add_argument("--json-path", default=DEFAULT_JSON_REPORT, help="JSON report path when --write-reports is used.")
    parser.add_argument("--md-path", default=DEFAULT_MD_REPORT, help="Markdown report path when --write-reports is used.")
    parser.add_argument("--rows-csv-path", default=DEFAULT_ROWS_CSV_REPORT, help="Per-match CSV report path when --write-reports is used.")
    parser.add_argument("--stdout", action="store_true", help="Print JSON to stdout even when writing report files.")
    return parser.parse_args()


def main():
    args = parse_args()
    report = build_cross_validation_report()
    if args.write_reports:
        paths = write_report_files(report, args.json_path, args.md_path, args.rows_csv_path)
        print(f"Wrote {paths['json']}")
        print(f"Wrote {paths['markdown']}")
        print(f"Wrote {paths['rowsCsv']}")
    if not args.write_reports or args.stdout:
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
