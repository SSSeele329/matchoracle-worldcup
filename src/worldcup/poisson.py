import math


def poisson_probability(k, lambda_value):
    if k < 0:
        return 0.0
    log_prob = -lambda_value + k * math.log(lambda_value)
    for i in range(1, k + 1):
        log_prob -= math.log(i)
    return math.exp(log_prob)


def generate_score_matrix(home_lambda, away_lambda, max_goals=5):
    scenarios = []
    for home_goals in range(max_goals + 1):
        for away_goals in range(max_goals + 1):
            probability = poisson_probability(home_goals, home_lambda) * poisson_probability(away_goals, away_lambda)
            scenarios.append({
                "score": f"{home_goals}-{away_goals}",
                "homeGoals": home_goals,
                "awayGoals": away_goals,
                "probability": probability,
            })
    scenarios.sort(key=lambda item: item["probability"], reverse=True)
    return scenarios


def dixon_coles_multiplier(home_goals, away_goals, home_lambda, away_lambda, rho):
    if home_goals == 0 and away_goals == 0:
        return 1 - home_lambda * away_lambda * rho
    if home_goals == 0 and away_goals == 1:
        return 1 + home_lambda * rho
    if home_goals == 1 and away_goals == 0:
        return 1 + away_lambda * rho
    if home_goals == 1 and away_goals == 1:
        return 1 - rho
    return 1


def apply_dixon_coles_adjustment(scenarios, home_lambda, away_lambda, rho=-0.08):
    """Rebalance low-score dependence so draws are not only a Poisson byproduct."""
    adjusted = []
    for scenario in scenarios:
        item = dict(scenario)
        multiplier = dixon_coles_multiplier(
            item["homeGoals"],
            item["awayGoals"],
            home_lambda,
            away_lambda,
            rho,
        )
        item["probability"] = max(0, item["probability"] * multiplier)
        adjusted.append(item)
    adjusted.sort(key=lambda item: item["probability"], reverse=True)
    return adjusted


def adjust_for_knockout(scenarios):
    adjusted = []
    for scenario in scenarios:
        item = dict(scenario)
        item["requiresExtraTime"] = item["homeGoals"] == item["awayGoals"]
        item["label"] = "(将进入加时赛)" if item["requiresExtraTime"] else ""
        adjusted.append(item)
    return adjusted


def get_top_score_scenarios(matrix, limit=5):
    top_items = []
    for item in matrix[:limit]:
        top = {"score": item["score"], "probability": round(item["probability"], 4)}
        if "requiresExtraTime" in item:
            top["requiresExtraTime"] = item["requiresExtraTime"]
            top["label"] = item["label"]
        top_items.append(top)
    return top_items


def filter_scenarios_by_result(matrix, result_key):
    return [item for item in matrix if score_result_key(item) == result_key]


def score_result_key(scenario):
    if scenario["homeGoals"] > scenario["awayGoals"]:
        return "home"
    if scenario["homeGoals"] < scenario["awayGoals"]:
        return "away"
    return "draw"


def outcome_probabilities_from_matrix(matrix):
    total_probability = sum(item["probability"] for item in matrix)
    if not total_probability:
        return {"home": 0.0, "draw": 0.0, "away": 0.0}

    probabilities = {"home": 0.0, "draw": 0.0, "away": 0.0}
    for item in matrix:
        probabilities[score_result_key(item)] += item["probability"] / total_probability
    return {key: round(value, 4) for key, value in probabilities.items()}


def get_predicted_score(matrix, result_key=None):
    if result_key:
        candidates = [item for item in matrix if score_result_key(item) == result_key]
        if candidates:
            top = candidates[0]
            return {"home": top["homeGoals"], "away": top["awayGoals"]}
    top = matrix[0]
    return {"home": top["homeGoals"], "away": top["awayGoals"]}


def get_representative_score(matrix, result_key=None):
    candidates = matrix
    if result_key:
        result_candidates = [item for item in matrix if score_result_key(item) == result_key]
        if result_candidates:
            candidates = result_candidates

    total_matrix_probability = sum(item["probability"] for item in matrix)
    total_candidate_probability = sum(item["probability"] for item in candidates)
    if not total_matrix_probability or not total_candidate_probability:
        return get_predicted_score(matrix, result_key)

    home_lambda = sum(item["homeGoals"] * item["probability"] for item in matrix) / total_matrix_probability
    away_lambda = sum(item["awayGoals"] * item["probability"] for item in matrix) / total_matrix_probability
    max_probability = max(item["probability"] for item in candidates)

    if result_key == "draw":
        total_goals = home_lambda + away_lambda
        if total_goals < 1.85:
            target_home, target_away = 0, 0
        elif total_goals > 3.35:
            target_home, target_away = 2, 2
        else:
            target_home, target_away = 1, 1
    elif result_key == "away":
        favorite_goals = 3 if away_lambda >= 1.75 else 2 if away_lambda >= 1.15 else 1
        underdog_goals = 0 if away_lambda - home_lambda >= 0.35 or home_lambda <= 1.05 else 1
        if favorite_goals <= underdog_goals:
            favorite_goals = underdog_goals + 1
        target_home, target_away = underdog_goals, favorite_goals
    else:
        favorite_goals = 3 if home_lambda >= 1.75 else 2 if home_lambda >= 1.15 else 1
        underdog_goals = 0 if home_lambda - away_lambda >= 0.35 or away_lambda <= 1.05 else 1
        if favorite_goals <= underdog_goals:
            favorite_goals = underdog_goals + 1
        target_home, target_away = favorite_goals, underdog_goals

    def representative_distance(item):
        distance = (item["homeGoals"] - target_home) ** 2 + (item["awayGoals"] - target_away) ** 2
        probability_penalty = (1 - item["probability"] / max_probability) * 0.45
        return distance + probability_penalty

    best = min(candidates, key=representative_distance)
    return {"home": best["homeGoals"], "away": best["awayGoals"]}
