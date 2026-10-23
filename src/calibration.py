import json
import math
import os
from collections import Counter

from .evaluation_metrics import compare_with_baselines
from .worldcup import WorldCupPredictor
from .worldcup.factors import clamp
from .worldcup.historical_features import (
    DEFAULT_RESULTS_PATH,
    build_match_prematch_features,
    load_international_results,
    profile_to_goal_data,
)
from .worldcup.tournament_context import build_tournament_context

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CALIBRATION_DIR = os.path.join(PROJECT_ROOT, "data", "calibration")
REPORTS_DIR = os.path.join(PROJECT_ROOT, "reports")
DEFAULT_WC2022_METRICS_REPORT = os.path.join(REPORTS_DIR, "wc2022_probability_metrics.md")


def load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def actual_result(score):
    if score["home"] > score["away"]:
        return "HOME_WIN"
    if score["home"] < score["away"]:
        return "AWAY_WIN"
    return "DRAW"


def regular_time_score(match):
    return match.get("regularTimeScore") or match["actualScore"]


def rank_goal_priors(rank):
    tournament_strength = clamp((65 - float(rank or 65)) / 64, 0, 1)
    return {
        "actualGoals_avg": round(0.95 + tournament_strength * 0.9, 2),
        "xGA_avg": round(1.55 - tournament_strength * 0.65, 2),
        "setpieceRate": 0.25,
    }


def simple_favorite_baseline(home_rank, away_rank):
    if home_rank < away_rank:
        probabilities = {"home": 0.50, "draw": 0.25, "away": 0.25}
    elif away_rank < home_rank:
        probabilities = {"home": 0.25, "draw": 0.25, "away": 0.50}
    else:
        probabilities = {"home": 0.375, "draw": 0.25, "away": 0.375}
    predicted = max(probabilities, key=probabilities.get)
    return {
        "predictedResult": {"home": "HOME_WIN", "draw": "DRAW", "away": "AWAY_WIN"}[predicted],
        "probabilities": probabilities,
    }


def elo_rank_baseline(home_rank, away_rank, draw_probability=0.26):
    home_rank = float(home_rank or 100)
    away_rank = float(away_rank or 100)
    home_edge = away_rank - home_rank
    home_share = 1 / (1 + math.exp(-home_edge * 0.06))
    home = (1 - draw_probability) * home_share
    away = (1 - draw_probability) * (1 - home_share)
    probabilities = {
        "home": round(home, 4),
        "draw": round(draw_probability, 4),
        "away": round(away, 4),
    }
    predicted = max(probabilities, key=probabilities.get)
    return {
        "predictedResult": {"home": "HOME_WIN", "draw": "DRAW", "away": "AWAY_WIN"}[predicted],
        "probabilities": probabilities,
    }


def build_rank_baselines(home_rank, away_rank):
    return {
        "simpleFavorite": simple_favorite_baseline(home_rank, away_rank),
        "eloRank": elo_rank_baseline(home_rank, away_rank),
    }


def load_elo_rank_proxy(year):
    elo = load_json(os.path.join(CALIBRATION_DIR, f"wc{year}_elo_ratings.json"))
    return {team: item["rank"] for team, item in elo["ratings"].items()}


def build_replay_input(match, ranks):
    home = match["homeTeam"]
    away = match["awayTeam"]
    home_rank = ranks.get(home, 100)
    away_rank = ranks.get(away, 100)
    return {
        "matchId": match["matchId"],
        "match": {
            "homeTeam": home,
            "awayTeam": away,
            "stage": match["stage"],
            "datetime": match["date"],
            "venue": match["venue"],
        },
        "teamData": {
            "home": {"fifaRank": home_rank},
            "away": {"fifaRank": away_rank},
        },
        "understatCoverage": {"home": 0, "away": 0},
        "goalData": {
            "home": rank_goal_priors(home_rank),
            "away": rank_goal_priors(away_rank),
        },
        "rankBaselines": build_rank_baselines(home_rank, away_rank),
        "teamStrengthOverridesEnabled": False,
        "historicalReplay": True,
    }


def build_historical_replay_input(match, ranks, history_rows, tournament_matches=None):
    home = match["homeTeam"]
    away = match["awayTeam"]
    home_rank = ranks.get(home, 100)
    away_rank = ranks.get(away, 100)
    profiles = build_match_prematch_features(history_rows, home, away, match["date"])
    home_profile = profiles["home"]
    away_profile = profiles["away"]
    home_goal_data = blend_history_with_rank_prior(home_profile, rank_goal_priors(home_rank))
    away_goal_data = blend_history_with_rank_prior(away_profile, rank_goal_priors(away_rank))
    tournament_context = build_tournament_context(tournament_matches or [], match)
    tournament_context["matchContext"]["scale"] = 0
    tournament_context["restData"]["scale"] = 0
    return {
        "matchId": match["matchId"],
        "match": {
            "homeTeam": home,
            "awayTeam": away,
            "stage": match["stage"],
            "datetime": match["date"],
            "venue": match["venue"],
        },
        "teamData": {
            "home": {
                "fifaRank": home_rank,
                "recentFormScore": home_profile["recentFormScore"],
            },
            "away": {
                "fifaRank": away_rank,
                "recentFormScore": away_profile["recentFormScore"],
            },
        },
        "matchContext": tournament_context["matchContext"],
        "restData": tournament_context["restData"],
        "understatCoverage": {
            "home": home_profile["matchesUsed"],
            "away": away_profile["matchesUsed"],
        },
        "goalData": {
            "home": home_goal_data,
            "away": away_goal_data,
        },
        "rankBaselines": build_rank_baselines(home_rank, away_rank),
        "lambdaScale": 1.4,
        "drawAdjustmentRho": -0.02,
        "prematchFeatureSource": profiles["source"],
        "teamStrengthOverridesEnabled": False,
        "historicalReplay": True,
    }


def blend_history_with_rank_prior(profile, rank_prior, history_weight=0.35):
    history_goal_data = profile_to_goal_data(profile)
    attack_weight = {"LOW": 0.15, "MEDIUM": 0.25, "HIGH": history_weight}.get(profile["dataQuality"], 0.2)
    defense_weight = attack_weight * 0.45
    return {
        "actualGoals_avg": round(
            rank_prior["actualGoals_avg"] * (1 - attack_weight)
            + history_goal_data["actualGoals_avg"] * attack_weight,
            3,
        ),
        "xGA_avg": round(
            max(
                0.78,
                rank_prior["xGA_avg"] * (1 - defense_weight)
                + history_goal_data["xGA_avg"] * defense_weight,
            ),
            3,
        ),
        "setpieceRate": history_goal_data["setpieceRate"],
        "historicalMatchesUsed": history_goal_data["historicalMatchesUsed"],
        "historyDataQuality": profile["dataQuality"],
        "rankPriorWeight": round(1 - attack_weight, 2),
        "historyWeight": round(attack_weight, 2),
        "defenseHistoryWeight": round(defense_weight, 2),
    }


def summarize_rows(rows):
    total = len(rows)
    result_hits = sum(1 for row in rows if row["predictedResult"] == row["actualResult"])
    top_score_hits = sum(1 for row in rows if row["topScoreHit"])
    predicted_result_distribution = Counter(row["predictedResult"] for row in rows)
    actual_result_distribution = Counter(row["actualResult"] for row in rows)
    predicted_score_distribution = Counter(row["predictedScoreText"] for row in rows)
    max_probabilities = [max(row["probabilities"].values()) for row in rows]
    baseline_comparison = compare_with_baselines(rows)
    return {
        "matches": total,
        "resultHits": result_hits,
        "resultAccuracy": round(result_hits / total, 4) if total else 0,
        "top5ScoreHits": top_score_hits,
        "top5ScoreCoverage": round(top_score_hits / total, 4) if total else 0,
        "actualResultDistribution": dict(actual_result_distribution),
        "predictedResultDistribution": dict(predicted_result_distribution),
        "predictedScoreDistribution": dict(predicted_score_distribution),
        "maxProbabilityRange": {
            "min": round(min(max_probabilities), 4) if max_probabilities else 0,
            "max": round(max(max_probabilities), 4) if max_probabilities else 0,
        },
        "probabilityMetrics": baseline_comparison["model"],
        "baselineComparison": baseline_comparison,
    }


def run_worldcup_backtest(year, mode="historical"):
    match_files = {
        2002: "wc2002_matches_openfootball.json",
        2006: "wc2006_matches_openfootball.json",
        2010: "wc2010_matches_openfootball.json",
        2014: "wc2014_matches_openfootball.json",
        2018: "wc2018_matches_openfootball.json",
        2022: "wc2022_matches_openfootball.json",
    }
    matches = load_json(os.path.join(CALIBRATION_DIR, match_files[year]))
    ranks = load_elo_rank_proxy(year)
    if mode == "legacy" and year == 2022:
        ranks = load_json(os.path.join(CALIBRATION_DIR, "wc2022_fifa_ranks.json"))
    history_rows = load_international_results(DEFAULT_RESULTS_PATH)
    predictor = WorldCupPredictor()
    rows = []

    for match in matches:
        if mode == "historical":
            prediction_input = build_historical_replay_input(match, ranks, history_rows, matches)
        else:
            prediction_input = build_replay_input(match, ranks)
        prediction = predictor.predict(prediction_input)
        score = regular_time_score(match)
        actual = actual_result(score)
        top_scores = [item["score"] for item in prediction["scorePrediction"]["topScenarios"]]
        actual_score_text = f"{score['home']}-{score['away']}"
        predicted_score = prediction["scorePrediction"]["predicted"]
        rows.append({
            "matchId": match["matchId"],
            "match": f"{match['homeTeam']} vs {match['awayTeam']}",
            "stage": match["stage"],
            "predictedResult": prediction["verdict"]["result"],
            "actualResult": actual,
            "probabilities": prediction["probabilities"],
            "predictedScore": predicted_score,
            "predictedScoreText": f"{predicted_score['home']}-{predicted_score['away']}",
            "actualScore": score,
            "actualScoreText": actual_score_text,
            "topScoreHit": actual_score_text in top_scores,
            "confidence": prediction["verdict"]["confidence"],
            "confidenceScore": prediction["verdict"]["confidenceScore"],
            "homeLambda": prediction["scorePrediction"]["homeLambda"],
            "awayLambda": prediction["scorePrediction"]["awayLambda"],
            "baselines": prediction_input.get("rankBaselines", {}),
        })

    return {
        "year": year,
        "mode": mode,
        "summary": summarize_rows(rows),
        "rows": rows,
    }


def run_split_backtest(mode="historical"):
    reports = [run_worldcup_backtest(year, mode=mode) for year in (2014, 2018, 2022)]
    calibration_rows = reports[0]["rows"] + reports[1]["rows"]
    return {
        "mode": mode,
        "calibrationYears": [2014, 2018],
        "blindTestYear": 2022,
        "calibrationSummary": summarize_rows(calibration_rows),
        "blindTestSummary": reports[2]["summary"],
        "yearReports": reports,
    }


def run_wc2022_calibration():
    matches = load_json(os.path.join(CALIBRATION_DIR, "wc2022_matches.json"))
    ranks = load_json(os.path.join(CALIBRATION_DIR, "wc2022_fifa_ranks.json"))
    predictor = WorldCupPredictor()
    rows = []

    for match in matches:
        prediction_input = build_replay_input(match, ranks)
        prediction = predictor.predict(prediction_input)
        score = regular_time_score(match)
        actual = actual_result(score)
        top_scores = [item["score"] for item in prediction["scorePrediction"]["topScenarios"]]
        actual_score_text = f"{score['home']}-{score['away']}"
        rows.append({
            "matchId": match["matchId"],
            "match": f"{match['homeTeam']} vs {match['awayTeam']}",
            "stage": match["stage"],
            "predictedResult": prediction["verdict"]["result"],
            "actualResult": actual,
            "probabilities": prediction["probabilities"],
            "predictedScore": prediction["scorePrediction"]["predicted"],
            "actualScore": score,
            "rawRecordedScore": match["actualScore"],
            "topScoreHit": actual_score_text in top_scores,
            "confidence": prediction["verdict"]["confidence"],
            "confidenceScore": prediction["verdict"]["confidenceScore"],
            "baselines": prediction_input.get("rankBaselines", {}),
        })

    total = len(rows)
    result_hits = sum(1 for row in rows if row["predictedResult"] == row["actualResult"])
    top_score_hits = sum(1 for row in rows if row["topScoreHit"])
    group_rows = [row for row in rows if row["stage"] == "GROUP_STAGE"]
    actual_group_draw_rate = sum(1 for row in group_rows if row["actualResult"] == "DRAW") / len(group_rows)
    predicted_group_draw_rate = sum(row["probabilities"]["draw"] for row in group_rows) / len(group_rows)
    high_conf_wrong = [
        row for row in rows
        if row["confidence"] == "HIGH" and row["predictedResult"] != row["actualResult"]
    ]
    predicted_result_distribution = Counter(row["predictedResult"] for row in rows)
    predicted_score_distribution = Counter(
        f"{row['predictedScore']['home']}-{row['predictedScore']['away']}" for row in rows
    )
    max_probabilities = [max(row["probabilities"].values()) for row in rows]
    baseline_comparison = compare_with_baselines(rows)
    biggest_overconfidence = sorted(
        [
            row for row in rows
            if max(row["probabilities"].values()) >= 0.65 and row["predictedResult"] != row["actualResult"]
        ],
        key=lambda row: max(row["probabilities"].values()),
        reverse=True,
    )[:8]

    recommendations = []
    draw_gap = actual_group_draw_rate - predicted_group_draw_rate
    if draw_gap > 0.04:
        recommendations.append(f"小组赛平局预测偏低约 {draw_gap:.1%}，建议上调基础平局概率或增强F05赛制与晋级压力因子。")
    if len(high_conf_wrong) > 6:
        recommendations.append(f"HIGH置信度错误 {len(high_conf_wrong)} 场，建议提高低质量数据和riskFlags的扣分。")
    if top_score_hits / total < 0.30:
        recommendations.append("Top5比分覆盖率低于30%，建议校准λ默认值或扩大比分层输入数据。")
    if not recommendations:
        recommendations.append("当前基线没有触发强制调参建议；接入赔率、近况和AI因子后再复盘。")

    return {
        "summary": {
            "matches": total,
            "resultAccuracy": round(result_hits / total, 4),
            "top5ScoreCoverage": round(top_score_hits / total, 4),
            "groupActualDrawRate": round(actual_group_draw_rate, 4),
            "groupPredictedDrawRate": round(predicted_group_draw_rate, 4),
            "highConfidenceWrong": len(high_conf_wrong),
            "predictedResultDistribution": dict(predicted_result_distribution),
            "predictedScoreDistribution": dict(predicted_score_distribution),
            "maxProbabilityRange": {
                "min": round(min(max_probabilities), 4),
                "max": round(max(max_probabilities), 4),
            },
            "probabilityMetrics": baseline_comparison["model"],
            "baselineComparison": baseline_comparison,
        },
        "recommendations": recommendations,
        "biggestOverconfidence": biggest_overconfidence,
        "rows": rows,
    }


def _format_pct(value):
    return f"{float(value) * 100:.2f}%"


def _format_metric(value):
    return f"{float(value):.4f}"


def _baseline_metric(summary, baseline_name, metric_name):
    return summary.get("baselineComparison", {}).get(baseline_name, {}).get(metric_name, 0)


def _probability_quality_interpretation(summary):
    metrics = summary["probabilityMetrics"]
    simple_brier = _baseline_metric(summary, "simpleFavorite", "brierScore")
    simple_loss = _baseline_metric(summary, "simpleFavorite", "logLoss")
    lines = [
        "- MatchOracle is slightly ahead on headline 1X2 accuracy."
        if summary["resultAccuracy"] > _baseline_metric(summary, "simpleFavorite", "resultAccuracy")
        else "- MatchOracle is not ahead of Simple Favorite on headline 1X2 accuracy.",
    ]
    if metrics["brierScore"] < simple_brier and metrics["logLoss"] < simple_loss:
        lines.append("- MatchOracle is better than the Simple Favorite baseline on both Brier Score and Log Loss.")
    else:
        lines.append("- MatchOracle is not yet better than the Simple Favorite baseline on Brier Score or Log Loss.")
    lines.extend([
        "- This means the current model can pick outcomes reasonably often, but its probability calibration still needs work.",
        "- This is exactly why P0 requires Brier, Log Loss, calibration buckets, and baseline comparison instead of only reporting accuracy.",
    ])
    return lines


def render_wc2022_probability_metrics_markdown(report):
    summary = report["summary"]
    metrics = summary["probabilityMetrics"]
    simple = summary["baselineComparison"]["simpleFavorite"]
    elo = summary["baselineComparison"]["eloRank"]
    lines = [
        "# 2022 World Cup Probability Metrics",
        "",
        "Generated from the current `V4-P0` 2022 rank/replay calibration pipeline.",
        "",
        "Scope:",
        "",
        f"- {summary['matches']} matches from the 2022 World Cup.",
        "- 90-minute result labels only.",
        "- This is not the full rolling-origin historical-feature validation report.",
        "- No historical correct-score odds are included in this report.",
        "- Baselines are intentionally simple and transparent, not optimized market models.",
        "",
        "## Summary",
        "",
        "| Metric | MatchOracle | Simple Favorite | Elo Rank Baseline |",
        "|---|---:|---:|---:|",
        (
            "| 1X2 Accuracy | {model} | {simple} | {elo} |".format(
                model=_format_pct(summary["resultAccuracy"]),
                simple=_format_pct(simple["resultAccuracy"]),
                elo=_format_pct(elo["resultAccuracy"]),
            )
        ),
        (
            "| Brier Score | {model} | {simple} | {elo} |".format(
                model=_format_metric(metrics["brierScore"]),
                simple=_format_metric(simple["brierScore"]),
                elo=_format_metric(elo["brierScore"]),
            )
        ),
        (
            "| Log Loss | {model} | {simple} | {elo} |".format(
                model=_format_metric(metrics["logLoss"]),
                simple=_format_metric(simple["logLoss"]),
                elo=_format_metric(elo["logLoss"]),
            )
        ),
        "",
        "Interpretation:",
        "",
        *_probability_quality_interpretation(summary),
        "",
        "## Calibration Buckets",
        "",
        "| Confidence Bucket | Matches | Average Confidence | Observed Accuracy | Calibration Error |",
        "|---|---:|---:|---:|---:|",
    ]
    for bucket in summary["baselineComparison"]["calibrationBuckets"]:
        lines.append(
            "| {bucket} | {matches} | {confidence} | {observed} | {error} |".format(
                bucket=bucket["bucket"],
                matches=bucket["matches"],
                confidence=_format_pct(bucket["averageConfidence"]),
                observed=_format_pct(bucket["observedAccuracy"]),
                error=_format_pct(bucket["calibrationError"]),
            )
        )
    lines.extend([
        "",
        "## Baseline Definitions",
        "",
        "- `Simple Favorite`: picks the better-ranked side with fixed probabilities: favorite 50%, draw 25%, underdog 25%.",
        "- `Elo Rank Baseline`: converts rank difference into home/away share with a fixed 26% draw prior.",
        "",
        "These baselines are not tuned for profit or betting. They are sanity checks for whether the model adds probability value beyond simple ranking logic.",
        "",
    ])
    return "\n".join(lines)


def write_wc2022_probability_metrics_report(report=None, path=DEFAULT_WC2022_METRICS_REPORT):
    report = report or run_wc2022_calibration()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(render_wc2022_probability_metrics_markdown(report))
    return path
