import json
import os
from collections import Counter


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CALIBRATION_DIR = os.path.join(PROJECT_ROOT, "data", "calibration")
SPLIT_PLAN = os.path.join(CALIBRATION_DIR, "worldcup_split_plan.json")

PRE_MATCH_FEATURE_FILES = {
    "elo": "wc{year}_elo_ratings.json",
    "fifaRank": "wc{year}_fifa_ranks.json",
    "internationalResults": "international_results.csv",
    "worldCupSchedule": "wc{year}_matches_openfootball.json",
    "odds": "wc{year}_odds_1x2.json",
    "rollingForm": "wc{year}_rolling_form.json",
    "rollingXg": "wc{year}_rolling_xg.json",
    "lineups": "wc{year}_lineups_pre_match.json",
    "injuries": "wc{year}_injuries_pre_match.json",
}

FACTOR_REQUIREMENTS = {
    "F01": ["elo"],
    "F02": ["internationalResults"],
    "F04": ["lineups", "injuries"],
    "F05": ["worldCupSchedule"],
    "F06": ["worldCupSchedule"],
    "F07": ["internationalResults"],
    "F08": ["internationalResults"],
    "F12": ["odds"],
    "F13": ["lineups"],
    "F17": ["lineups"],
}


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def result(score):
    if score["home"] > score["away"]:
        return "HOME_WIN"
    if score["home"] < score["away"]:
        return "AWAY_WIN"
    return "DRAW"


def audit_match_file(year, filename):
    path = os.path.join(CALIBRATION_DIR, filename)
    if not os.path.exists(path):
        return {"year": year, "file": filename, "exists": False}

    matches = load_json(path)
    stages = Counter(match["stage"] for match in matches)
    results = Counter(result(match["actualScore"]) for match in matches)
    return {
        "year": year,
        "file": filename,
        "exists": True,
        "matches": len(matches),
        "stageDistribution": dict(stages),
        "regularTimeResultDistribution": dict(results),
        "extraTimeMatches": sum(1 for match in matches if "afterExtraTimeScore" in match),
        "penaltyMatches": sum(1 for match in matches if "penaltyWinner" in match),
        "hasSourceMetadata": all("source" in match for match in matches),
    }


def audit_feature_files(year):
    features = {}
    for feature, template in PRE_MATCH_FEATURE_FILES.items():
        filename = template.format(year=year)
        path = os.path.join(CALIBRATION_DIR, filename)
        caveat = "must be snapshotted before kickoff; do not derive from the target match result"
        if feature == "internationalResults":
            caveat = "use only rows dated before each kickoff; source full-time scores may include extra time"
        if feature == "worldCupSchedule":
            caveat = "derive only from same-tournament matches that started before kickoff; simultaneous final group matches must not leak"
        features[feature] = {
            "file": filename,
            "exists": os.path.exists(path),
            "preMatchRequirement": caveat,
        }
    return features


def factor_status(features):
    statuses = {}
    for factor, requirements in FACTOR_REQUIREMENTS.items():
        missing = [feature for feature in requirements if not features[feature]["exists"]]
        statuses[factor] = {
            "available": not missing,
            "requiredFeatureFiles": requirements,
            "missingFeatureFiles": missing,
        }
    return statuses


def audit_split():
    plan = load_json(SPLIT_PLAN)
    years = plan["calibrationYears"] + [plan["blindTestYear"]]
    match_audits = []
    feature_audits = {}
    factor_audits = {}

    for year in years:
        filename = plan["matchFiles"][str(year)]
        match_audits.append(audit_match_file(year, filename))
        feature_audits[str(year)] = audit_feature_files(year)
        factor_audits[str(year)] = factor_status(feature_audits[str(year)])

    blockers = []
    for match_audit in match_audits:
        if not match_audit.get("exists"):
            blockers.append(f"{match_audit['year']} match file is missing")
        elif match_audit.get("matches") != 64:
            blockers.append(f"{match_audit['year']} match count is {match_audit.get('matches')}, expected 64")

    calibration_feature_ready = all(
        status["available"]
        for year in plan["calibrationYears"]
        for status in factor_audits[str(year)].values()
    )
    if not calibration_feature_ready:
        blockers.append("2014/2018 pre-match feature layer is incomplete; do not train weighted model yet")

    return {
        "splitPlan": plan,
        "matchAudits": match_audits,
        "featureAudits": feature_audits,
        "factorAudits": factor_audits,
        "readyForResultOnlyBaseline": not any("match file" in blocker or "match count" in blocker for blocker in blockers),
        "readyForWeightedModelCalibration": calibration_feature_ready and not blockers,
        "blockers": blockers,
    }


def main():
    print(json.dumps(audit_split(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
