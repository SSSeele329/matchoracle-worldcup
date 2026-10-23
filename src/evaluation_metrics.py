import math


RESULT_TO_KEY = {
    "HOME_WIN": "home",
    "DRAW": "draw",
    "AWAY_WIN": "away",
}


def probability_for_result(probabilities, result):
    return float(probabilities.get(RESULT_TO_KEY[result], 0))


def brier_score(probabilities, actual_result):
    score = 0
    for result, key in RESULT_TO_KEY.items():
        target = 1 if result == actual_result else 0
        score += (float(probabilities.get(key, 0)) - target) ** 2
    return score


def log_loss(probabilities, actual_result, epsilon=1e-15):
    probability = min(1 - epsilon, max(epsilon, probability_for_result(probabilities, actual_result)))
    return -math.log(probability)


def predicted_result_from_probabilities(probabilities):
    key = max(("home", "draw", "away"), key=lambda item: probabilities.get(item, 0))
    return {"home": "HOME_WIN", "draw": "DRAW", "away": "AWAY_WIN"}[key]


def summarize_probability_metrics(rows, probabilities_key="probabilities"):
    if not rows:
        return {"brierScore": 0, "logLoss": 0}
    brier = sum(brier_score(row[probabilities_key], row["actualResult"]) for row in rows) / len(rows)
    loss = sum(log_loss(row[probabilities_key], row["actualResult"]) for row in rows) / len(rows)
    return {
        "brierScore": round(brier, 4),
        "logLoss": round(loss, 4),
    }


def draw_diagnostics(rows, probabilities_key="probabilities"):
    if not rows:
        return {
            "matches": 0,
            "predictedDraws": 0,
            "predictedDrawRate": 0,
            "actualDraws": 0,
            "actualDrawRate": 0,
            "averageDrawProbability": 0,
            "actualDrawAverageProbability": 0,
        }
    predicted_draws = sum(
        1
        for row in rows
        if row.get("predictedResult", predicted_result_from_probabilities(row[probabilities_key])) == "DRAW"
    )
    actual_draw_rows = [row for row in rows if row["actualResult"] == "DRAW"]
    average_draw_probability = sum(float(row[probabilities_key].get("draw", 0)) for row in rows) / len(rows)
    actual_draw_average_probability = (
        sum(float(row[probabilities_key].get("draw", 0)) for row in actual_draw_rows) / len(actual_draw_rows)
        if actual_draw_rows
        else 0
    )
    return {
        "matches": len(rows),
        "predictedDraws": predicted_draws,
        "predictedDrawRate": round(predicted_draws / len(rows), 4),
        "actualDraws": len(actual_draw_rows),
        "actualDrawRate": round(len(actual_draw_rows) / len(rows), 4),
        "averageDrawProbability": round(average_draw_probability, 4),
        "actualDrawAverageProbability": round(actual_draw_average_probability, 4),
    }


def calibration_buckets(rows, bucket_size=0.1, probabilities_key="probabilities"):
    buckets = {}
    for row in rows:
        probabilities = row[probabilities_key]
        predicted_result = predicted_result_from_probabilities(probabilities)
        confidence = max(probabilities.values())
        bucket_floor = math.floor(confidence / bucket_size) * bucket_size
        bucket_label = f"{bucket_floor:.1f}-{min(1.0, bucket_floor + bucket_size):.1f}"
        bucket = buckets.setdefault(bucket_label, {
            "bucket": bucket_label,
            "matches": 0,
            "confidenceSum": 0,
            "hits": 0,
        })
        bucket["matches"] += 1
        bucket["confidenceSum"] += confidence
        if predicted_result == row["actualResult"]:
            bucket["hits"] += 1

    results = []
    for label in sorted(buckets):
        bucket = buckets[label]
        average_confidence = bucket["confidenceSum"] / bucket["matches"]
        observed_accuracy = bucket["hits"] / bucket["matches"]
        results.append({
            "bucket": label,
            "matches": bucket["matches"],
            "averageConfidence": round(average_confidence, 4),
            "observedAccuracy": round(observed_accuracy, 4),
            "calibrationError": round(abs(average_confidence - observed_accuracy), 4),
        })
    return results


def summarize_baseline(rows, baseline_key):
    baseline_rows = [
        {
            **row,
            "probabilities": row["baselines"][baseline_key]["probabilities"],
            "predictedResult": row["baselines"][baseline_key]["predictedResult"],
        }
        for row in rows
        if row.get("baselines") and baseline_key in row["baselines"]
    ]
    if not baseline_rows:
        return {
            "matches": 0,
            "resultAccuracy": 0,
            "brierScore": 0,
            "logLoss": 0,
        }
    result_hits = sum(1 for row in baseline_rows if row["predictedResult"] == row["actualResult"])
    metrics = summarize_probability_metrics(baseline_rows)
    return {
        "matches": len(baseline_rows),
        "resultAccuracy": round(result_hits / len(baseline_rows), 4),
        **metrics,
    }


def compare_with_baselines(rows):
    model_metrics = summarize_probability_metrics(rows)
    return {
        "model": model_metrics,
        "simpleFavorite": summarize_baseline(rows, "simpleFavorite"),
        "eloRank": summarize_baseline(rows, "eloRank"),
        "calibrationBuckets": calibration_buckets(rows),
        "drawDiagnostics": draw_diagnostics(rows),
    }
