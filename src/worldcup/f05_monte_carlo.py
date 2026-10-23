import copy
import random

from .factors import clamp
from .poisson import apply_dixon_coles_adjustment, generate_score_matrix
from .snapshot_store import current_utc_iso


FORMAT_WC2026_48 = "WC2026_48"
LOCK_TYPE_T24_DEPENDENCY = "T24_DEPENDENCY"
GROUP_STAGE = "GROUP_STAGE"
DEFAULT_SIMULATIONS = 2000
MAX_SIMULATIONS = 20000
AUTO_ADVANCERS_PER_GROUP = 2
THIRD_PLACE_ADVANCERS = 8


class F05MonteCarloError(Exception):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def _match_date(match):
    return str(match.get("date") or match.get("datetime") or "9999-12-31")[:10]


def _match_minutes(match):
    raw_time = match.get("time")
    if raw_time is None:
        raw_datetime = str(match.get("datetime") or "")
        raw_time = raw_datetime[11:16] if "T" in raw_datetime else "12:00"
    parts = str(raw_time).split()[0].split(":")
    if len(parts) < 2:
        return 12 * 60
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except ValueError:
        return 12 * 60


def match_sort_key(match):
    return (_match_date(match), _match_minutes(match), match.get("matchId", ""))


def match_chronology_key(match):
    return (_match_date(match), _match_minutes(match))


def match_started_before(candidate, current):
    return match_chronology_key(candidate) < match_chronology_key(current)


def same_match(left, right):
    if left.get("matchId") and right.get("matchId"):
        return left.get("matchId") == right.get("matchId")
    return (
        left.get("group") == right.get("group")
        and left.get("homeTeam") == right.get("homeTeam")
        and left.get("awayTeam") == right.get("awayTeam")
        and _match_date(left) == _match_date(right)
        and _match_minutes(left) == _match_minutes(right)
    )


def empty_record():
    return {"played": 0, "points": 0, "gf": 0, "ga": 0, "gd": 0}


def result_points(goals_for, goals_against):
    if goals_for > goals_against:
        return 3
    if goals_for < goals_against:
        return 0
    return 1


def apply_score(table, home, away, home_goals, away_goals):
    for team in (home, away):
        table.setdefault(team, empty_record())
    table[home]["played"] += 1
    table[away]["played"] += 1
    table[home]["points"] += result_points(home_goals, away_goals)
    table[away]["points"] += result_points(away_goals, home_goals)
    table[home]["gf"] += home_goals
    table[home]["ga"] += away_goals
    table[away]["gf"] += away_goals
    table[away]["ga"] += home_goals
    table[home]["gd"] = table[home]["gf"] - table[home]["ga"]
    table[away]["gd"] = table[away]["gf"] - table[away]["ga"]


def score_result_key(home_goals, away_goals):
    if home_goals > away_goals:
        return "home"
    if home_goals < away_goals:
        return "away"
    return "draw"


def normalize_probability_map(probabilities):
    probabilities = probabilities or {}
    values = {
        "home": probabilities.get("home", probabilities.get("HOME_WIN", 0)),
        "draw": probabilities.get("draw", probabilities.get("DRAW", 0)),
        "away": probabilities.get("away", probabilities.get("AWAY_WIN", 0)),
    }
    cleaned = {}
    for key, value in values.items():
        try:
            cleaned[key] = max(0.0, float(value))
        except (TypeError, ValueError):
            cleaned[key] = 0.0
    total = sum(cleaned.values())
    if total <= 0:
        return {"home": 1 / 3, "draw": 1 / 3, "away": 1 / 3}
    return {key: value / total for key, value in cleaned.items()}


def prediction_probabilities(match):
    prediction = match.get("prediction") or match.get("lockedPrediction") or {}
    canonical = (prediction.get("canonicalProbability") or {}).get("probabilities")
    return normalize_probability_map(
        match.get("probabilities")
        or match.get("outcomeProbabilities")
        or canonical
        or prediction.get("probabilities")
    )


def weighted_choice(weighted_items, rng):
    total = sum(max(0.0, item[1]) for item in weighted_items)
    if total <= 0:
        return weighted_items[0][0]
    threshold = rng.random() * total
    running = 0.0
    for value, weight in weighted_items:
        running += max(0.0, weight)
        if running >= threshold:
            return value
    return weighted_items[-1][0]


def sample_result(match, rng):
    probabilities = prediction_probabilities(match)
    return weighted_choice(
        [("home", probabilities["home"]), ("draw", probabilities["draw"]), ("away", probabilities["away"])],
        rng,
    )


def parse_score(score):
    if not score:
        return None
    parts = str(score).split("-")
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def scenario_goals(scenario):
    if "homeGoals" in scenario and "awayGoals" in scenario:
        return int(scenario["homeGoals"]), int(scenario["awayGoals"])
    if "home" in scenario and "away" in scenario:
        return int(scenario["home"]), int(scenario["away"])
    return parse_score(scenario.get("score"))


def normalize_score_scenarios(scenarios):
    normalized = []
    for scenario in scenarios or []:
        goals = scenario_goals(scenario)
        if goals is None:
            continue
        probability = scenario.get("probability", scenario.get("p", 0))
        try:
            weight = max(0.0, float(probability))
        except (TypeError, ValueError):
            weight = 0.0
        normalized.append({
            "homeGoals": goals[0],
            "awayGoals": goals[1],
            "probability": weight,
        })
    return normalized


def score_scenarios_from_match(match):
    direct = normalize_score_scenarios(match.get("scoreScenarios"))
    if direct:
        return direct

    prediction = match.get("prediction") or match.get("lockedPrediction") or {}
    score_prediction = prediction.get("scorePrediction") or {}
    home_lambda = score_prediction.get("homeLambda")
    away_lambda = score_prediction.get("awayLambda")
    if home_lambda is not None and away_lambda is not None:
        try:
            matrix = generate_score_matrix(float(home_lambda), float(away_lambda), max_goals=7)
        except (TypeError, ValueError):
            matrix = []
        raw_rho = ((prediction.get("probabilityModel") or {}).get("drawAdjustment") or {}).get("rho", 0)
        try:
            rho = float(raw_rho)
        except (TypeError, ValueError):
            rho = 0.0
        if matrix and rho:
            matrix = apply_dixon_coles_adjustment(matrix, float(home_lambda), float(away_lambda), rho)
        if matrix:
            return matrix

    return normalize_score_scenarios(
        score_prediction.get("rawTopScenarios")
        or score_prediction.get("topScenarios")
        or prediction.get("scoreScenarios")
    )


def fallback_score_for_result(result):
    if result == "home":
        return 1, 0
    if result == "away":
        return 0, 1
    return 1, 1


def sample_score(match, rng, fixed_result=None):
    scenarios = score_scenarios_from_match(match)
    if fixed_result:
        scenarios = [
            scenario for scenario in scenarios
            if score_result_key(scenario["homeGoals"], scenario["awayGoals"]) == fixed_result
        ]
    if scenarios:
        selected = weighted_choice(
            [
                ((scenario["homeGoals"], scenario["awayGoals"]), scenario["probability"])
                for scenario in scenarios
            ],
            rng,
        )
        return selected
    return fallback_score_for_result(fixed_result or sample_result(match, rng))


def normalize_lock(lock):
    if not isinstance(lock, dict):
        raise F05MonteCarloError(
            "F05_DEPENDENCY_SNAPSHOT_LOCK_REQUIRED",
            "F05 Monte Carlo requires a T-24 dependency snapshot lock.",
        )
    lock_type = str(lock.get("lockType") or lock.get("type") or "").upper().replace("-", "")
    if lock_type != LOCK_TYPE_T24_DEPENDENCY:
        raise F05MonteCarloError(
            "F05_DEPENDENCY_SNAPSHOT_LOCK_NOT_T24",
            "F05 dependency snapshot lock must be T24_DEPENDENCY.",
            details={"lockType": lock.get("lockType") or lock.get("type")},
        )
    snapshot_id = lock.get("snapshotId") or lock.get("dependencySnapshotId")
    if not snapshot_id or not lock.get("lockedAt"):
        raise F05MonteCarloError(
            "F05_DEPENDENCY_SNAPSHOT_LOCK_INCOMPLETE",
            "F05 dependency snapshot lock requires snapshotId and lockedAt.",
        )
    return {
        "lockType": LOCK_TYPE_T24_DEPENDENCY,
        "snapshotId": snapshot_id,
        "lockedAt": lock.get("lockedAt"),
        "source": lock.get("source", "prediction_snapshots"),
    }


def has_t60_lineup_signal(match):
    prediction = match.get("prediction") or match.get("lockedPrediction") or {}
    lineup_check = prediction.get("finalLineupCheck") or match.get("finalLineupCheck") or {}
    lineup_shock = lineup_check.get("lineupShock") or match.get("lineupShock") or {}
    return bool(
        match.get("actualLineup")
        or lineup_shock.get("applied")
        or str(match.get("snapshotType") or "").upper() == "T60_LINEUP_RECALC"
    )


def sanitize_matches_for_dependency_lock(matches):
    sanitized = []
    ignored_t60 = []
    for match in matches:
        item = copy.deepcopy(match)
        if has_t60_lineup_signal(item):
            ignored_t60.append(item.get("matchId"))
            item.pop("actualLineup", None)
            item.pop("lineupShock", None)
            item.pop("finalLineupCheck", None)
            prediction = item.get("prediction") or item.get("lockedPrediction")
            if isinstance(prediction, dict):
                prediction.pop("finalLineupCheck", None)
        sanitized.append(item)
    return sanitized, [match_id for match_id in ignored_t60 if match_id]


def group_matches(matches):
    groups = {}
    for match in matches:
        if match.get("stage", GROUP_STAGE) != GROUP_STAGE or not match.get("group"):
            continue
        groups.setdefault(match["group"], []).append(match)
    return groups


def table_before_current(matches, current):
    tables = {}
    for group, group_items in group_matches(matches).items():
        table = {}
        for match in group_items:
            table.setdefault(match["homeTeam"], empty_record())
            table.setdefault(match["awayTeam"], empty_record())
        for match in sorted(group_items, key=match_sort_key):
            score = match.get("actualScore")
            if not score or not match_started_before(match, current):
                continue
            apply_score(table, match["homeTeam"], match["awayTeam"], int(score["home"]), int(score["away"]))
        tables[group] = table
    return tables


def ranking_for_group(table):
    rows = []
    for team, record in table.items():
        item = {"team": team, **record}
        rows.append(item)
    rows.sort(key=lambda row: (-row["points"], -row["gd"], -row["gf"], row["team"]))
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    return rows


def current_outcome_to_result(current, team, outcome):
    if outcome == "D":
        return "draw"
    if team == current["homeTeam"]:
        return "home" if outcome == "W" else "away"
    return "away" if outcome == "W" else "home"


def simulate_once(matches, current, rng, fixed_team=None, fixed_outcome=None):
    tables = table_before_current(matches, current)
    for match in sorted(matches, key=match_sort_key):
        if match.get("stage", GROUP_STAGE) != GROUP_STAGE or not match.get("group"):
            continue
        if match.get("actualScore") and match_started_before(match, current):
            continue
        fixed_result = None
        if fixed_team and fixed_outcome and same_match(match, current):
            fixed_result = current_outcome_to_result(current, fixed_team, fixed_outcome)
        home_goals, away_goals = sample_score(match, rng, fixed_result=fixed_result)
        apply_score(tables[match["group"]], match["homeTeam"], match["awayTeam"], home_goals, away_goals)

    rankings_by_group = {
        group: ranking_for_group(table)
        for group, table in tables.items()
    }
    top_two = set()
    third_rows = []
    for group, rankings in rankings_by_group.items():
        for row in rankings[:AUTO_ADVANCERS_PER_GROUP]:
            top_two.add(row["team"])
        if len(rankings) >= 3:
            third = dict(rankings[2])
            third["group"] = group
            third_rows.append(third)

    third_rows.sort(key=lambda row: (-row["points"], -row["gd"], -row["gf"], row["group"], row["team"]))
    third_advancers = {row["team"] for row in third_rows[:THIRD_PLACE_ADVANCERS]}
    return {
        "advanced": top_two | third_advancers,
        "topTwo": top_two,
        "thirdAdvancers": third_advancers,
        "thirdRows": third_rows,
    }


def all_group_teams(matches):
    teams = set()
    for match in matches:
        if match.get("stage", GROUP_STAGE) != GROUP_STAGE or not match.get("group"):
            continue
        teams.add(match["homeTeam"])
        teams.add(match["awayTeam"])
    return sorted(teams)


def run_advancement_trials(matches, current, simulations, seed, fixed_team=None, fixed_outcome=None):
    rng = random.Random(seed)
    teams = all_group_teams(matches)
    advanced_counts = {team: 0 for team in teams}
    top_two_counts = {team: 0 for team in teams}
    third_advance_counts = {team: 0 for team in teams}
    third_place_counts = {team: 0 for team in teams}
    for _ in range(simulations):
        result = simulate_once(matches, current, rng, fixed_team=fixed_team, fixed_outcome=fixed_outcome)
        for team in result["advanced"]:
            advanced_counts[team] += 1
        for team in result["topTwo"]:
            top_two_counts[team] += 1
        for team in result["thirdAdvancers"]:
            third_advance_counts[team] += 1
        for row in result["thirdRows"]:
            third_place_counts[row["team"]] += 1
    return {
        team: {
            "advancementProbability": round(advanced_counts[team] / simulations, 4),
            "topTwoProbability": round(top_two_counts[team] / simulations, 4),
            "thirdPlaceProbability": round(third_place_counts[team] / simulations, 4),
            "thirdPlaceAdvanceProbability": round(third_advance_counts[team] / simulations, 4),
        }
        for team in teams
    }


def motivation_from_outcome_shares(outcome_scores, played):
    win_share = outcome_scores["W"]
    draw_share = outcome_scores["D"]
    loss_share = outcome_scores["L"]
    if played == 0:
        return 0.0, 0.02, 0.0, "小组首战，48队晋级模拟按中性动机处理。"
    if loss_share >= 0.85:
        return 0.4, 0.45, max(0.0, draw_share - loss_share), "即使输球仍大概率出线，存在轮换空间。"
    if win_share <= 0.15:
        return -0.8, 0.3, 0.0, "即使赢球也很难出线，赛制动机下修。"

    must_win_pressure = max(0.0, win_share - draw_share)
    survival_pressure = max(0.0, draw_share - loss_share)
    draw_incentive = clamp((draw_share - loss_share) - max(0.0, win_share - draw_share) * 0.5, 0.0, 1.0)
    motivation = must_win_pressure * 4.0 + survival_pressure * 1.8
    rotation = 0.05
    if draw_incentive >= 0.35 and loss_share >= 0.35:
        rotation = 0.18
    if must_win_pressure >= 0.45:
        rotation = 0.02
    note = (
        f"48队模拟出线率：赢{win_share:.0%}、平{draw_share:.0%}、负{loss_share:.0%}；"
        f"必须争胜压力{must_win_pressure:.0%}。"
    )
    return clamp(motivation, -1.5, 4.0), rotation, draw_incentive, note


def completed_played_count(matches, current, team):
    count = 0
    for match in matches:
        if team not in {match.get("homeTeam"), match.get("awayTeam")}:
            continue
        if match.get("actualScore") and match_started_before(match, current):
            count += 1
    return count


def build_match_context(result, current, matches):
    home = current["homeTeam"]
    away = current["awayTeam"]
    home_scores = result["currentMatch"]["homeQualificationByOutcome"]
    away_scores = result["currentMatch"]["awayQualificationByOutcome"]
    home_motivation, home_rotation, home_draw_incentive, home_note = motivation_from_outcome_shares(
        home_scores,
        completed_played_count(matches, current, home),
    )
    away_motivation, away_rotation, away_draw_incentive, away_note = motivation_from_outcome_shares(
        away_scores,
        completed_played_count(matches, current, away),
    )
    match_draw_incentive = round(min(home_draw_incentive, away_draw_incentive), 4)
    return {
        "homeMotivationScore": round(home_motivation, 2),
        "awayMotivationScore": round(away_motivation, 2),
        "homeRotationRisk": round(home_rotation, 2),
        "awayRotationRisk": round(away_rotation, 2),
        "homeQualificationByOutcome": home_scores,
        "awayQualificationByOutcome": away_scores,
        "homeMustWinPressure": round(max(0.0, home_scores["W"] - home_scores["D"]), 4),
        "awayMustWinPressure": round(max(0.0, away_scores["W"] - away_scores["D"]), 4),
        "matchDrawIncentive": match_draw_incentive,
        "dependencySnapshotId": result["dependencySnapshotLock"]["snapshotId"],
        "qualificationModel": FORMAT_WC2026_48,
        "reasoning": f"{home}: {home_note} {away}: {away_note}",
    }


def validate_payload(payload):
    payload = payload or {}
    lock = normalize_lock(payload.get("dependencySnapshotLock") or payload.get("t24DependencySnapshotLock"))
    matches = payload.get("matches")
    if not isinstance(matches, list) or not matches:
        raise F05MonteCarloError(
            "F05_MATCHES_REQUIRED",
            "F05 Monte Carlo requires a non-empty matches list.",
        )
    current_match_id = payload.get("currentMatchId") or (payload.get("currentMatch") or {}).get("matchId")
    current = payload.get("currentMatch")
    if current_match_id:
        current = next((match for match in matches if match.get("matchId") == current_match_id), current)
    if not isinstance(current, dict):
        raise F05MonteCarloError(
            "F05_CURRENT_MATCH_REQUIRED",
            "F05 Monte Carlo requires currentMatch or currentMatchId.",
        )
    if current.get("stage", GROUP_STAGE) != GROUP_STAGE or not current.get("group"):
        raise F05MonteCarloError(
            "F05_GROUP_STAGE_REQUIRED",
            "F05 Monte Carlo only runs for group-stage matches with a group.",
        )
    try:
        simulations = int(payload.get("simulations", DEFAULT_SIMULATIONS))
    except (TypeError, ValueError):
        simulations = DEFAULT_SIMULATIONS
    simulations = max(1, min(MAX_SIMULATIONS, simulations))
    try:
        seed = int(payload.get("seed", 2026))
    except (TypeError, ValueError):
        seed = 2026
    return lock, matches, current, simulations, seed


def run_f05_monte_carlo(payload):
    lock, raw_matches, current, simulations, seed = validate_payload(payload)
    matches, ignored_t60_ids = sanitize_matches_for_dependency_lock(raw_matches)
    current = next((match for match in matches if same_match(match, current)), current)
    groups = group_matches(matches)
    if len(groups) < 12:
        raise F05MonteCarloError(
            "F05_WC2026_GROUP_SET_INCOMPLETE",
            "F05 48-team simulation requires all 12 groups so third-place ranking is cross-group.",
            details={"groupCount": len(groups)},
        )

    base = run_advancement_trials(matches, current, simulations, seed)
    current_match = {
        "matchId": current.get("matchId"),
        "group": current.get("group"),
        "homeTeam": current.get("homeTeam"),
        "awayTeam": current.get("awayTeam"),
        "homeQualificationByOutcome": {},
        "awayQualificationByOutcome": {},
    }
    outcome_seed_offset = {"W": 101, "D": 202, "L": 303}
    for team_key, team in (("home", current["homeTeam"]), ("away", current["awayTeam"])):
        scores = {}
        for outcome in ("W", "D", "L"):
            fixed = run_advancement_trials(
                matches,
                current,
                simulations,
                seed + outcome_seed_offset[outcome] + (17 if team_key == "away" else 0),
                fixed_team=team,
                fixed_outcome=outcome,
            )
            scores[outcome] = fixed[team]["advancementProbability"]
        current_match[f"{team_key}QualificationByOutcome"] = scores

    result = {
        "status": "READY",
        "format": FORMAT_WC2026_48,
        "generatedAt": current_utc_iso(),
        "simulations": simulations,
        "seed": seed,
        "dependencySnapshotLock": lock,
        "guardrails": {
            "dependencySnapshotLockRequired": True,
            "t60CascadeBlocked": True,
            "ignoredT60LineupShockMatchIds": ignored_t60_ids,
            "note": "F05 uses the locked T-24 slate snapshot; T-60 single-match lineup shock inputs are ignored and do not cascade across groups.",
        },
        "groupCount": len(groups),
        "teamCount": len(all_group_teams(matches)),
        "teamAdvancement": base,
        "currentMatch": current_match,
        "tiebreaker": [
            "points",
            "goal_difference",
            "goals_for",
            "deterministic_team_name_fallback",
        ],
    }
    result["matchContext"] = build_match_context(result, current, matches)
    return result
