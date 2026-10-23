from datetime import datetime
from itertools import product

from .factors import clamp


def parse_date(value):
    return datetime.strptime(value[:10], "%Y-%m-%d").date()


def parse_minutes(value):
    if not value:
        return 12 * 60
    parts = value.split()[0].split(":")
    if len(parts) < 2:
        return 12 * 60
    return int(parts[0]) * 60 + int(parts[1])


def match_sort_key(match):
    return (parse_date(match["date"]), parse_minutes(match.get("time", "")), match.get("matchId", ""))


def match_started_before(candidate, current):
    candidate_key = match_sort_key(candidate)
    current_key = match_sort_key(current)
    return candidate_key < current_key


def result_points(goals_for, goals_against):
    if goals_for > goals_against:
        return 3
    if goals_for < goals_against:
        return 0
    return 1


def empty_record():
    return {"played": 0, "points": 0, "gf": 0, "ga": 0, "gd": 0}


def apply_result(table, match):
    home = match["homeTeam"]
    away = match["awayTeam"]
    home_score = match["actualScore"]["home"]
    away_score = match["actualScore"]["away"]
    for team in (home, away):
        table.setdefault(team, empty_record())
    table[home]["played"] += 1
    table[away]["played"] += 1
    table[home]["points"] += result_points(home_score, away_score)
    table[away]["points"] += result_points(away_score, home_score)
    table[home]["gf"] += home_score
    table[home]["ga"] += away_score
    table[away]["gf"] += away_score
    table[away]["ga"] += home_score
    table[home]["gd"] = table[home]["gf"] - table[home]["ga"]
    table[away]["gd"] = table[away]["gf"] - table[away]["ga"]


def group_teams(matches, group):
    teams = set()
    for match in matches:
        if match.get("group") != group:
            continue
        teams.add(match["homeTeam"])
        teams.add(match["awayTeam"])
    return sorted(teams)


def standings_before(matches, current):
    group = current.get("group")
    teams = group_teams(matches, group)
    table = {team: empty_record() for team in teams}
    for match in sorted(matches, key=match_sort_key):
        if match.get("stage") != "GROUP_STAGE" or match.get("group") != group:
            continue
        if not match_started_before(match, current):
            continue
        apply_result(table, match)
    return table


def qualification_share(table, team):
    points = table[team]["points"]
    higher = sum(1 for record in table.values() if record["points"] > points)
    tied = sum(1 for record in table.values() if record["points"] == points)
    available_slots = max(0, 2 - higher)
    if available_slots <= 0:
        return 0.0
    return min(1.0, available_slots / tied)


def add_points(record, points):
    updated = dict(record)
    updated["played"] += 1
    updated["points"] += points
    return updated


def projected_table(base_table, remaining_matches, outcomes):
    table = {team: dict(record) for team, record in base_table.items()}
    for match, outcome in zip(remaining_matches, outcomes):
        home = match["homeTeam"]
        away = match["awayTeam"]
        if outcome == "H":
            home_points, away_points = 3, 0
        elif outcome == "A":
            home_points, away_points = 0, 3
        else:
            home_points, away_points = 1, 1
        table[home] = add_points(table[home], home_points)
        table[away] = add_points(table[away], away_points)
    return table


def qualification_by_current_outcome(matches, current, team):
    group = current.get("group")
    base_table = standings_before(matches, current)
    remaining = [
        match for match in sorted(matches, key=match_sort_key)
        if match.get("stage") == "GROUP_STAGE"
        and match.get("group") == group
        and not match_started_before(match, current)
    ]
    if current not in remaining:
        remaining.insert(0, current)

    outcome_scores = {}
    for current_outcome in ("W", "D", "L"):
        shares = []
        other_matches = [match for match in remaining if match is not current]
        for other_outcomes in product(("H", "D", "A"), repeat=len(other_matches)):
            outcomes = []
            other_iter = iter(other_outcomes)
            for match in remaining:
                if match is current:
                    if current_outcome == "D":
                        outcomes.append("D")
                    elif (current_outcome == "W" and match["homeTeam"] == team) or (current_outcome == "L" and match["awayTeam"] == team):
                        outcomes.append("H")
                    else:
                        outcomes.append("A")
                else:
                    outcomes.append(next(other_iter))
            table = projected_table(base_table, remaining, outcomes)
            shares.append(qualification_share(table, team))
        outcome_scores[current_outcome] = sum(shares) / len(shares) if shares else 0.0
    return outcome_scores


def motivation_from_qualification(outcome_scores, played):
    if played == 0:
        return 0.0, 0.02, "小组首战，赛制动机按中性。"

    win_share = outcome_scores["W"]
    draw_share = outcome_scores["D"]
    loss_share = outcome_scores["L"]
    if loss_share >= 0.85:
        return 0.4, 0.45, "即使输球仍大概率出线，存在轮换空间。"
    if win_share <= 0.15:
        return -0.8, 0.3, "即使赢球也很难出线，赛制动机下修。"

    must_win_pressure = max(0, win_share - draw_share)
    survival_pressure = max(0, draw_share - loss_share)
    motivation = must_win_pressure * 4.0 + survival_pressure * 1.8
    rotation = 0.05
    if draw_share >= 0.75 and loss_share >= 0.45:
        rotation = 0.18
    if must_win_pressure >= 0.45:
        rotation = 0.02
    note = (
        f"出线份额估计：赢{win_share:.0%}、平{draw_share:.0%}、负{loss_share:.0%}；"
        f"必须争胜压力{must_win_pressure:.0%}。"
    )
    return clamp(motivation, -1.5, 4.0), rotation, note


def previous_match(matches, current, team):
    candidates = [
        match for match in matches
        if team in {match["homeTeam"], match["awayTeam"]}
        and match_started_before(match, current)
    ]
    if not candidates:
        return None
    return max(candidates, key=match_sort_key)


def build_rest_context(matches, current):
    home_previous = previous_match(matches, current, current["homeTeam"])
    away_previous = previous_match(matches, current, current["awayTeam"])
    current_date = parse_date(current["date"])
    home_rest = (current_date - parse_date(home_previous["date"])).days if home_previous else None
    away_rest = (current_date - parse_date(away_previous["date"])).days if away_previous else None
    return {
        "homeRestDays": home_rest,
        "awayRestDays": away_rest,
        "homePreviousMatchId": home_previous["matchId"] if home_previous else None,
        "awayPreviousMatchId": away_previous["matchId"] if away_previous else None,
    }


def build_group_motivation_context(matches, current):
    if current.get("stage") != "GROUP_STAGE" or not current.get("group"):
        return {
            "homeMotivationScore": 0,
            "awayMotivationScore": 0,
            "homeRotationRisk": 0.05,
            "awayRotationRisk": 0.05,
            "reasoning": "非小组赛或缺少小组字段，F05按中性处理。",
        }

    table = standings_before(matches, current)
    home = current["homeTeam"]
    away = current["awayTeam"]
    home_scores = qualification_by_current_outcome(matches, current, home)
    away_scores = qualification_by_current_outcome(matches, current, away)
    home_motivation, home_rotation, home_note = motivation_from_qualification(home_scores, table[home]["played"])
    away_motivation, away_rotation, away_note = motivation_from_qualification(away_scores, table[away]["played"])
    return {
        "homeMotivationScore": round(home_motivation, 2),
        "awayMotivationScore": round(away_motivation, 2),
        "homeRotationRisk": round(home_rotation, 2),
        "awayRotationRisk": round(away_rotation, 2),
        "homeQualificationByOutcome": home_scores,
        "awayQualificationByOutcome": away_scores,
        "homeGroupRecord": table[home],
        "awayGroupRecord": table[away],
        "reasoning": f"{home}: {home_note} {away}: {away_note}",
    }


def build_tournament_context(matches, current):
    return {
        "matchContext": build_group_motivation_context(matches, current),
        "restData": build_rest_context(matches, current),
    }
