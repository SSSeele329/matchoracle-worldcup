from datetime import datetime, timezone

from .factors import build_baseline_factors, confidence_from_factors, probabilities_from_factors, select_result_key, weighted_edge
from .knockout import build_knockout_layers
from .lambda_model import adjust_lambdas_with_factor_edge, apply_f05_motivation_context, apply_lineup_shock, calculate_lambda
from .lineup_evidence import enrich_match_input_with_f04p
from .lineup_check import final_lineup_check
from .market import build_market_aligned_calibrated_probability, build_market_analysis, devig_decimal_odds
from .narrative import build_final_risk_narrative
from .poisson import apply_dixon_coles_adjustment, adjust_for_knockout, filter_scenarios_by_result, generate_score_matrix, get_predicted_score, get_representative_score, get_top_score_scenarios, outcome_probabilities_from_matrix
from .reliability import build_data_reliability, market_divergence_allowed
from .rules import get_competition_rules
from .snapshot import build_canonical_probability, build_prediction_manifest
from .upset_risk import build_upset_risk
from .weights import MODEL_ARCHITECTURE, select_weight_scheme


MODEL_VERSION = "V4-P0"


class WorldCupPredictor:
    def predict(self, match_input):
        match_input, f04p_expected_lineup = enrich_match_input_with_f04p(match_input)
        match = match_input.get("match", {})
        stage = match.get("stage", "GROUP_STAGE")
        competition_rules = get_competition_rules(stage)
        weight_scheme = select_weight_scheme(stage)
        data_reliability = build_data_reliability(match_input)
        if data_reliability["status"] == "FATAL":
            return self._make_aborted_prediction(match_input, data_reliability, weight_scheme, competition_rules)

        decimal_odds = match_input.get("decimalOdds")
        if decimal_odds and not match_input.get("oddsProbabilities"):
            market = devig_decimal_odds(decimal_odds)
            if market:
                match_input = dict(match_input)
                match_input["oddsProbabilities"] = market["probabilities"]
        factors = build_baseline_factors(match_input)
        factor_probabilities = probabilities_from_factors(factors, stage)
        factor_edge = weighted_edge(factors)
        result_map = {"home": "HOME_WIN", "draw": "DRAW", "away": "AWAY_WIN"}

        goal_data = match_input.get("goalData", {})
        home_goal_data = dict(goal_data.get("home") or {})
        away_goal_data = dict(goal_data.get("away") or {})
        f07_factor = next(f for f in factors if f["id"] == "F07")
        home_goal_data.setdefault("f07DataQuality", f07_factor["dataQuality"])
        away_goal_data.setdefault("f07DataQuality", f07_factor["dataQuality"])
        raw_home_lambda = calculate_lambda(home_goal_data, away_goal_data)
        raw_away_lambda = calculate_lambda(away_goal_data, home_goal_data)
        home_lambda, away_lambda = adjust_lambdas_with_factor_edge(raw_home_lambda, raw_away_lambda, factor_edge)
        draw_adjustment_rho = match_input.get("drawAdjustmentRho", 0)
        home_lambda, away_lambda, draw_adjustment_rho = apply_f05_motivation_context(
            home_lambda,
            away_lambda,
            match_input.get("matchContext"),
            draw_adjustment_rho,
        )
        lambda_scale = float(match_input.get("lambdaScale", 1))
        if lambda_scale != 1:
            home_lambda = round(min(3.6, home_lambda * lambda_scale), 3)
            away_lambda = round(min(3.6, away_lambda * lambda_scale), 3)
        lineup_check = final_lineup_check(match_input.get("expectedLineup"), match_input.get("actualLineup"))
        pre_lineup_home_lambda = home_lambda
        pre_lineup_away_lambda = away_lambda
        home_lambda, away_lambda = apply_lineup_shock(home_lambda, away_lambda, lineup_check)

        matrix = generate_score_matrix(home_lambda, away_lambda, max_goals=7)
        matrix = apply_dixon_coles_adjustment(matrix, home_lambda, away_lambda, draw_adjustment_rho)
        if weight_scheme in {"KNOCKOUT", "SEMI_AND_FINAL"}:
            matrix = adjust_for_knockout(matrix)
        probabilities = outcome_probabilities_from_matrix(matrix)
        result_key = select_result_key(probabilities, stage)
        knockout_layers = (
            build_knockout_layers(probabilities, home_lambda, away_lambda, match_input)
            if competition_rules["advancementRequiresWinner"]
            else {"extraTime": None, "penalties": None, "advancement": None}
        )
        modal_score = get_predicted_score(matrix, result_key)
        predicted_score = get_representative_score(matrix, result_key)
        raw_top_scenarios = get_top_score_scenarios(matrix)
        result_scenarios = filter_scenarios_by_result(matrix, result_key)
        top_scenarios = get_top_score_scenarios(result_scenarios or matrix)

        opening_decimal_odds = match_input.get("openingDecimalOdds")
        public_ticket_percent = match_input.get("publicTicketPercent")
        market_analysis = build_market_analysis(probabilities, decimal_odds, opening_decimal_odds, public_ticket_percent) if decimal_odds else None
        market_aligned, market_alignment_reason = market_divergence_allowed(match_input)
        if market_analysis:
            market_analysis["temporalAlignment"] = {
                "divergenceEnabled": market_aligned,
                "reason": market_alignment_reason,
            }
        calibrated_probability = build_market_aligned_calibrated_probability(probabilities, market_analysis)
        risk_flags = []
        risk_flags.extend(
            event["message"]
            for event in data_reliability["auditEvents"]
            if event["level"] in {"WARN", "CRITICAL"}
        )
        if market_analysis:
            disagreement = market_analysis["biggestDisagreement"]
            if market_aligned and abs(disagreement["edge"]) >= 0.15:
                risk_flags.append("模型与市场概率分歧超过15%，建议核查伤停、首发和赔率变化。")
            rlm = market_analysis.get("reverseLineMovement")
            if rlm and rlm.get("detected"):
                risk_flags.append("检测到疑似逆向盘口移动：公众方向与盘口概率变化相反。")
        risk_flags.extend(lineup_check["riskFlags"])
        upset_risk = build_upset_risk(match_input, probabilities, market_analysis=market_analysis)
        if upset_risk["upsetRiskLevel"] in {"MEDIUM", "HIGH"}:
            risk_flags.append(f"爆冷风险层：{upset_risk['explanation']}")
        confidence_score, confidence = confidence_from_factors(factors, risk_flags)
        confidence_score = max(0, confidence_score - lineup_check["confidencePenalty"])
        confidence_score = max(0, confidence_score - upset_risk["confidencePenalty"])
        if data_reliability["status"] == "CRITICAL":
            confidence_score = min(confidence_score, 45)
        elif data_reliability["status"] == "WARN":
            confidence_score = min(confidence_score, 72)
        if confidence_score >= 75:
            confidence = "HIGH"
        elif confidence_score >= 50:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"
        if calibrated_probability["status"] == "ACTIVE":
            canonical_probability = build_canonical_probability(
                calibrated_probability["probabilities"],
                data_reliability,
                source=calibrated_probability["source"],
                reason=calibrated_probability["reason"],
                calibration=calibrated_probability.get("calibration"),
                components=calibrated_probability.get("components"),
            )
        else:
            canonical_probability = build_canonical_probability(
                probabilities,
                data_reliability,
                reason=f"{calibrated_probability['reason']} Risk and narrative layers explain this probability; they do not mutate it.",
            )
        display_probabilities = canonical_probability.get("probabilities") or probabilities
        display_result_key = select_result_key(display_probabilities, stage)
        display_predicted_score = get_representative_score(matrix, display_result_key)
        display_modal_score = get_predicted_score(matrix, display_result_key)
        display_result_scenarios = filter_scenarios_by_result(matrix, display_result_key)
        display_top_scenarios = get_top_score_scenarios(display_result_scenarios or matrix)
        prediction_manifest = build_prediction_manifest(
            match_input,
            MODEL_VERSION,
            weight_scheme,
            data_reliability,
            factors,
        )
        final_risk_narrative = build_final_risk_narrative(
            data_reliability=data_reliability,
            risk_flags=risk_flags,
            market_analysis=market_analysis,
            lineup_check=lineup_check,
            upset_risk=upset_risk,
            canonical_probability=canonical_probability,
        )

        return {
            "matchId": match_input.get("matchId", f"{match.get('homeTeam', 'HOME')}-{match.get('awayTeam', 'AWAY')}"),
            "modelVersion": MODEL_VERSION,
            "modelArchitecture": MODEL_ARCHITECTURE,
            "weightScheme": weight_scheme,
            "predictionSnapshotId": prediction_manifest["predictionSnapshotId"],
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "match": {
                "homeTeam": match.get("homeTeam"),
                "awayTeam": match.get("awayTeam"),
                "stage": stage,
                "datetime": match.get("datetime"),
                "venue": match.get("venue"),
            },
            "competitionRules": competition_rules,
            "predictionLayers": {
                "regularTime": {
                    "label": "90分钟胜平负",
                    "result": result_map[display_result_key],
                    "probabilities": display_probabilities,
                    "rawModelProbabilities": probabilities,
                    "scoreStorageRule": competition_rules["scoreStorageRule"],
                },
                "extraTime": knockout_layers["extraTime"],
                "penalties": knockout_layers["penalties"],
                "advancement": knockout_layers["advancement"],
            },
            "verdict": {
                "result": result_map[display_result_key],
                "confidence": confidence,
                "confidenceScore": confidence_score,
                "executiveSummary": self._make_summary(match, display_probabilities, display_predicted_score, confidence),
            },
            "probabilities": probabilities,
            "calibratedProbability": calibrated_probability,
            "canonicalProbability": canonical_probability,
            "probabilityModel": {
                "primary": "poisson_score_matrix",
                "factorEdge": round(factor_edge, 4),
                "factorOnlyProbabilities": factor_probabilities,
                "lambdaScale": lambda_scale,
                "drawAdjustment": {
                    "type": "dixon_coles_low_score",
                    "rho": draw_adjustment_rho,
                },
            },
            "scorePrediction": {
                "predicted": display_predicted_score,
                "modal": display_modal_score,
                "homeLambda": home_lambda,
                "awayLambda": away_lambda,
                "preLineupHomeLambda": pre_lineup_home_lambda,
                "preLineupAwayLambda": pre_lineup_away_lambda,
                "rawHomeLambda": raw_home_lambda,
                "rawAwayLambda": raw_away_lambda,
                "topScenarios": display_top_scenarios,
                "rawResultTopScenarios": top_scenarios,
                "rawTopScenarios": raw_top_scenarios,
                "note": "胜平负概率按常规90分钟1X2口径输出；淘汰赛如预测平局，表示90分钟后可能进入加时/点球。predicted为该赛果条件下的代表比分，modal为该赛果条件下概率最高的单一比分。",
            },
            "factors": factors,
            "riskFlags": risk_flags,
            "upsetRisk": upset_risk,
            "finalRiskNarrative": final_risk_narrative,
            "marketAnalysis": market_analysis,
            "finalLineupCheck": lineup_check,
            "f04PExpectedLineup": f04p_expected_lineup,
            "dataReliability": data_reliability,
            "predictionManifest": prediction_manifest,
            "dataSources": {
                "footballDataApi": False,
                "understatCoverage": match_input.get("understatCoverage", {"home": 0, "away": 0}),
                "oddsApiUsed": False,
                "paidApisRequired": False,
                "manualOddsUsed": bool(decimal_odds),
                "manualAdvancedInputsSupported": [
                    "playerData",
                    "goalkeeperData",
                    "matchContext",
                    "tacticalData",
                    "depthData",
                ],
                "searchQueriesExecuted": [],
                "staticFilesUsed": ["teamStrengthOverrides.json"],
            },
        }

    def _make_aborted_prediction(self, match_input, data_reliability, weight_scheme, competition_rules):
        match = match_input.get("match", {})
        manifest = build_prediction_manifest(match_input, MODEL_VERSION, weight_scheme, data_reliability, [])
        risk_flags = [event["message"] for event in data_reliability["auditEvents"]]
        canonical_probability = build_canonical_probability(None, data_reliability)
        return {
            "matchId": match_input.get("matchId", f"{match.get('homeTeam', 'HOME')}-{match.get('awayTeam', 'AWAY')}"),
            "modelVersion": MODEL_VERSION,
            "modelArchitecture": MODEL_ARCHITECTURE,
            "weightScheme": weight_scheme,
            "predictionSnapshotId": manifest["predictionSnapshotId"],
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "match": {
                "homeTeam": match.get("homeTeam"),
                "awayTeam": match.get("awayTeam"),
                "stage": match.get("stage", "GROUP_STAGE"),
                "datetime": match.get("datetime"),
                "venue": match.get("venue"),
            },
            "competitionRules": competition_rules,
            "verdict": {
                "result": "ABORTED",
                "confidence": "NONE",
                "confidenceScore": 0,
                "executiveSummary": "关键赛前数据缺失，系统已熔断，本场不输出概率。",
            },
            "canonicalProbability": canonical_probability,
            "dataReliability": data_reliability,
            "predictionManifest": manifest,
            "riskFlags": risk_flags,
            "finalRiskNarrative": build_final_risk_narrative(
                data_reliability=data_reliability,
                risk_flags=risk_flags,
                canonical_probability=canonical_probability,
            ),
        }

    def _make_summary(self, match, probabilities, predicted_score, confidence):
        home = match.get("homeTeam", "主队")
        away = match.get("awayTeam", "客队")
        home_pct = round(probabilities["home"] * 100, 1)
        draw_pct = round(probabilities["draw"] * 100, 1)
        away_pct = round(probabilities["away"] * 100, 1)
        return (
            f"{home} vs {away} 的{MODEL_VERSION}基线预测为 {predicted_score['home']}-{predicted_score['away']}。"
            f"当前胜平负概率为主胜{home_pct}%、平局{draw_pct}%、客胜{away_pct}%，"
            f"置信度为{confidence}。"
        )
