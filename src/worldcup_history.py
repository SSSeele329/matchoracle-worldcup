import json
import os
import urllib.request


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CALIBRATION_DIR = os.path.join(PROJECT_ROOT, "data", "calibration")

OPENFOOTBALL_URL = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/{year}/worldcup.json"

TEAM_ALIASES = {
    "United States": "USA",
    "South Korea": "Korea Republic",
}

ROUND_TO_STAGE = {
    "Round of 16": "ROUND_OF_16",
    "Quarter-finals": "QUARTER_FINAL",
    "Semi-finals": "SEMI_FINAL",
    "Match for third place": "THIRD_PLACE",
    "Final": "FINAL",
}


def normalize_team(name):
    return TEAM_ALIASES.get(name, name)


def normalize_stage(match):
    if match.get("group"):
        return "GROUP_STAGE"
    return ROUND_TO_STAGE.get(match.get("round"), match.get("round", "UNKNOWN"))


def score_dict(raw_score):
    return {"home": int(raw_score[0]), "away": int(raw_score[1])}


def penalty_winner(match):
    penalties = match.get("score", {}).get("p")
    if not penalties:
        return None
    if penalties[0] > penalties[1]:
        return normalize_team(match["team1"])
    if penalties[1] > penalties[0]:
        return normalize_team(match["team2"])
    return None


def normalize_match(year, index, match):
    score = match["score"]
    normalized = {
        "matchId": f"WC{year}-{index:03d}",
        "stage": normalize_stage(match),
        "homeTeam": normalize_team(match["team1"]),
        "awayTeam": normalize_team(match["team2"]),
        "date": match["date"],
        "time": match.get("time", ""),
        "group": match.get("group"),
        "venue": match.get("ground", ""),
        "actualScore": score_dict(score["ft"]),
        "source": {
            "provider": "openfootball/worldcup.json",
            "url": OPENFOOTBALL_URL.format(year=year),
            "scoreField": "score.ft",
            "scoreMeaning": "90-minute regular time plus stoppage time",
        },
    }
    if "et" in score:
        normalized["afterExtraTimeScore"] = score_dict(score["et"])
    if "p" in score:
        normalized["penaltyScore"] = score_dict(score["p"])
        winner = penalty_winner(match)
        if winner:
            normalized["penaltyWinner"] = winner
    return normalized


def fetch_openfootball_year(year):
    url = OPENFOOTBALL_URL.format(year=year)
    request = urllib.request.Request(url, headers={"User-Agent": "MatchOracle data pipeline"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def build_year_matches(year):
    payload = fetch_openfootball_year(year)
    return [normalize_match(year, index, match) for index, match in enumerate(payload["matches"], start=1)]


def write_year_matches(year, output_path=None):
    os.makedirs(CALIBRATION_DIR, exist_ok=True)
    output_path = output_path or os.path.join(CALIBRATION_DIR, f"wc{year}_matches_openfootball.json")
    matches = build_year_matches(year)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(matches, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return output_path, matches
