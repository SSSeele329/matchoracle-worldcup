#!/usr/bin/env python3
"""
Batch Prediction Script for 2026 FIFA World Cup Group Stage
============================================================
Runs all 72 group-stage matches through the local MatchOracle API
(/api/predict) and saves results to a JSON report + prints a summary table.

Data sources:
- FIFA Rankings: June 11, 2026 official update
- Groups & Schedule: Official FIFA draw results
- Goal averages: Estimated from recent international form (last 10 matches)
- Venues: Official FIFA match schedule
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta

try:
    import urllib.request
    import urllib.error
except ImportError:
    print("ERROR: urllib not available")
    sys.exit(1)

API_BASE = "http://127.0.0.1:5012"

# ─── FIFA Rankings (June 11, 2026) ───────────────────────────────────────────
FIFA_RANKS = {
    "Argentina": 1, "Spain": 2, "France": 3, "England": 4,
    "Portugal": 5, "Brazil": 6, "Morocco": 7, "Netherlands": 8,
    "Belgium": 9, "Germany": 10, "Croatia": 11, "Italy": 12,
    "Colombia": 13, "Mexico": 14, "Senegal": 15, "Uruguay": 16,
    "United States": 17, "Japan": 18, "Switzerland": 19, "Iran": 20,
    "Turkiye": 22, "Ecuador": 23, "Austria": 24, "South Korea": 25,
    "Australia": 27, "Algeria": 28, "Egypt": 29, "Norway": 31,
    "Ivory Coast": 33, "Panama": 34, "Sweden": 38, "Czechia": 40,
    "Paraguay": 41, "Scotland": 42, "Tunisia": 45, "DR Congo": 46,
    "Uzbekistan": 50, "Qatar": 56, "Iraq": 57, "South Africa": 60,
    "Saudi Arabia": 61, "Jordan": 63, "Bosnia and Herzegovina": 64,
    "Cape Verde": 67, "Ghana": 73, "Curacao": 82, "Haiti": 83,
    "New Zealand": 85,
}

# ─── Team Statistics (estimated from recent 10-match form) ────────────────────
# Format: (goals_avg, xga_avg, setpiece_rate, typical_formation)
TEAM_STATS = {
    # Tier 1: Elite (Rank 1-6)
    "Argentina":    (2.1, 0.7, 0.25, "4-3-3"),
    "Spain":        (2.0, 0.6, 0.20, "4-3-3"),
    "France":       (1.9, 0.8, 0.25, "4-2-3-1"),
    "England":      (2.0, 0.7, 0.25, "4-2-3-1"),
    "Portugal":     (2.0, 0.8, 0.25, "4-3-3"),
    "Brazil":       (1.8, 0.9, 0.25, "4-2-3-1"),
    # Tier 2: Strong (Rank 7-15)
    "Morocco":      (1.5, 0.7, 0.30, "4-3-3"),
    "Netherlands":  (2.0, 0.8, 0.25, "3-4-3"),
    "Belgium":      (1.7, 0.9, 0.25, "3-4-3"),
    "Germany":      (2.2, 1.0, 0.25, "4-2-3-1"),
    "Croatia":      (1.6, 0.8, 0.20, "4-3-3"),
    "Colombia":     (1.6, 0.8, 0.25, "4-2-3-1"),
    "Mexico":       (1.4, 0.9, 0.25, "4-3-3"),
    "Senegal":      (1.4, 0.8, 0.30, "4-3-3"),
    "Uruguay":      (1.5, 0.8, 0.30, "4-4-2"),
    # Tier 3: Competitive (Rank 16-30)
    "United States":(1.5, 1.0, 0.25, "4-3-3"),
    "Japan":        (1.8, 0.9, 0.20, "4-2-3-1"),
    "Switzerland":  (1.4, 0.8, 0.20, "3-4-3"),
    "Iran":         (1.3, 0.9, 0.35, "4-3-3"),
    "Turkiye":      (1.6, 1.0, 0.25, "4-2-3-1"),
    "Ecuador":      (1.4, 1.0, 0.25, "4-3-3"),
    "Austria":      (1.7, 1.0, 0.30, "4-2-3-1"),
    "South Korea":  (1.4, 0.9, 0.25, "4-3-3"),
    "Australia":    (1.4, 1.1, 0.30, "4-4-2"),
    "Algeria":      (1.3, 0.9, 0.30, "4-3-3"),
    "Egypt":        (1.2, 0.8, 0.30, "4-2-3-1"),
    "Norway":       (1.6, 1.0, 0.25, "4-3-3"),
    # Tier 4: Underdog (Rank 31-50)
    "Ivory Coast":  (1.3, 1.0, 0.30, "4-3-3"),
    "Panama":       (1.0, 1.2, 0.35, "5-4-1"),
    "Sweden":       (1.4, 1.0, 0.30, "4-4-2"),
    "Czechia":      (1.3, 1.0, 0.25, "4-2-3-1"),
    "Paraguay":     (1.2, 1.0, 0.25, "4-4-2"),
    "Scotland":     (1.2, 1.1, 0.30, "3-5-2"),
    "Tunisia":      (1.1, 0.9, 0.30, "4-3-3"),
    "DR Congo":     (1.2, 1.1, 0.25, "4-3-3"),
    "Uzbekistan":   (1.2, 1.0, 0.25, "4-3-3"),
    # Tier 5: Dark Horse / Weaker (Rank 50+)
    "Qatar":        (1.0, 1.2, 0.30, "3-5-2"),
    "Iraq":         (1.1, 1.1, 0.30, "4-3-3"),
    "South Africa": (1.0, 1.1, 0.30, "4-3-3"),
    "Saudi Arabia": (1.1, 1.1, 0.30, "4-3-3"),
    "Jordan":       (1.0, 1.1, 0.30, "4-3-3"),
    "Bosnia and Herzegovina": (1.3, 1.1, 0.25, "4-3-3"),
    "Cape Verde":   (0.9, 1.2, 0.35, "4-3-3"),
    "Ghana":        (1.1, 1.2, 0.30, "4-2-3-1"),
    "Curacao":      (0.8, 1.5, 0.35, "5-3-2"),
    "Haiti":        (0.7, 1.6, 0.35, "4-4-2"),
    "New Zealand":  (0.9, 1.3, 0.35, "4-4-2"),
}

# ─── 2026 World Cup Groups ───────────────────────────────────────────────────
GROUPS = {
    "A": ["Mexico", "South Korea", "Czechia", "South Africa"],
    "B": ["Canada", "Bosnia and Herzegovina", "Qatar", "Switzerland"],
    "C": ["Brazil", "Morocco", "Haiti", "Scotland"],
    "D": ["United States", "Paraguay", "Turkiye", "Australia"],
    "E": ["Germany", "Curacao", "Ecuador", "Ivory Coast"],
    "F": ["Netherlands", "Japan", "Sweden", "Tunisia"],
    "G": ["Belgium", "Egypt", "Iran", "New Zealand"],
    "H": ["Spain", "Cape Verde", "Saudi Arabia", "Uruguay"],
    "I": ["France", "Senegal", "Iraq", "Norway"],
    "J": ["Argentina", "Algeria", "Austria", "Jordan"],
    "K": ["Portugal", "DR Congo", "Uzbekistan", "Colombia"],
    "L": ["England", "Croatia", "Ghana", "Panama"],
}

# Note: "Canada" is not in FIFA_RANKS from our search, let's add it
if "Canada" not in FIFA_RANKS:
    FIFA_RANKS["Canada"] = 43  # approximate

if "Canada" not in TEAM_STATS:
    TEAM_STATS["Canada"] = (1.3, 1.0, 0.25, "4-4-2")

# ─── Match Schedule with Venues ──────────────────────────────────────────────
# Group stage: June 11 - June 27, 2026
# Each group plays 3 matchdays:
#   MD1: 1v4, 2v3  |  MD2: 1v3, 4v2  |  MD3: 1v2, 3v4

VENUES = {
    "A": ["Estadio Azteca, Mexico City", "Estadio Akron, Guadalajara", "Estadio BBVA, Monterrey"],
    "B": ["BMO Field, Toronto", "BC Place, Vancouver", "BMO Field, Toronto"],
    "C": ["MetLife Stadium, New York/NJ", "Gillette Stadium, Boston", "Lincoln Financial Field, Philadelphia"],
    "D": ["SoFi Stadium, Los Angeles", "Levi's Stadium, San Francisco", "Lumen Field, Seattle"],
    "E": ["NRG Stadium, Houston", "AT&T Stadium, Dallas", "Arrowhead Stadium, Kansas City"],
    "F": ["Hard Rock Stadium, Miami", "Mercedes-Benz Stadium, Atlanta", "Hard Rock Stadium, Miami"],
    "G": ["Lincoln Financial Field, Philadelphia", "MetLife Stadium, New York/NJ", "Gillette Stadium, Boston"],
    "H": ["AT&T Stadium, Dallas", "NRG Stadium, Houston", "Arrowhead Stadium, Kansas City"],
    "I": ["Mercedes-Benz Stadium, Atlanta", "Hard Rock Stadium, Miami", "Mercedes-Benz Stadium, Atlanta"],
    "J": ["SoFi Stadium, Los Angeles", "Lumen Field, Seattle", "Levi's Stadium, San Francisco"],
    "K": ["Lumen Field, Seattle", "SoFi Stadium, Los Angeles", "Levi's Stadium, San Francisco"],
    "L": ["Gillette Stadium, Boston", "Lincoln Financial Field, Philadelphia", "MetLife Stadium, New York/NJ"],
}

# Base dates for each matchday (approximate based on FIFA schedule)
MD_DATES = {
    "A": ["2026-06-11", "2026-06-16", "2026-06-21"],
    "B": ["2026-06-12", "2026-06-17", "2026-06-22"],
    "C": ["2026-06-13", "2026-06-18", "2026-06-23"],
    "D": ["2026-06-12", "2026-06-17", "2026-06-22"],
    "E": ["2026-06-14", "2026-06-19", "2026-06-24"],
    "F": ["2026-06-14", "2026-06-19", "2026-06-24"],
    "G": ["2026-06-15", "2026-06-20", "2026-06-25"],
    "H": ["2026-06-15", "2026-06-20", "2026-06-25"],
    "I": ["2026-06-16", "2026-06-21", "2026-06-26"],
    "J": ["2026-06-16", "2026-06-21", "2026-06-26"],
    "K": ["2026-06-17", "2026-06-22", "2026-06-27"],
    "L": ["2026-06-13", "2026-06-18", "2026-06-23"],
}


def generate_matches():
    """Generate all 72 group stage matches with metadata."""
    matches = []
    match_num = 1
    for group_name, teams in GROUPS.items():
        t1, t2, t3, t4 = teams
        dates = MD_DATES[group_name]
        venues = VENUES[group_name]

        # Matchday 1: 1v4, 2v3
        matches.append({
            "matchNum": match_num, "group": group_name, "matchday": 1,
            "home": t1, "away": t4,
            "date": dates[0], "venue": venues[0],
        })
        match_num += 1
        matches.append({
            "matchNum": match_num, "group": group_name, "matchday": 1,
            "home": t2, "away": t3,
            "date": dates[0], "venue": venues[0],
        })
        match_num += 1

        # Matchday 2: 1v3, 4v2
        matches.append({
            "matchNum": match_num, "group": group_name, "matchday": 2,
            "home": t1, "away": t3,
            "date": dates[1], "venue": venues[1],
        })
        match_num += 1
        matches.append({
            "matchNum": match_num, "group": group_name, "matchday": 2,
            "home": t4, "away": t2,
            "date": dates[1], "venue": venues[1],
        })
        match_num += 1

        # Matchday 3: 1v2, 3v4
        matches.append({
            "matchNum": match_num, "group": group_name, "matchday": 3,
            "home": t1, "away": t2,
            "date": dates[2], "venue": venues[2],
        })
        match_num += 1
        matches.append({
            "matchNum": match_num, "group": group_name, "matchday": 3,
            "home": t3, "away": t4,
            "date": dates[2], "venue": venues[2],
        })
        match_num += 1

    return matches


def build_payload(match):
    """Build the API request payload for a single match."""
    home = match["home"]
    away = match["away"]

    h_stats = TEAM_STATS.get(home, (1.0, 1.2, 0.25, "4-4-2"))
    a_stats = TEAM_STATS.get(away, (1.0, 1.2, 0.25, "4-4-2"))

    # Build kickoff datetime (future time so prematch logic works)
    kickoff = f"{match['date']}T18:00:00Z"

    payload = {
        "matchId": f"wc2026-group{match['group']}-md{match['matchday']}-{home.lower().replace(' ', '_')}-vs-{away.lower().replace(' ', '_')}",
        "match": {
            "homeTeam": home,
            "awayTeam": away,
            "stage": "GROUP_STAGE",
            "datetime": kickoff,
            "venue": match["venue"],
        },
        "teamData": {
            "home": {"fifaRank": FIFA_RANKS.get(home, 80)},
            "away": {"fifaRank": FIFA_RANKS.get(away, 80)},
        },
        "understatCoverage": {"home": 0, "away": 0},
        "formationData": {
            "home": h_stats[3],
            "away": a_stats[3],
        },
        "goalData": {
            "home": {
                "actualGoals_avg": h_stats[0],
                "xGA_avg": h_stats[1],
                "setpieceRate": h_stats[2],
            },
            "away": {
                "actualGoals_avg": a_stats[0],
                "xGA_avg": a_stats[1],
                "setpieceRate": a_stats[2],
            },
        },
    }
    return payload


def call_predict(payload):
    """Call the /api/predict endpoint."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE}/api/predict",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"error": f"HTTP {e.code}", "detail": body}
    except Exception as e:
        return {"error": str(e)}


def extract_summary(match, result):
    """Extract key prediction fields for the summary."""
    verdict = result.get("verdict") or {}
    probs = result.get("probabilities") or {}
    canonical = result.get("canonicalProbability") or {}
    cp = canonical.get("probabilities") or probs
    reliability = result.get("dataReliability") or {}

    return {
        "matchNum": match["matchNum"],
        "group": match["group"],
        "matchday": match["matchday"],
        "date": match["date"],
        "home": match["home"],
        "away": match["away"],
        "venue": match["venue"],
        "predictedResult": verdict.get("result", "N/A"),
        "confidence": verdict.get("confidence", "N/A"),
        "confidenceScore": verdict.get("confidenceScore", 0),
        "executiveSummary": verdict.get("executiveSummary", ""),
        "homeWinProb": round(cp.get("home", 0) * 100, 1) if cp else 0,
        "drawProb": round(cp.get("draw", 0) * 100, 1) if cp else 0,
        "awayWinProb": round(cp.get("away", 0) * 100, 1) if cp else 0,
        "dataReliabilityStatus": reliability.get("status", "N/A"),
        "dataReliabilityScore": reliability.get("score", 0),
    }


def print_summary_table(summaries):
    """Print a formatted summary table."""
    current_group = None
    print("\n" + "=" * 130)
    print("  2026 FIFA World Cup 小组赛 全部预测结果")
    print("=" * 130)

    for s in summaries:
        if s["group"] != current_group:
            current_group = s["group"]
            print(f"\n{'─' * 130}")
            print(f"  小组 {current_group}")
            print(f"{'─' * 130}")
            print(f"  {'日期':<12} {'主队':<25} {'客队':<25} {'预测':^10} {'置信':^6} {'主胜%':>6} {'平局%':>6} {'客胜%':>6} {'可靠性':>6}")
            print(f"  {'─'*12} {'─'*25} {'─'*25} {'─'*10} {'─'*6} {'─'*6} {'─'*6} {'─'*6} {'─'*6}")

        result_cn = {
            "HOME_WIN": "主胜 ✅",
            "DRAW": "平局 🟡",
            "AWAY_WIN": "客胜 ❌",
            "ABORTED": "熔断 ⚠️",
        }.get(s["predictedResult"], s["predictedResult"])

        conf_cn = {
            "HIGH": "高",
            "MEDIUM": "中",
            "LOW": "低",
            "NONE": "无",
        }.get(s["confidence"], s["confidence"])

        print(
            f"  {s['date']:<12} {s['home']:<25} {s['away']:<25} "
            f"{result_cn:^10} {conf_cn:^6} "
            f"{s['homeWinProb']:>5.1f}% {s['drawProb']:>5.1f}% {s['awayWinProb']:>5.1f}% "
            f"{s['dataReliabilityScore']:>5}"
        )

    print(f"\n{'=' * 130}")


def main():
    matches = generate_matches()
    print(f"[INFO] 生成 {len(matches)} 场小组赛赛程")
    print(f"[INFO] API 地址: {API_BASE}/api/predict")
    print(f"[INFO] 开始批量预测...\n")

    all_results = []
    summaries = []
    errors = 0

    for i, match in enumerate(matches, 1):
        label = f"[{i:>2}/{len(matches)}] Group {match['group']} MD{match['matchday']}: {match['home']} vs {match['away']}"
        print(f"  {label} ... ", end="", flush=True)

        payload = build_payload(match)
        result = call_predict(payload)

        if "error" in result and not result.get("verdict"):
            print(f"❌ Error: {result.get('error', 'unknown')}")
            errors += 1
            all_results.append({"match": match, "payload": payload, "error": result})
            continue

        summary = extract_summary(match, result)
        summaries.append(summary)
        all_results.append({"match": match, "payload": payload, "result": result, "summary": summary})

        result_label = summary["predictedResult"]
        prob_str = f"H:{summary['homeWinProb']}% D:{summary['drawProb']}% A:{summary['awayWinProb']}%"
        print(f"✅ {result_label} ({summary['confidence']}) | {prob_str}")

        # Small delay to not overwhelm the server
        time.sleep(0.15)

    # Save full results
    output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_path = os.path.join(output_dir, f"wc2026_group_stage_predictions_{timestamp}.json")
    summary_path = os.path.join(output_dir, f"wc2026_group_stage_summary_{timestamp}.json")

    # Save detailed results (without full payloads to keep file size manageable)
    save_results = []
    for r in all_results:
        save_item = {"match": r["match"]}
        if "summary" in r:
            save_item["summary"] = r["summary"]
        if "result" in r:
            # Save key fields from result
            result = r["result"]
            save_item["prediction"] = {
                "verdict": result.get("verdict"),
                "probabilities": result.get("probabilities"),
                "canonicalProbability": result.get("canonicalProbability"),
                "dataReliability": result.get("dataReliability"),
                "finalRiskNarrative": result.get("finalRiskNarrative"),
                "riskFlags": result.get("riskFlags"),
                "predictionManifest": result.get("predictionManifest"),
                "marketAnalysis": result.get("marketAnalysis"),
                "modelVersion": result.get("modelVersion"),
                "predictionSnapshotId": result.get("predictionSnapshotId"),
            }
        if "error" in r:
            save_item["error"] = r["error"]
        save_results.append(save_item)

    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(save_results, f, ensure_ascii=False, indent=2)
    print(f"\n[INFO] 详细结果已保存: {results_path}")

    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summaries, f, ensure_ascii=False, indent=2)
    print(f"[INFO] 摘要已保存: {summary_path}")

    # Print summary table
    print_summary_table(summaries)

    # Stats
    print(f"\n[统计] 总计: {len(matches)} 场 | 成功: {len(summaries)} | 失败: {errors}")
    if summaries:
        home_wins = sum(1 for s in summaries if s["predictedResult"] == "HOME_WIN")
        draws = sum(1 for s in summaries if s["predictedResult"] == "DRAW")
        away_wins = sum(1 for s in summaries if s["predictedResult"] == "AWAY_WIN")
        high_conf = sum(1 for s in summaries if s["confidence"] == "HIGH")
        med_conf = sum(1 for s in summaries if s["confidence"] == "MEDIUM")
        low_conf = sum(1 for s in summaries if s["confidence"] == "LOW")
        print(f"[统计] 主胜: {home_wins} | 平局: {draws} | 客胜: {away_wins}")
        print(f"[统计] 高置信: {high_conf} | 中置信: {med_conf} | 低置信: {low_conf}")


if __name__ == "__main__":
    main()
