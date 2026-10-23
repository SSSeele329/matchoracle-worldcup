import math

from .poisson import generate_score_matrix, score_result_key


def clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


def safe_float(value, fallback=0):
    try:
        if value is None or value == "":
            return fallback
        return float(value)
    except (TypeError, ValueError):
        return fallback


def logistic(value):
    return 1 / (1 + math.exp(-value))


def result_probabilities_from_matrix(matrix):
    totals = {"home": 0.0, "draw": 0.0, "away": 0.0}
    for item in matrix:
        totals[score_result_key(item)] += item["probability"]
    total = sum(totals.values()) or 1
    return {key: round(value / total, 4) for key, value in totals.items()}


def side_score(match_input, section, side, key):
    return safe_float((match_input.get(section, {}).get(side, {}) or {}).get(key), 0)


def build_knockout_layers(probabilities, home_lambda, away_lambda, match_input):
    extra_time_entry = float(probabilities.get("draw", 0))

    home_bench = side_score(match_input, "depthData", "home", "benchStrength")
    away_bench = side_score(match_input, "depthData", "away", "benchStrength")
    home_penalty = side_score(match_input, "depthData", "home", "penaltyReadiness")
    away_penalty = side_score(match_input, "depthData", "away", "penaltyReadiness")
    home_keeper = side_score(match_input, "goalkeeperData", "home", "score")
    away_keeper = side_score(match_input, "goalkeeperData", "away", "score")

    bench_edge = (home_bench - away_bench) / 100
    keeper_edge = (home_keeper - away_keeper) / 100
    penalty_edge = (home_penalty - away_penalty) / 100

    home_et_lambda = clamp((home_lambda / 3) * (1 + bench_edge * 0.12), 0.08, 1.25)
    away_et_lambda = clamp((away_lambda / 3) * (1 - bench_edge * 0.12), 0.08, 1.25)
    extra_time_matrix = generate_score_matrix(home_et_lambda, away_et_lambda, max_goals=3)
    extra_time_probs = result_probabilities_from_matrix(extra_time_matrix)

    penalty_home_split = logistic((penalty_edge * 1.4) + (keeper_edge * 1.1))
    penalty_probs = {
        "home": round(penalty_home_split, 4),
        "away": round(1 - penalty_home_split, 4),
    }

    penalty_entry = extra_time_entry * extra_time_probs["draw"]
    home_advances = (
        probabilities["home"]
        + extra_time_entry * extra_time_probs["home"]
        + penalty_entry * penalty_probs["home"]
    )
    away_advances = (
        probabilities["away"]
        + extra_time_entry * extra_time_probs["away"]
        + penalty_entry * penalty_probs["away"]
    )
    total_advances = home_advances + away_advances or 1

    return {
        "extraTime": {
            "label": "加时赛层",
            "entryProbability": round(extra_time_entry, 4),
            "homeLambda30": round(home_et_lambda, 3),
            "awayLambda30": round(away_et_lambda, 3),
            "probabilities": extra_time_probs,
            "note": "加时赛按独立30分钟模型估计，λ由90分钟λ按30/90缩放，并用替补席强度做轻微修正。",
        },
        "penalties": {
            "label": "点球大战层",
            "entryProbability": round(penalty_entry, 4),
            "probabilities": penalty_probs,
            "note": "点球层不使用泊松模型，当前用门将评分和点球准备度做简化估计。",
        },
        "advancement": {
            "label": "晋级/冠军归属",
            "homeAdvances": round(home_advances / total_advances, 4),
            "awayAdvances": round(away_advances / total_advances, 4),
            "method": "90分钟胜率 + 90分钟平局后加时赛路径 + 点球路径。加时/点球不污染90分钟比分模型。",
        },
    }
