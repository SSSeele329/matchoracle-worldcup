import csv
import os
from datetime import date, datetime, timedelta

from .factors import clamp

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CALIBRATION_DIR = os.path.join(PROJECT_ROOT, "data", "calibration")
INTERNATIONAL_RESULTS_URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
DEFAULT_RESULTS_PATH = os.path.join(CALIBRATION_DIR, "international_results.csv")

TEAM_ALIASES = {
    "Bosnia-Herzegovina": "Bosnia and Herzegovina",
    "Côte d'Ivoire": "Ivory Coast",
    "Ivory Coast": "Ivory Coast",
    "Korea Republic": "South Korea",
    "USA": "United States",
}

MAJOR_TOURNAMENTS = {
    "FIFA World Cup",
    "FIFA World Cup qualification",
    "UEFA Euro",
    "UEFA Euro qualification",
    "Copa América",
    "African Cup of Nations",
    "African Cup of Nations qualification",
    "AFC Asian Cup",
    "AFC Asian Cup qualification",
    "CONCACAF Championship",
    "CONCACAF Gold Cup",
    "CONCACAF Nations League",
    "UEFA Nations League",
    "Oceania Nations Cup",
}


def canonical_team(name):
    return TEAM_ALIASES.get(name, name)


def parse_date(value):
    if isinstance(value, date):
        return value
    return datetime.strptime(value[:10], "%Y-%m-%d").date()


def load_international_results(path=DEFAULT_RESULTS_PATH):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["home_score"] == "NA" or row["away_score"] == "NA":
                continue
            rows.append({
                "date": parse_date(row["date"]),
                "homeTeam": canonical_team(row["home_team"]),
                "awayTeam": canonical_team(row["away_team"]),
                "homeScore": int(row["home_score"]),
                "awayScore": int(row["away_score"]),
                "tournament": row["tournament"],
                "neutral": row["neutral"].strip().upper() == "TRUE",
            })
    rows.sort(key=lambda item: item["date"])
    return rows


def team_match_view(match, team):
    team = canonical_team(team)
    if match["homeTeam"] == team:
        return {
            "date": match["date"],
            "team": team,
            "opponent": match["awayTeam"],
            "goalsFor": match["homeScore"],
            "goalsAgainst": match["awayScore"],
            "points": result_points(match["homeScore"], match["awayScore"]),
            "isNeutral": match["neutral"],
            "tournament": match["tournament"],
        }
    if match["awayTeam"] == team:
        return {
            "date": match["date"],
            "team": team,
            "opponent": match["homeTeam"],
            "goalsFor": match["awayScore"],
            "goalsAgainst": match["homeScore"],
            "points": result_points(match["awayScore"], match["homeScore"]),
            "isNeutral": match["neutral"],
            "tournament": match["tournament"],
        }
    return None


def result_points(goals_for, goals_against):
    if goals_for > goals_against:
        return 3
    if goals_for < goals_against:
        return 0
    return 1


def competition_weight(tournament):
    if tournament == "Friendly":
        return 0.7
    if tournament in MAJOR_TOURNAMENTS:
        return 1.2
    if "qualification" in tournament.lower():
        return 1.1
    return 1.0


def recency_weight(match_date, as_of_date, half_life_days=365):
    age_days = max((as_of_date - match_date).days, 0)
    return 0.5 ** (age_days / half_life_days)


def weighted_average(values, fallback):
    numerator = sum(value * weight for value, weight in values)
    denominator = sum(weight for _, weight in values)
    if denominator <= 0:
        return fallback
    return numerator / denominator


def global_team_goal_average(rows, as_of_date, window_days=1460):
    start_date = as_of_date - timedelta(days=window_days)
    selected = [row for row in rows if start_date <= row["date"] < as_of_date]
    if not selected:
        selected = [row for row in rows if row["date"] < as_of_date]
    if not selected:
        return 1.25
    total_goals = sum(row["homeScore"] + row["awayScore"] for row in selected)
    return clamp(total_goals / (len(selected) * 2), 0.8, 1.8)


def build_team_prematch_profile(rows, team, as_of_date, max_matches=24, window_days=1460):
    team = canonical_team(team)
    as_of_date = parse_date(as_of_date)
    start_date = as_of_date - timedelta(days=window_days)
    views = []
    for row in rows:
        if row["date"] >= as_of_date or row["date"] < start_date:
            continue
        view = team_match_view(row, team)
        if view:
            views.append(view)

    extended = False
    if len(views) < 8:
        extended = True
        views = []
        for row in rows:
            if row["date"] >= as_of_date:
                continue
            view = team_match_view(row, team)
            if view:
                views.append(view)

    views = views[-max_matches:]
    global_avg = global_team_goal_average(rows, as_of_date, window_days)
    if not views:
        return {
            "team": team,
            "matchesUsed": 0,
            "windowDays": None,
            "extendedWindow": extended,
            "recentFormSequence": "",
            "goalsForAvg": global_avg,
            "goalsAgainstAvg": global_avg,
            "recentFormScore": 0.45,
            "attackIndex": 1.0,
            "defenseIndex": 1.0,
            "dataQuality": "LOW",
            "actualGoals_avg": round(global_avg, 3),
            "xGA_avg": round(global_avg, 3),
            "setpieceRate": 0.25,
        }

    weighted_goals_for = []
    weighted_goals_against = []
    weighted_points = []
    for view in views:
        weight = recency_weight(view["date"], as_of_date) * competition_weight(view["tournament"])
        weighted_goals_for.append((view["goalsFor"], weight))
        weighted_goals_against.append((view["goalsAgainst"], weight))
        weighted_points.append((view["points"] / 3.0, weight))

    effective_matches = sum(weight for _, weight in weighted_points)
    reliability = clamp(effective_matches / 10.0, 0.25, 1.0)
    goals_for = weighted_average(weighted_goals_for, global_avg)
    goals_against = weighted_average(weighted_goals_against, global_avg)
    goals_for = global_avg + (goals_for - global_avg) * reliability
    goals_against = global_avg + (goals_against - global_avg) * reliability
    recent_form = weighted_average(weighted_points, 0.45)
    recent_form_sequence = "-".join(
        "W" if view["points"] == 3 else "D" if view["points"] == 1 else "L"
        for view in views[-5:]
    )
    quality = "HIGH" if len(views) >= 14 and not extended else "MEDIUM" if len(views) >= 8 else "LOW"

    return {
        "team": team,
        "matchesUsed": len(views),
        "windowDays": window_days if not extended else None,
        "extendedWindow": extended,
        "recentFormSequence": recent_form_sequence,
        "goalsForAvg": round(goals_for, 3),
        "goalsAgainstAvg": round(goals_against, 3),
        "recentFormScore": round(recent_form, 3),
        "attackIndex": round(goals_for / global_avg, 3),
        "defenseIndex": round(goals_against / global_avg, 3),
        "dataQuality": quality,
        "actualGoals_avg": round(clamp(goals_for, 0.45, 2.7), 3),
        "xGA_avg": round(clamp(goals_against, 0.45, 2.7), 3),
        "setpieceRate": 0.25,
    }


def build_match_prematch_features(rows, home_team, away_team, as_of_date):
    home_profile = build_team_prematch_profile(rows, home_team, as_of_date)
    away_profile = build_team_prematch_profile(rows, away_team, as_of_date)
    return {
        "home": home_profile,
        "away": away_profile,
        "source": {
            "dataset": "martj42/international_results",
            "url": INTERNATIONAL_RESULTS_URL,
            "scoreCaveat": "Historical source stores full-time scores including extra time; target calibration still uses World Cup 90-minute scores.",
        },
    }


def profile_to_goal_data(profile):
    return {
        "actualGoals_avg": profile["actualGoals_avg"],
        "xGA_avg": profile["xGA_avg"],
        "setpieceRate": profile["setpieceRate"],
        "historicalMatchesUsed": profile["matchesUsed"],
        "historyDataQuality": profile["dataQuality"],
    }
