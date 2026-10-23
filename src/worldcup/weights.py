from .rules import GROUP_STAGE, QUARTER_FINAL, ROUND_OF_16, ROUND_OF_32, SEMI_FINAL, THIRD_PLACE, FINAL, normalize_stage

WEIGHT_TABLE = {
    "GROUP_STAGE": {
        "F01": 18, "F02": 8, "F03": 1, "F04": 16, "F05": 12,
        "F06": 2, "F07": 11, "F08": 10, "F10": 1, "F11": 5,
        "F12": 10, "F13": 3, "F14": 1, "F16": 1, "F17": 1,
    },
    "KNOCKOUT": {
        "F01": 16, "F02": 7, "F03": 1, "F04": 16, "F05": 9,
        "F06": 2, "F07": 11, "F08": 10, "F10": 2, "F11": 4,
        "F12": 10, "F13": 5, "F14": 2, "F16": 2, "F17": 3,
    },
    "SEMI_AND_FINAL": {
        "F01": 15, "F02": 6, "F03": 1, "F04": 16, "F05": 7,
        "F06": 1, "F07": 10, "F08": 10, "F10": 3, "F11": 4,
        "F12": 10, "F13": 6, "F14": 2, "F16": 2, "F17": 7,
    },
}

FACTOR_NAMES = {
    "F01": "球队真实强度",
    "F02": "近期状态与比赛节奏",
    "F03": "历史交锋参考",
    "F04": "球员与预计首发强度",
    "F05": "赛制动机与轮换概率",
    "F06": "休息天数",
    "F07": "进攻质量与 xG",
    "F08": "防守与门将稳定性",
    "F10": "教练临场适配",
    "F11": "环境与后勤损耗",
    "F12": "市场概率与赔率分歧",
    "F13": "战术对位与阵容连续性",
    "F14": "裁判/牌点风险",
    "F16": "定位球事件风险",
    "F17": "阵容深度与淘汰赛路径",
}

FACTOR_ROLES = {
    "F01": "CORE",
    "F02": "CONTEXT",
    "F03": "EXPLAIN_ONLY",
    "F04": "CORE",
    "F05": "CORE",
    "F06": "CONTEXT",
    "F07": "LAMBDA_ONLY",
    "F08": "LAMBDA_ONLY",
    "F10": "EXPLAIN_ONLY",
    "F11": "CONTEXT",
    "F12": "CORE",
    "F13": "CONTEXT",
    "F14": "RISK_MODIFIER",
    "F16": "RISK_MODIFIER",
    "F17": "CONTEXT",
}

MODEL_ARCHITECTURE = {
    "version": "V4-P0",
    "principle": "probability model + market calibration + risk explanation",
    "coreModules": [
        "team_strength_rating",
        "player_and_expected_lineup_strength",
        "attack_defense_goal_model",
        "market_implied_probability",
        "match_context_and_rotation",
        "goalkeeper_defensive_stability",
    ],
    "riskAndExplanationModules": [
        "h2h_context",
        "coach_adaptability",
        "referee_cards_penalties",
        "set_piece_event_risk",
    ],
    "finalCheck": "T-60 actual lineup validation with tier-based lambda shock",
}


def select_weight_scheme(stage):
    normalized = normalize_stage(stage)
    if normalized == GROUP_STAGE:
        return "GROUP_STAGE"
    if normalized in {ROUND_OF_32, ROUND_OF_16, QUARTER_FINAL}:
        return "KNOCKOUT"
    if normalized in {SEMI_FINAL, FINAL, THIRD_PLACE}:
        return "SEMI_AND_FINAL"
    return "GROUP_STAGE"


def validate_weight_table():
    totals = {scheme: sum(weights.values()) for scheme, weights in WEIGHT_TABLE.items()}
    invalid = {scheme: total for scheme, total in totals.items() if total != 100}
    if invalid:
        raise ValueError(f"权重表未归一化: {invalid}")
    return totals


def get_base_weights(stage):
    return dict(WEIGHT_TABLE[select_weight_scheme(stage)])


validate_weight_table()
