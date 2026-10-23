PROBABILITY_KEYS = ("home", "draw", "away")

LOW = "LOW"
MEDIUM = "MEDIUM"
HIGH = "HIGH"


def clamp(value, lower, upper):
    return max(lower, min(upper, value))


def safe_float(value, default=None):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_status(value):
    if not isinstance(value, str):
        return "UNKNOWN"
    return value.strip().upper()


def home_away_probabilities(probabilities):
    probabilities = probabilities or {}
    return {
        "home": safe_float(probabilities.get("home"), 0.0) or 0.0,
        "away": safe_float(probabilities.get("away"), 0.0) or 0.0,
        "draw": safe_float(probabilities.get("draw"), 0.0) or 0.0,
    }


def favorite_side(probabilities):
    probs = home_away_probabilities(probabilities)
    favorite = "home" if probs["home"] >= probs["away"] else "away"
    underdog = "away" if favorite == "home" else "home"
    margin = probs[favorite] - probs[underdog]
    return favorite, underdog, probs[favorite], probs[underdog], margin


def team_label(match, side):
    match = match or {}
    return match.get("homeTeam" if side == "home" else "awayTeam") or side.upper()


def side_value(context, side, field):
    return (context or {}).get(f"{side}{field}")


def side_status(context, side):
    explicit = side_value(context, side, "QualificationStatus")
    if explicit is not None:
        return normalize_status(explicit)
    outcomes = side_value(context, side, "QualificationByOutcome")
    if isinstance(outcomes, dict):
        win = safe_float(outcomes.get("W"), 0.0) or 0.0
        draw = safe_float(outcomes.get("D"), 0.0) or 0.0
        loss = safe_float(outcomes.get("L"), 0.0) or 0.0
        if loss >= 0.85:
            return "ALREADY_QUALIFIED"
        if win <= 0.15 and draw <= 0.15:
            return "ELIMINATED"
        if win - draw >= 0.35:
            return "MUST_WIN"
        if draw - loss >= 0.30:
            return "NEED_DRAW"
    return "UNKNOWN"


def group_round(match, context):
    value = (
        (context or {}).get("groupRound")
        or (context or {}).get("matchday")
        or (match or {}).get("groupRound")
        or (match or {}).get("matchday")
    )
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def side_setpiece_rate(goal_data, side):
    side_goal_data = (goal_data or {}).get(side) or {}
    return safe_float(side_goal_data.get("setpieceRate"), 0.25) or 0.25


def market_favorite_probability(market_analysis, favorite):
    market_probs = (market_analysis or {}).get("probabilities") or {}
    return safe_float(market_probs.get(favorite), 0.0) or 0.0


def public_favorite_share(match_input, favorite):
    public = (match_input or {}).get("publicTicketPercent") or {}
    return safe_float(public.get(favorite), 0.0) or 0.0


def add_trigger(triggers, code, weight, message):
    triggers.append({
        "code": code,
        "weight": round(weight, 4),
        "message": message,
    })


def build_upset_risk(match_input, probabilities, market_analysis=None):
    match_input = match_input or {}
    match = match_input.get("match") or {}
    context = match_input.get("matchContext") or {}
    goal_data = match_input.get("goalData") or {}
    favorite, underdog, favorite_probability, underdog_probability, margin = favorite_side(probabilities)
    favorite_name = team_label(match, favorite)
    underdog_name = team_label(match, underdog)
    clear_favorite = favorite_probability >= 0.48 and margin >= 0.12
    triggers = []

    if not clear_favorite:
        return {
            "upsetRiskLevel": LOW,
            "upsetRiskScore": 0.0,
            "favorite": favorite,
            "favoriteTeam": favorite_name,
            "underdog": underdog,
            "underdogTeam": underdog_name,
            "clearFavorite": False,
            "confidencePenalty": 0,
            "riskFlags": [],
            "triggers": [],
            "explanation": "双方概率差距不足，不属于典型爆冷结构；本场更适合按均势风险解读。",
        }

    add_trigger(
        triggers,
        "CLEAR_FAVORITE_BASELINE",
        0.10 + clamp((margin - 0.12) * 0.4, 0.0, 0.08),
        f"{favorite_name} 是明显热门，热门预期越高，小概率事件被放大时越需要提示风险。",
    )

    favorite_status = side_status(context, favorite)
    underdog_status = side_status(context, underdog)
    favorite_rotation = safe_float(side_value(context, favorite, "RotationRisk"), 0.0) or 0.0
    underdog_must_win = safe_float(side_value(context, underdog, "MustWinPressure"), 0.0) or 0.0
    favorite_motivation = safe_float(side_value(context, favorite, "MotivationScore"), 0.0) or 0.0
    underdog_motivation = safe_float(side_value(context, underdog, "MotivationScore"), 0.0) or 0.0
    path_incentive = safe_float(context.get("pathIncentiveRisk"), 0.0) or 0.0
    mutual_draw = max(
        safe_float(context.get("mutualDrawIncentive"), 0.0) or 0.0,
        safe_float(context.get("matchDrawIncentive"), 0.0) or 0.0,
    )
    card_risk = safe_float(context.get("cardRiskImportance"), 0.0) or 0.0
    round_number = group_round(match, context)

    if favorite_status == "ALREADY_QUALIFIED":
        add_trigger(
            triggers,
            "FAVORITE_ALREADY_QUALIFIED",
            0.18,
            f"{favorite_name} 已接近或已经完成晋级目标，比赛目标可能从赢球最大化转向控风险。",
        )
    if favorite_rotation >= 0.20:
        add_trigger(
            triggers,
            "FAVORITE_ROTATION_RISK",
            clamp(favorite_rotation * 0.24, 0.06, 0.18),
            f"{favorite_name} 轮换风险较高，强弱差距可能被压缩。",
        )
    if underdog_status in {"MUST_WIN", "NEED_DRAW"} or underdog_must_win >= 0.25:
        add_trigger(
            triggers,
            "UNDERDOG_MUST_TAKE_POINTS",
            0.12 + clamp(underdog_must_win * 0.12, 0.0, 0.10),
            f"{underdog_name} 的拿分/争胜动机更清晰，弱队比赛强度可能上修。",
        )
    if underdog_motivation - favorite_motivation >= 1.0:
        add_trigger(
            triggers,
            "MOTIVATION_ASYMMETRY",
            0.10,
            "双方赛制动机存在明显不对称，热门方胜率需要降级解读。",
        )
    if path_incentive >= 0.25:
        add_trigger(
            triggers,
            "PATH_INCENTIVE_RISK",
            clamp(path_incentive * 0.16, 0.05, 0.14),
            "小组排名或淘汰赛路径存在非赢球最大化动机，不能只按实力差距解释。",
        )
    if mutual_draw >= 0.25:
        add_trigger(
            triggers,
            "MUTUAL_DRAW_INCENTIVE",
            clamp(mutual_draw * 0.14, 0.04, 0.12),
            "双方都有接受平局的空间，热门方大胜信心应下调。",
        )
    if round_number == 1:
        add_trigger(
            triggers,
            "FIRST_GROUP_MATCH_VOLATILITY",
            0.05,
            "小组首战准备周期长、热门压力大，冷门波动略高。",
        )
    elif round_number == 3:
        add_trigger(
            triggers,
            "THIRD_GROUP_MATCH_COMPLEXITY",
            0.07,
            "小组第三轮受晋级、净胜球和跨组第三名比较影响，动机结构更复杂。",
        )

    favorite_setpiece = side_setpiece_rate(goal_data, favorite)
    underdog_setpiece = side_setpiece_rate(goal_data, underdog)
    setpiece_gap = underdog_setpiece - favorite_setpiece
    explicit_setpiece_mismatch = safe_float(match_input.get("setpieceMismatch"), None)
    if explicit_setpiece_mismatch is not None:
        setpiece_gap = explicit_setpiece_mismatch if underdog == "home" else -explicit_setpiece_mismatch
    if setpiece_gap >= 0.08:
        add_trigger(
            triggers,
            "SETPIECE_VOLATILITY",
            clamp(setpiece_gap * 0.55, 0.04, 0.12),
            f"{underdog_name} 定位球占比相对更高，短赛制里会放大冷门路径。",
        )
    if card_risk >= 0.30:
        add_trigger(
            triggers,
            "CARD_RISK_IMPORTANCE",
            clamp(card_risk * 0.10, 0.03, 0.08),
            "黄牌/红牌或停赛约束更重要，比赛强度和阵容选择存在额外波动。",
        )

    market_heat = 0.0
    market_favorite = market_favorite_probability(market_analysis, favorite)
    if market_favorite:
        market_heat = max(0.0, market_favorite - favorite_probability)
    public_share = public_favorite_share(match_input, favorite)
    if market_heat >= 0.06 or public_share >= 65:
        add_trigger(
            triggers,
            "MARKET_FAVORITE_HEAT",
            0.08 + clamp(market_heat, 0.0, 0.08) + (0.04 if public_share >= 65 else 0.0),
            "市场或公众预期明显偏热，热门胜率需要结合赔率变化复核。",
        )

    draw_probability = home_away_probabilities(probabilities)["draw"]
    if draw_probability >= 0.285 and favorite_probability < 0.60:
        add_trigger(
            triggers,
            "LOW_SCORE_DRAW_VOLATILITY",
            0.05,
            "平局概率偏高且热门优势未压倒性，低比分路径会增加爆冷/不胜风险。",
        )

    score = round(clamp(sum(trigger["weight"] for trigger in triggers), 0.0, 1.0), 4)
    if score >= 0.55:
        level = HIGH
        penalty = 12
    elif score >= 0.30:
        level = MEDIUM
        penalty = 6
    else:
        level = LOW
        penalty = 0

    risk_flags = [trigger["code"] for trigger in triggers if trigger["code"] != "CLEAR_FAVORITE_BASELINE"]
    if level == LOW:
        explanation = f"{favorite_name} 仍是热门，当前没有足够信号说明爆冷风险显著升高。"
    else:
        explanation = (
            f"{favorite_name} 仍是热门，但 {underdog_name} 的爆冷/不败风险升高；"
            "这些信号只降低置信度和解释口径，不直接改写胜平负概率。"
        )

    return {
        "upsetRiskLevel": level,
        "upsetRiskScore": score,
        "favorite": favorite,
        "favoriteTeam": favorite_name,
        "favoriteProbability": round(favorite_probability, 4),
        "underdog": underdog,
        "underdogTeam": underdog_name,
        "underdogProbability": round(underdog_probability, 4),
        "clearFavorite": True,
        "confidencePenalty": penalty,
        "riskFlags": risk_flags,
        "triggers": triggers,
        "explanation": explanation,
    }
