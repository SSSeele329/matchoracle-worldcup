MARKET_ALIGNED_RAW_WEIGHT = 0.65
MARKET_ALIGNED_MARKET_WEIGHT = 0.35
MARKET_ALIGNED_MAX_OUTCOME_SHIFT = 0.08
PROBABILITY_KEYS = ("home", "draw", "away")


def safe_decimal(value):
    try:
        if value is None or value == "":
            return None
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if value > 1 else None


def normalize_probabilities(probabilities):
    probabilities = probabilities or {}
    cleaned = {}
    for key in PROBABILITY_KEYS:
        try:
            cleaned[key] = max(0.0, float(probabilities.get(key, 0)))
        except (TypeError, ValueError):
            cleaned[key] = 0.0
    total = sum(cleaned.values())
    if total <= 0:
        return None
    return {key: cleaned[key] / total for key in PROBABILITY_KEYS}


def rounded_probabilities(probabilities):
    normalized = normalize_probabilities(probabilities)
    if not normalized:
        return None
    rounded = {key: round(normalized[key], 4) for key in PROBABILITY_KEYS}
    drift = round(1.0 - sum(rounded.values()), 4)
    if drift:
        top_key = max(PROBABILITY_KEYS, key=lambda key: rounded[key])
        rounded[top_key] = round(rounded[top_key] + drift, 4)
    return rounded


def bounded_market_blend(raw_probabilities, market_probabilities):
    raw = normalize_probabilities(raw_probabilities)
    market = normalize_probabilities(market_probabilities)
    if not raw or not market:
        return None
    blended = {}
    for key in PROBABILITY_KEYS:
        target = raw[key] * MARKET_ALIGNED_RAW_WEIGHT + market[key] * MARKET_ALIGNED_MARKET_WEIGHT
        delta = max(
            -MARKET_ALIGNED_MAX_OUTCOME_SHIFT,
            min(MARKET_ALIGNED_MAX_OUTCOME_SHIFT, target - raw[key]),
        )
        blended[key] = raw[key] + delta
    return rounded_probabilities(blended)


def build_market_aligned_calibrated_probability(raw_probabilities, market_analysis):
    if not market_analysis:
        return {
            "status": "UNAVAILABLE",
            "source": "RAW_MODEL",
            "probabilities": None,
            "reason": "Market odds are unavailable; canonical probability falls back to Raw Model.",
        }
    alignment = market_analysis.get("temporalAlignment") or {}
    if not alignment.get("divergenceEnabled"):
        return {
            "status": "UNAVAILABLE",
            "source": "RAW_MODEL",
            "probabilities": None,
            "reason": f"Market odds are not temporally aligned ({alignment.get('reason', 'UNKNOWN')}); canonical probability falls back to Raw Model.",
            "temporalAlignment": alignment,
        }
    probabilities = bounded_market_blend(raw_probabilities, market_analysis.get("probabilities"))
    if not probabilities:
        return {
            "status": "UNAVAILABLE",
            "source": "RAW_MODEL",
            "probabilities": None,
            "reason": "Market probabilities are invalid; canonical probability falls back to Raw Model.",
            "temporalAlignment": alignment,
        }
    return {
        "status": "ACTIVE",
        "source": "MARKET_ALIGNED_CALIBRATED",
        "probabilities": probabilities,
        "reason": "Market odds are temporally aligned; canonical probability uses a transparent bounded blend of Raw Model and de-vigged market probabilities.",
        "temporalAlignment": alignment,
        "calibration": {
            "method": "bounded_raw_market_blend",
            "rawModelWeight": MARKET_ALIGNED_RAW_WEIGHT,
            "marketWeight": MARKET_ALIGNED_MARKET_WEIGHT,
            "maxOutcomeShift": MARKET_ALIGNED_MAX_OUTCOME_SHIFT,
            "marketRole": "BASELINE_NOT_BLACK_BOX_REPLACEMENT",
        },
        "components": {
            "rawModel": rounded_probabilities(raw_probabilities),
            "market": rounded_probabilities(market_analysis.get("probabilities")),
        },
    }


def devig_decimal_odds(decimal_odds):
    odds = {
        "home": safe_decimal(decimal_odds.get("home")),
        "draw": safe_decimal(decimal_odds.get("draw")),
        "away": safe_decimal(decimal_odds.get("away")),
    }
    if not all(odds.values()):
        return None
    raw = {key: 1 / value for key, value in odds.items()}
    total = sum(raw.values())
    return {
        "odds": odds,
        "rawImplied": {key: round(value, 4) for key, value in raw.items()},
        "overround": round(total - 1, 4),
        "probabilities": {key: round(value / total, 4) for key, value in raw.items()},
    }


def calculate_ev(model_probabilities, decimal_odds):
    results = {}
    for key in ("home", "draw", "away"):
        probability = float(model_probabilities.get(key, 0))
        odds = safe_decimal(decimal_odds.get(key))
        if odds is None:
            continue
        ev = probability * odds - 1
        if ev >= 0.08:
            rating = "VALUE"
        elif ev >= 0.02:
            rating = "LEAN_VALUE"
        elif ev > -0.02:
            rating = "FAIR"
        else:
            rating = "NO_VALUE"
        results[key] = {
            "modelProbability": round(probability, 4),
            "odds": odds,
            "ev": round(ev, 4),
            "evPercent": round(ev * 100, 2),
            "rating": rating,
        }
    return results


def calculate_line_movement(opening_odds, current_odds):
    opening = devig_decimal_odds(opening_odds or {})
    current = devig_decimal_odds(current_odds or {})
    if not opening or not current:
        return None
    movement = {}
    for key in ("home", "draw", "away"):
        movement[key] = {
            "openingOdds": opening["odds"][key],
            "currentOdds": current["odds"][key],
            "oddsDelta": round(current["odds"][key] - opening["odds"][key], 4),
            "openingProbability": opening["probabilities"][key],
            "currentProbability": current["probabilities"][key],
            "probabilityDelta": round(current["probabilities"][key] - opening["probabilities"][key], 4),
        }
    strongest_key = max(movement, key=lambda item: abs(movement[item]["probabilityDelta"]))
    return {
        "openingProbabilities": opening["probabilities"],
        "currentProbabilities": current["probabilities"],
        "movement": movement,
        "strongestMove": {"outcome": strongest_key, **movement[strongest_key]},
    }


def detect_reverse_line_movement(line_movement, public_ticket_percent):
    if not line_movement or not public_ticket_percent:
        return None
    valid = {
        key: float(public_ticket_percent.get(key, 0))
        for key in ("home", "draw", "away")
        if public_ticket_percent.get(key) is not None
    }
    if not valid:
        return None
    public_side = max(valid, key=valid.get)
    public_share = valid[public_side]
    if public_share < 65:
        return {
            "detected": False,
            "reason": "公众投注比例未明显集中，暂不判定逆向盘口移动。",
        }
    public_move = line_movement["movement"][public_side]["probabilityDelta"]
    against_sides = [key for key in ("home", "draw", "away") if key != public_side]
    sharp_side = max(against_sides, key=lambda key: line_movement["movement"][key]["probabilityDelta"])
    sharp_move = line_movement["movement"][sharp_side]["probabilityDelta"]
    detected = public_move < -0.015 and sharp_move > 0.015
    return {
        "detected": detected,
        "publicSide": public_side,
        "publicShare": public_share,
        "suspectedSharpSide": sharp_side if detected else None,
        "reason": (
            "公众投注高度集中一侧，但市场概率向反方向移动，疑似逆向盘口移动。"
            if detected else
            "未出现明确的公众方向与盘口移动反向信号。"
        ),
    }


def build_market_analysis(model_probabilities, decimal_odds, opening_decimal_odds=None, public_ticket_percent=None):
    market = devig_decimal_odds(decimal_odds or {})
    if not market:
        return None
    value_bets = calculate_ev(model_probabilities, market["odds"])
    edges = {
        key: round(model_probabilities.get(key, 0) - market["probabilities"].get(key, 0), 4)
        for key in ("home", "draw", "away")
    }
    best_key = max(value_bets, key=lambda key: value_bets[key]["ev"])
    biggest_disagreement_key = max(edges, key=lambda key: abs(edges[key]))
    line_movement = calculate_line_movement(opening_decimal_odds, decimal_odds)
    reverse_line_movement = detect_reverse_line_movement(line_movement, public_ticket_percent)
    return {
        **market,
        "edges": edges,
        "valueBets": value_bets,
        "bestValue": {"outcome": best_key, **value_bets[best_key]},
        "biggestDisagreement": {
            "outcome": biggest_disagreement_key,
            "edge": edges[biggest_disagreement_key],
        },
        "lineMovement": line_movement,
        "reverseLineMovement": reverse_line_movement,
    }
