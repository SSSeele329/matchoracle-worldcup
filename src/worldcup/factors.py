import json
import math
import os
from copy import deepcopy

from .lineup_check import formation_geometry_edge
from .rules import is_knockout_stage
from .weights import FACTOR_NAMES, FACTOR_ROLES, get_base_weights

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DATA_DIR = os.path.join(PROJECT_ROOT, "data", "worldcup")


def clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


def optional_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def min_quality(*qualities):
    order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    return min(qualities, key=lambda quality: order.get(quality, 0))


def load_json_file(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def load_team_strength_overrides():
    payload = load_json_file(os.path.join(DATA_DIR, "teamStrengthOverrides.json"), {"overrides": []})
    return payload.get("overrides", [])


def rank_to_score(rank):
    rank = int(rank)
    if rank <= 1:
        return 100.0
    if rank >= 200:
        return 20.0
    return round(100 - (rank - 1) * 0.4, 2)


def get_team_strength_score(team_name, fifa_rank, overrides=None):
    overrides = overrides if overrides is not None else load_team_strength_overrides()
    for override in overrides:
        if override.get("team", "").lower() == str(team_name).lower():
            return float(override["adjustedScore"]), override
    return rank_to_score(fifa_rank), None


def evaluate_f07_data_quality(understat_matches_found, base_weight):
    coverage = int(understat_matches_found or 0)
    if coverage >= 6:
        return {
            "understatCoverage": coverage,
            "dataQuality": "HIGH",
            "effectiveWeight": base_weight,
            "weightTransfer": {"F01": 0, "F12": 0},
        }
    if coverage >= 3:
        transferred = base_weight * 0.5
        return {
            "understatCoverage": coverage,
            "dataQuality": "MEDIUM",
            "effectiveWeight": base_weight * 0.5,
            "weightTransfer": {"F01": transferred * 0.5, "F12": transferred * 0.5},
        }
    return {
        "understatCoverage": coverage,
        "dataQuality": "LOW",
        "effectiveWeight": 0,
        "weightTransfer": {"F01": base_weight * 0.5, "F12": base_weight * 0.5},
    }


def make_factor(factor_id, weight, original_weight, impact_score=0, reasoning="", data_quality="HIGH", degraded=False, evidence=None, uncertainty=None):
    impact_score = round(clamp(float(impact_score), -5, 5), 2)
    if impact_score > 0.35:
        impact = "POSITIVE_HOME"
    elif impact_score < -0.35:
        impact = "POSITIVE_AWAY"
    else:
        impact = "NEUTRAL"
    factor = {
        "id": factor_id,
        "name": FACTOR_NAMES[factor_id],
        "role": FACTOR_ROLES.get(factor_id, "CONTEXT"),
        "weight": round(weight, 2),
        "originalWeight": original_weight,
        "impact": impact,
        "impactScore": impact_score,
        "reasoning": reasoning,
        "dataQuality": data_quality,
        "degraded": degraded,
    }
    if evidence is not None:
        factor["evidence"] = evidence
    if uncertainty:
        factor["uncertainty"] = uncertainty
    return factor


def build_initial_weights(stage, understat_home_coverage, understat_away_coverage):
    weights = get_base_weights(stage)
    original = deepcopy(weights)
    home_status = evaluate_f07_data_quality(understat_home_coverage, original["F07"])
    away_status = evaluate_f07_data_quality(understat_away_coverage, original["F07"])
    quality_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    lower_status = home_status if quality_order[home_status["dataQuality"]] <= quality_order[away_status["dataQuality"]] else away_status
    effective_f07 = lower_status["effectiveWeight"]
    transferred = original["F07"] - effective_f07
    weights["F07"] = effective_f07
    weights["F01"] += transferred * 0.5
    weights["F12"] += transferred * 0.5
    return weights, original, home_status, away_status, lower_status


def calculate_f01(home_team, away_team, home_rank, away_rank, use_overrides=True):
    overrides = load_team_strength_overrides() if use_overrides else []
    home_score, home_override = get_team_strength_score(home_team, home_rank, overrides)
    away_score, away_override = get_team_strength_score(away_team, away_rank, overrides)
    diff = home_score - away_score
    impact_score = clamp(diff / 8.0, -5, 5)
    notes = [
        f"{home_team}实力分 {home_score:.1f}",
        f"{away_team}实力分 {away_score:.1f}",
        f"差值 {diff:+.1f}",
    ]
    if home_override:
        notes.append(f"{home_team}使用补丁：{home_override.get('reason')}")
    if away_override:
        notes.append(f"{away_team}使用补丁：{away_override.get('reason')}")
    if not use_overrides:
        notes.append("历史回放禁用2026静态补丁，避免未来信息污染")
    return impact_score, "；".join(notes) + "。"


def calculate_f02(home_recent_points=None, away_recent_points=None):
    if home_recent_points is None or away_recent_points is None:
        return 0, "缺少近10场状态分，F02暂按中性处理。", "LOW", True
    diff = float(home_recent_points) - float(away_recent_points)
    return clamp(diff * 5, -5, 5), f"近况加权分差为 {diff:+.2f}。", "HIGH", False


def calculate_f04(player_data=None, f04p_expected_lineup=None):
    player_data = player_data or {}
    has_legacy_subjective_fields = any(
        (player_data.get(side) or {}).get(field) not in (None, "")
        for side in ("home", "away")
        for field in ("lineupStrength", "keyAbsenceImpact")
    )
    if has_legacy_subjective_fields:
        return (
            0,
            "V4-P0 不再使用0-100阵容强度或主观缺阵分作为核心概率输入；F04数值影响只通过T-60 Tier-based Lineup Shock重算lambda。",
            "LOW",
            True,
            None,
        )
    if f04p_expected_lineup and f04p_expected_lineup.get("status") == "AVAILABLE":
        summary = f04p_expected_lineup.get("summary") or {}
        return (
            0,
            "已提供F04-P结构化证据，预计首发概率由代码公式计算；当前不直接改胜平负概率，只作为T-60官方首发delta基线。",
            "MEDIUM",
            False,
            [{
                "source": "expectedLineupEvidence",
                "keyFact": f"已评估{summary.get('playersWithProbability', 0)}名球员的预计首发概率。",
                "confidence": "MEDIUM",
                "validationMode": f04p_expected_lineup.get("validationMode"),
                "historicalBacktestEligible": f04p_expected_lineup.get("historicalBacktestEligible"),
            }],
        )
    return (
        0,
        "未提供可验证的F04-P/F04-O结构化证据，F04按中性处理；T-60官方首发变化将通过Tier-based Lineup Shock单独重算lambda。",
        "LOW",
        True,
        None,
    )


def calculate_f05(match_context=None):
    match_context = match_context or {}
    scale = optional_float(match_context.get("scale"))
    scale = 1.0 if scale is None else scale
    home_motivation = optional_float(match_context.get("homeMotivationScore"))
    away_motivation = optional_float(match_context.get("awayMotivationScore"))
    home_rotation = optional_float(match_context.get("homeRotationRisk"))
    away_rotation = optional_float(match_context.get("awayRotationRisk"))
    if home_motivation is None and away_motivation is None and home_rotation is None and away_rotation is None:
        return 0, "未提供小组积分、晋级形势或轮换概率，F05当前中性；第三轮和淘汰赛前建议手动填写。", "MEDIUM", True

    home_motivation = home_motivation if home_motivation is not None else 0
    away_motivation = away_motivation if away_motivation is not None else 0
    home_rotation = home_rotation if home_rotation is not None else 0
    away_rotation = away_rotation if away_rotation is not None else 0
    motivation_edge = home_motivation - away_motivation
    rotation_edge = away_rotation - home_rotation
    score = (motivation_edge + rotation_edge * 3) * scale
    return (
        clamp(score, -5, 5),
        f"赛制动机差 {motivation_edge:+.1f}；轮换风险差 {rotation_edge:+.2f}；赛程上下文权重{scale:.2f}。",
        "HIGH",
        False,
    )


def calculate_f06(rest_data=None):
    rest_data = rest_data or {}
    scale = optional_float(rest_data.get("scale"))
    scale = 1.0 if scale is None else scale
    home_rest = optional_float(rest_data.get("homeRestDays"))
    away_rest = optional_float(rest_data.get("awayRestDays"))
    if home_rest is None and away_rest is None:
        return 0, "双方均为本届首战或缺少赛程上下文，F06按中性处理。", "MEDIUM", True
    if home_rest is None or away_rest is None:
        return 0, "仅一方有本届上一场记录，休息天数差暂按中性处理。", "MEDIUM", True

    rest_edge = home_rest - away_rest
    score = clamp((rest_edge / 2.0) * scale, -2.0, 2.0)
    return (
        score,
        f"主队休息{home_rest:.0f}天，客队休息{away_rest:.0f}天，休息差{rest_edge:+.0f}天；赛程上下文权重{scale:.2f}。",
        "HIGH",
        False,
    )


def calculate_f12(odds_probabilities=None):
    if not odds_probabilities:
        return 0, "未提供本场赔率，F12按中性处理。", "LOW", True
    home = float(odds_probabilities.get("home", 0))
    away = float(odds_probabilities.get("away", 0))
    diff = home - away
    return clamp(diff * 10, -5, 5), f"市场去水后主胜与客胜概率差为 {diff:+.2%}。", "HIGH", False


def calculate_f07(goal_data=None):
    goal_data = goal_data or {}
    home_goal = goal_data.get("home") or {}
    away_goal = goal_data.get("away") or {}
    home_attack = optional_float(home_goal.get("xG_avg") or home_goal.get("actualGoals_avg"))
    away_attack = optional_float(away_goal.get("xG_avg") or away_goal.get("actualGoals_avg"))
    if home_attack is None or away_attack is None:
        return 0, "未提供赛前进攻均值或xG，F07按中性处理。", "LOW", True

    diff = home_attack - away_attack
    home_matches = optional_float(home_goal.get("historicalMatchesUsed"))
    away_matches = optional_float(away_goal.get("historicalMatchesUsed"))
    quality = "HIGH"
    if home_goal.get("historyDataQuality") == "MEDIUM" or away_goal.get("historyDataQuality") == "MEDIUM":
        quality = "MEDIUM"
    if home_goal.get("historyDataQuality") == "LOW" or away_goal.get("historyDataQuality") == "LOW":
        quality = "LOW"
    if home_matches is not None and away_matches is not None and min(home_matches, away_matches) < 8:
        quality = "LOW"

    notes = [f"赛前进攻均值差 {diff:+.2f}"]
    if home_matches is not None and away_matches is not None:
        notes.append(f"历史样本主队{int(home_matches)}场、客队{int(away_matches)}场")
    return clamp(diff * 3.0, -5, 5), "；".join(notes) + "。", quality, quality == "LOW"


def calculate_f13(formation_data=None):
    formation_data = formation_data or {}
    result = formation_geometry_edge(formation_data.get("home"), formation_data.get("away"))
    tactical_data = formation_data.get("tacticalData") or {}
    home_continuity = optional_float(tactical_data.get("homeContinuityScore"))
    away_continuity = optional_float(tactical_data.get("awayContinuityScore"))
    continuity_score = 0
    continuity_note = ""
    if home_continuity is not None and away_continuity is not None:
        continuity_diff = home_continuity - away_continuity
        continuity_score = clamp(continuity_diff / 18.0, -2, 2)
        continuity_note = f" 阵容连续性差 {continuity_diff:+.1f}。"
    impact_score = clamp(result["impactScore"] + continuity_score, -5, 5)
    data_quality = "MEDIUM" if result["dataQuality"] != "LOW" or continuity_note else "LOW"
    return (
        impact_score,
        result["reasoning"] + continuity_note,
        data_quality,
        data_quality == "LOW",
    )


def calculate_f08(goal_data=None, goalkeeper_data=None):
    goal_data = goal_data or {}
    goalkeeper_data = goalkeeper_data or {}
    home_goal = goal_data.get("home") or {}
    away_goal = goal_data.get("away") or {}
    home_keeper = goalkeeper_data.get("home") or {}
    away_keeper = goalkeeper_data.get("away") or {}
    home_xga = optional_float(home_goal.get("xGA_avg"))
    away_xga = optional_float(away_goal.get("xGA_avg"))
    home_keeper_score = optional_float(home_keeper.get("score"))
    away_keeper_score = optional_float(away_keeper.get("score"))
    if home_xga is None and away_xga is None and home_keeper_score is None and away_keeper_score is None:
        return 0, "未提供防守xGA或门将评分，F08按中性处理。", "MEDIUM", True

    score = 0
    notes = []
    if home_xga is not None and away_xga is not None:
        defensive_edge = away_xga - home_xga
        score += defensive_edge * 2.4
        notes.append(f"防守失球质量差 {defensive_edge:+.2f}")
    if home_keeper_score is not None and away_keeper_score is not None:
        keeper_edge = home_keeper_score - away_keeper_score
        score += keeper_edge / 18.0
        notes.append(f"门将质量差 {keeper_edge:+.1f}")
    quality = "HIGH" if notes else "LOW"
    return clamp(score, -5, 5), "；".join(notes) + "。", quality, quality != "HIGH"


def calculate_f16(goal_data=None):
    goal_data = goal_data or {}
    home_rate = optional_float((goal_data.get("home") or {}).get("setpieceRate"))
    away_rate = optional_float((goal_data.get("away") or {}).get("setpieceRate"))
    if home_rate is None or away_rate is None:
        return 0, "未提供定位球占比，F16仅作为事件风险项中性处理。", "MEDIUM", True
    diff = home_rate - away_rate
    return clamp(diff * 8, -3, 3), f"定位球得分依赖度差 {diff:+.2f}；该项主要解释比赛事件风险。", "MEDIUM", False


def calculate_f17(depth_data=None, stage="GROUP_STAGE"):
    depth_data = depth_data or {}
    home = depth_data.get("home") or {}
    away = depth_data.get("away") or {}
    home_bench = optional_float(home.get("benchStrength"))
    away_bench = optional_float(away.get("benchStrength"))
    home_penalty = optional_float(home.get("penaltyReadiness"))
    away_penalty = optional_float(away.get("penaltyReadiness"))
    if home_bench is None and away_bench is None and home_penalty is None and away_penalty is None:
        return 0, "未提供替补席或点球大战准备度，F17按中性处理；淘汰赛再提高关注。", "LOW", True

    score = 0
    notes = []
    if home_bench is not None and away_bench is not None:
        bench_diff = home_bench - away_bench
        score += bench_diff / 18.0
        notes.append(f"替补席质量差 {bench_diff:+.1f}")
    knockout_stage = str(stage or "").upper() != "GROUP_STAGE"
    if knockout_stage and home_penalty is not None and away_penalty is not None:
        penalty_diff = home_penalty - away_penalty
        score += penalty_diff / 25.0
        notes.append(f"点球路径准备度差 {penalty_diff:+.1f}")
    elif home_penalty is not None or away_penalty is not None:
        notes.append("点球准备度仅在淘汰赛计入")
    return clamp(score, -5, 5), "；".join(notes) + "。", "MEDIUM", False


def build_baseline_factors(match_input):
    match = match_input.get("match", {})
    team_data = match_input.get("teamData") or {}
    home_data = team_data.get("home") or {}
    away_data = team_data.get("away") or {}
    home_team = match.get("homeTeam", "Home")
    away_team = match.get("awayTeam", "Away")
    understat = match_input.get("understatCoverage") or {}
    weights, original, f07_home, f07_away, f07_effective = build_initial_weights(
        match.get("stage", "GROUP_STAGE"),
        understat.get("home", 0),
        understat.get("away", 0),
    )

    f01_score, f01_reasoning = calculate_f01(
        home_team,
        away_team,
        home_data.get("fifaRank", 100),
        away_data.get("fifaRank", 100),
        use_overrides=match_input.get("teamStrengthOverridesEnabled", True),
    )
    f02_score, f02_reasoning, f02_quality, f02_degraded = calculate_f02(home_data.get("recentFormScore"), away_data.get("recentFormScore"))
    f04_score, f04_reasoning, f04_quality, f04_degraded, f04_evidence = calculate_f04(
        match_input.get("playerData"),
        match_input.get("f04PExpectedLineup"),
    )
    f05_score, f05_reasoning, f05_quality, f05_degraded = calculate_f05(match_input.get("matchContext"))
    f06_score, f06_reasoning, f06_quality, f06_degraded = calculate_f06(match_input.get("restData"))
    f07_score, f07_reasoning, f07_quality, f07_degraded = calculate_f07(match_input.get("goalData"))
    f08_score, f08_reasoning, f08_quality, f08_degraded = calculate_f08(match_input.get("goalData"), match_input.get("goalkeeperData"))
    f12_score, f12_reasoning, f12_quality, f12_degraded = calculate_f12(match_input.get("oddsProbabilities"))
    formation_data = dict(match_input.get("formationData") or {})
    formation_data["tacticalData"] = match_input.get("tacticalData", {})
    f13_score, f13_reasoning, f13_quality, f13_degraded = calculate_f13(formation_data)
    f16_score, f16_reasoning, f16_quality, f16_degraded = calculate_f16(match_input.get("goalData"))
    f17_score, f17_reasoning, f17_quality, f17_degraded = calculate_f17(match_input.get("depthData"), match.get("stage", "GROUP_STAGE"))

    local_placeholder = {"source": "本地基线解释层", "keyFact": "当前缺少结构化输入，按中性代理处理。", "confidence": "LOW"}
    return [
        make_factor("F01", weights["F01"], original["F01"], f01_score, f01_reasoning),
        make_factor("F02", weights["F02"], original["F02"], f02_score, f02_reasoning, f02_quality, f02_degraded),
        make_factor("F03", weights["F03"], original["F03"], 0, "H2H已降级为解释项；国家队交手样本通常太小，默认不明显影响概率。", "LOW", True),
        make_factor("F04", weights["F04"], original["F04"], f04_score, f04_reasoning, f04_quality, f04_degraded, evidence=f04_evidence if f04_evidence is not None else [local_placeholder] if f04_degraded else None, uncertainty="F04-P只作为预计首发证据基线，不能包装成历史严格回测增益；T-60 只接受 Tier + 位置的官方首发差异重算。"),
        make_factor("F05", weights["F05"], original["F05"], f05_score, f05_reasoning, f05_quality, f05_degraded),
        make_factor("F06", weights["F06"], original["F06"], f06_score, f06_reasoning, f06_quality, f06_degraded),
        make_factor("F07", weights["F07"], original["F07"], f07_score, f07_reasoning, min_quality(f07_quality, f07_effective["dataQuality"]), f07_degraded or weights["F07"] != original["F07"]),
        make_factor("F08", weights["F08"], original["F08"], f08_score, f08_reasoning, f08_quality, f08_degraded),
        make_factor("F10", weights["F10"], original["F10"], 0, "教练因素已降为解释项；除非有明确换帅、体系崩坏或临场短板证据，否则不高权重计分。", "LOW", True),
        make_factor("F11", weights["F11"], original["F11"], 0, "F15旅途消耗已并入本因子；venues.json和赛程路线暂未填写，当前中性。", "LOW", True),
        make_factor("F12", weights["F12"], original["F12"], f12_score, f12_reasoning, f12_quality, f12_degraded),
        make_factor("F13", weights["F13"], original["F13"], f13_score, f13_reasoning, f13_quality, f13_degraded, evidence=[local_placeholder] if f13_degraded else None, uncertainty="未读取双方完整战术标签，当前仅使用阵型几何输入。" if not f13_degraded else "未提供阵型。"),
        make_factor("F14", weights["F14"], original["F14"], 0, "裁判风格已降为牌/点球/比赛混乱度风险项，不作为胜平负核心权重。", "LOW", True, evidence=[local_placeholder], uncertainty="未提供本场主裁。"),
        make_factor("F16", weights["F16"], original["F16"], f16_score, f16_reasoning, f16_quality, f16_degraded),
        make_factor("F17", weights["F17"], original["F17"], f17_score, f17_reasoning, f17_quality, f17_degraded, evidence=[local_placeholder] if f17_degraded else None, uncertainty="可先手动录入替补席和点球准备度，未来再自动化。"),
    ]


LAMBDA_ONLY_FACTOR_IDS = {"F07", "F08"}


def weighted_edge(factors):
    return sum(
        (factor["weight"] / 100.0) * factor["impactScore"]
        for factor in factors
        if factor["id"] not in LAMBDA_ONLY_FACTOR_IDS
    )


def probabilities_from_factors(factors, stage):
    edge = weighted_edge(factors)
    home_share = 1 / (1 + math.exp(-edge * 0.9))
    knockout_stage = is_knockout_stage(stage)
    base_draw = 0.28 if knockout_stage else 0.26
    draw = clamp(base_draw - abs(edge) * 0.035, 0.14, 0.34)
    home = (1 - draw) * home_share
    away = (1 - draw) * (1 - home_share)
    total = home + draw + away
    return {"home": round(home / total, 4), "draw": round(draw / total, 4), "away": round(away / total, 4)}


def select_result_key(probabilities, stage):
    """Pick the headline outcome without suppressing plausible draws."""
    home = probabilities["home"]
    draw = probabilities["draw"]
    away = probabilities["away"]
    knockout_stage = is_knockout_stage(stage)
    balance_band = 0.03 if knockout_stage else 0.04
    draw_floor = 0.26 if knockout_stage else 0.245

    if abs(home - away) <= balance_band and draw >= draw_floor:
        return "draw"
    if draw >= max(home, away):
        return "draw"
    return "home" if home > away else "away"


def confidence_from_factors(factors, risk_flags):
    score = 100
    for factor in factors:
        if factor["dataQuality"] != "LOW":
            continue
        if factor.get("role") in {"CORE", "LAMBDA_ONLY"}:
            score -= 8
        elif factor.get("role") == "CONTEXT":
            score -= 4
        else:
            score -= 2
    score -= len(risk_flags) * 10
    if any("赔率异常" in flag for flag in risk_flags):
        score -= 12
    score = int(clamp(score, 0, 100))
    if score >= 75:
        return score, "HIGH"
    if score >= 50:
        return score, "MEDIUM"
    return score, "LOW"
