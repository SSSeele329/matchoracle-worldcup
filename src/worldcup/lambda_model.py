from .factors import clamp


def safe_float(value, fallback):
    try:
        if value is None:
            return fallback
        return float(value)
    except (TypeError, ValueError):
        return fallback


def calculate_lambda(attack_team, defend_team, tournament_avg_goals=2.55):
    attack_quality = attack_team.get("f07DataQuality", "LOW")
    base_attack = safe_float(
        attack_team.get("xG_avg") if attack_quality != "LOW" else attack_team.get("actualGoals_avg"),
        1.2,
    )
    defend_xga = safe_float(defend_team.get("xGA_avg"), tournament_avg_goals / 2)
    defense_multiplier = defend_xga / (tournament_avg_goals / 2)
    setpiece_rate = safe_float(attack_team.get("setpieceRate"), 0)
    if setpiece_rate > 0.40:
        setpiece_adjustment = 0.25
    elif setpiece_rate > 0.25:
        setpiece_adjustment = 0.10
    else:
        setpiece_adjustment = 0
    raw_lambda = base_attack * defense_multiplier + setpiece_adjustment
    return round(clamp(raw_lambda, 0.4, 3.0), 3)


def align_lambdas_with_probabilities(home_lambda, away_lambda, probabilities):
    """Keep the score layer directionally consistent with the win/draw layer."""
    total_goals = clamp(home_lambda + away_lambda, 1.4, 4.6)
    target_margin = (probabilities["home"] - probabilities["away"]) * 1.65
    current_margin = home_lambda - away_lambda
    blended_margin = current_margin * 0.45 + target_margin * 0.55
    max_margin = total_goals - 0.8
    blended_margin = clamp(blended_margin, -max_margin, max_margin)

    aligned_home = (total_goals + blended_margin) / 2
    aligned_away = (total_goals - blended_margin) / 2
    return round(clamp(aligned_home, 0.4, 3.0), 3), round(clamp(aligned_away, 0.4, 3.0), 3)


def adjust_lambdas_with_factor_edge(home_lambda, away_lambda, factor_edge):
    """Apply non-goal factors to lambdas while preserving the match goal total."""
    total_goals = clamp(home_lambda + away_lambda, 1.2, 5.2)
    current_margin = home_lambda - away_lambda
    target_margin = factor_edge * 0.75
    blended_margin = current_margin * 0.55 + target_margin * 0.45
    max_margin = total_goals - 0.7
    blended_margin = clamp(blended_margin, -max_margin, max_margin)

    adjusted_home = (total_goals + blended_margin) / 2
    adjusted_away = (total_goals - blended_margin) / 2
    return round(clamp(adjusted_home, 0.35, 3.6), 3), round(clamp(adjusted_away, 0.35, 3.6), 3)


def apply_f05_motivation_context(home_lambda, away_lambda, match_context=None, base_rho=0):
    """Map objective F05 Monte Carlo signals into bounded lambda/rho changes."""
    match_context = match_context or {}
    home_pressure = clamp(safe_float(match_context.get("homeMustWinPressure"), 0.0), 0.0, 1.0)
    away_pressure = clamp(safe_float(match_context.get("awayMustWinPressure"), 0.0), 0.0, 1.0)
    draw_incentive = clamp(safe_float(match_context.get("matchDrawIncentive"), 0.0), 0.0, 1.0)

    adjusted_home = home_lambda
    adjusted_away = away_lambda

    # Must-win teams attack more aggressively, but the same pressure also opens
    # counterattack space for the opponent. Keep the effect small and bounded.
    adjusted_home *= 1 + 0.10 * home_pressure
    adjusted_away *= 1 + 0.07 * home_pressure
    adjusted_away *= 1 + 0.10 * away_pressure
    adjusted_home *= 1 + 0.07 * away_pressure

    if draw_incentive:
        slowdown = 1 - 0.10 * draw_incentive
        adjusted_home *= slowdown
        adjusted_away *= slowdown

    rho = safe_float(base_rho, 0.0)
    rho = clamp(rho - 0.04 * draw_incentive, -0.10, 0.0)
    return (
        round(clamp(adjusted_home, 0.35, 3.6), 3),
        round(clamp(adjusted_away, 0.35, 3.6), 3),
        round(rho, 4),
    )


def apply_lineup_shock(home_lambda, away_lambda, lineup_check_result):
    lineup_shock = (lineup_check_result or {}).get("lineupShock") or {}
    home_multiplier = safe_float(lineup_shock.get("homeMultiplier"), 1.0)
    away_multiplier = safe_float(lineup_shock.get("awayMultiplier"), 1.0)
    return (
        round(clamp(home_lambda * home_multiplier, 0.35, 3.6), 3),
        round(clamp(away_lambda * away_multiplier, 0.35, 3.6), 3),
    )
