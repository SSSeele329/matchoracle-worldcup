import json
import os
import urllib.parse
import urllib.request

from bs4 import BeautifulSoup


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CALIBRATION_DIR = os.path.join(PROJECT_ROOT, "data", "calibration")

ELO_URL = "https://www.international-football.net/elo-ratings-table"

TEAM_ALIASES = {
    "Bosnia and Herzegovina": "Bosnia-Herzegovina",
    "Ivory Coast": "Côte d'Ivoire",
    "South Korea": "Korea Republic",
    "United States": "USA",
}

SNAPSHOT_DATES = {
    2002: {"year": 2002, "month": 5, "day": 30, "reason": "day before 2002 World Cup opening match"},
    2006: {"year": 2006, "month": 6, "day": 8, "reason": "day before 2006 World Cup opening match"},
    2010: {"year": 2010, "month": 6, "day": 10, "reason": "day before 2010 World Cup opening match"},
    2014: {"year": 2014, "month": 6, "day": 11, "reason": "day before 2014 World Cup opening match"},
    2018: {"year": 2018, "month": 6, "day": 13, "reason": "day before 2018 World Cup opening match"},
    2022: {"year": 2022, "month": 11, "day": 19, "reason": "day before 2022 World Cup opening match"},
}


def normalize_team(name):
    return TEAM_ALIASES.get(name, name)


def snapshot_url(snapshot):
    query = urllib.parse.urlencode({
        "confed": "",
        "day": f"{snapshot['day']:02d}",
        "month": f"{snapshot['month']:02d}",
        "old-team": "",
        "year": snapshot["year"],
    })
    return f"{ELO_URL}?{query}"


def fetch_elo_snapshot(snapshot):
    url = snapshot_url(snapshot)
    request = urllib.request.Request(url, headers={"User-Agent": "MatchOracle Elo snapshot"})
    with urllib.request.urlopen(request, timeout=25) as response:
        html = response.read().decode("utf-8")

    soup = BeautifulSoup(html, "html.parser")
    ratings = {}
    position = 1
    for table in soup.select("table.elorank"):
        for row in table.select("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in row.select("td")]
            if len(cells) < 3 or not cells[1] or not cells[2]:
                continue
            team = normalize_team(cells[1])
            ratings[team] = {"rank": position, "elo": int(cells[2])}
            position += 1
    return url, ratings


def load_worldcup_teams(year):
    openfootball_path = os.path.join(CALIBRATION_DIR, f"wc{year}_matches_openfootball.json")
    static_path = os.path.join(CALIBRATION_DIR, f"wc{year}_matches.json")
    path = openfootball_path if os.path.exists(openfootball_path) else static_path
    with open(path, "r", encoding="utf-8") as handle:
        matches = json.load(handle)
    return sorted({match["homeTeam"] for match in matches} | {match["awayTeam"] for match in matches})


def write_worldcup_elo_snapshot(year, output_path=None):
    if year not in SNAPSHOT_DATES:
        raise ValueError(f"No snapshot date configured for {year}")
    snapshot = SNAPSHOT_DATES[year]
    url, all_ratings = fetch_elo_snapshot(snapshot)
    teams = load_worldcup_teams(year)
    missing = [team for team in teams if team not in all_ratings]
    payload = {
        "year": year,
        "snapshotDate": f"{snapshot['year']}-{snapshot['month']:02d}-{snapshot['day']:02d}",
        "snapshotReason": snapshot["reason"],
        "source": {
            "provider": "international-football.net Elo ratings table",
            "url": url,
            "preMatch": True,
            "licenseNote": "Use for local research/prototyping; verify terms before commercial redistribution.",
        },
        "ratings": {team: all_ratings[team] for team in teams if team in all_ratings},
        "missingTeams": missing,
    }

    os.makedirs(CALIBRATION_DIR, exist_ok=True)
    output_path = output_path or os.path.join(CALIBRATION_DIR, f"wc{year}_elo_ratings.json")
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return output_path, payload
