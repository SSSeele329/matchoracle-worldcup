def normalize_player_name(name):
    return str(name or "").strip().lower()


ATTACK_ROLES = {"ATTACKER", "FORWARD", "STRIKER", "CF", "ST", "LW", "RW", "WINGER"}
CREATOR_ROLES = {"CREATOR", "PLAYMAKER", "CAM", "AM", "CM"}
GOALKEEPER_ROLES = {"GOALKEEPER", "GK"}
CENTER_BACK_ROLES = {"CENTER_BACK", "CB", "DEFENDER", "CENTRE_BACK"}


def parse_formation(formation):
    parts = []
    for part in str(formation or "").replace(" ", "").split("-"):
        try:
            parts.append(int(part))
        except ValueError:
            return None
    if len(parts) < 3:
        return None
    return parts


def midfield_count(formation):
    parts = parse_formation(formation)
    if not parts:
        return None
    return sum(parts[1:-1])


def formation_geometry_edge(home_formation, away_formation):
    home_mid = midfield_count(home_formation)
    away_mid = midfield_count(away_formation)
    if home_mid is None or away_mid is None:
        return {
            "impactScore": 0,
            "dataQuality": "LOW",
            "reasoning": "未提供双方有效阵型，阵型几何对位按中性处理。",
        }
    diff = home_mid - away_mid
    impact_score = max(-2.0, min(2.0, diff * 0.7))
    if diff > 0:
        direction = f"主队中场人数 {home_mid} 对 {away_mid}，在站位几何上更容易形成中场覆盖优势。"
    elif diff < 0:
        direction = f"客队中场人数 {away_mid} 对 {home_mid}，在站位几何上更容易形成中场覆盖优势。"
    else:
        direction = f"双方中场人数均为 {home_mid}，阵型几何不形成明显单边优势。"
    return {
        "impactScore": impact_score,
        "dataQuality": "MEDIUM",
        "reasoning": f"预计阵型：主队 {home_formation}，客队 {away_formation}。{direction}",
    }


def normalize_role(value):
    return str(value or "").strip().upper().replace(" ", "_").replace("-", "_")


def player_name(player):
    if isinstance(player, dict):
        return player.get("name")
    return player


def player_tier(player):
    if not isinstance(player, dict):
        return "UNKNOWN"
    return str(player.get("tier") or "UNKNOWN").strip().upper()


def player_role(player):
    if not isinstance(player, dict):
        return "UNKNOWN"
    return normalize_role(player.get("role") or player.get("position"))


def side_expected_players(expected, side):
    keys = [f"{side}KeyPlayers", f"{side}Players", f"{side}ExpectedPlayers"]
    for key in keys:
        players = expected.get(key)
        if players:
            return players
    return []


def side_actual_names(actual, side):
    starters = actual.get(f"{side}Starters") or []
    players = actual.get(f"{side}Players") or []
    names = {normalize_player_name(name) for name in starters if name}
    names.update(normalize_player_name(player_name(player)) for player in players if player_name(player))
    return names


def apply_absence_multiplier(home_multiplier, away_multiplier, side, tier, role):
    if tier == "TIER_3" or tier == "UNKNOWN":
        return home_multiplier, away_multiplier, None

    if role in ATTACK_ROLES:
        multiplier = 0.85 if tier == "TIER_1" else 0.925
        target = side
    elif role in CREATOR_ROLES:
        multiplier = 0.90 if tier == "TIER_1" else 0.95
        target = side
    elif role in GOALKEEPER_ROLES:
        multiplier = 1.15 if tier == "TIER_1" else 1.075
        target = "away" if side == "home" else "home"
    elif role in CENTER_BACK_ROLES:
        multiplier = 1.10 if tier == "TIER_1" else 1.05
        target = "away" if side == "home" else "home"
    else:
        return home_multiplier, away_multiplier, None

    if target == "home":
        home_multiplier *= multiplier
    else:
        away_multiplier *= multiplier
    return home_multiplier, away_multiplier, multiplier


def calculate_lineup_shock(expected=None, actual=None):
    expected = expected or {}
    actual = actual or {}
    if not expected or not actual:
        return {
            "applied": False,
            "homeMultiplier": 1.0,
            "awayMultiplier": 1.0,
            "absences": [],
            "riskFlags": [],
        }

    home_multiplier = 1.0
    away_multiplier = 1.0
    absences = []
    flags = []

    for side in ("home", "away"):
        actual_names = side_actual_names(actual, side)
        if not actual_names:
            continue
        for player in side_expected_players(expected, side):
            name = player_name(player)
            if not name or normalize_player_name(name) in actual_names:
                continue
            tier = player_tier(player)
            role = player_role(player)
            home_multiplier, away_multiplier, applied_multiplier = apply_absence_multiplier(
                home_multiplier,
                away_multiplier,
                side,
                tier,
                role,
            )
            absence = {
                "teamSide": side,
                "name": name,
                "tier": tier,
                "role": role,
                "lambdaMultiplier": applied_multiplier,
            }
            absences.append(absence)
            if applied_multiplier is not None:
                flags.append(f"Lineup Shock：{side} {tier} {role} {name} 未进入官方首发，lambda已按规则重算。")

    home_multiplier = max(0.70, min(1.30, home_multiplier))
    away_multiplier = max(0.70, min(1.30, away_multiplier))
    return {
        "applied": bool(flags),
        "homeMultiplier": round(home_multiplier, 4),
        "awayMultiplier": round(away_multiplier, 4),
        "absences": absences,
        "riskFlags": flags,
    }


def final_lineup_check(expected=None, actual=None):
    expected = expected or {}
    actual = actual or {}
    expected_home = {normalize_player_name(name) for name in (expected.get("homeStarters") or []) if name}
    expected_away = {normalize_player_name(name) for name in (expected.get("awayStarters") or []) if name}
    actual_home = {normalize_player_name(name) for name in (actual.get("homeStarters") or []) if name}
    actual_away = {normalize_player_name(name) for name in (actual.get("awayStarters") or []) if name}

    home_changed = len(expected_home - actual_home) if expected_home and actual_home else 0
    away_changed = len(expected_away - actual_away) if expected_away and actual_away else 0
    home_rate = home_changed / len(expected_home) if expected_home else 0
    away_rate = away_changed / len(expected_away) if expected_away else 0

    expected_home_formation = expected.get("homeFormation")
    actual_home_formation = actual.get("homeFormation")
    expected_away_formation = expected.get("awayFormation")
    actual_away_formation = actual.get("awayFormation")
    home_formation_changed = bool(expected_home_formation and actual_home_formation and expected_home_formation != actual_home_formation)
    away_formation_changed = bool(expected_away_formation and actual_away_formation and expected_away_formation != actual_away_formation)

    max_change_rate = max(home_rate, away_rate)
    confidence_penalty = 0
    flags = []
    if max_change_rate >= 0.35 or home_formation_changed or away_formation_changed:
        confidence_penalty = 18
        flags.append("T-60首发校验发现较大偏差，建议重新刷新预测。")
    elif max_change_rate >= 0.2:
        confidence_penalty = 10
        flags.append("T-60首发校验发现中等轮换偏差，预测置信度下调。")

    lineup_shock = calculate_lineup_shock(expected, actual)
    flags.extend(lineup_shock["riskFlags"])
    if lineup_shock["applied"]:
        confidence_penalty = max(confidence_penalty, 18)

    return {
        "available": bool(expected or actual),
        "homeChangedPlayers": home_changed,
        "awayChangedPlayers": away_changed,
        "homeChangeRate": round(home_rate, 4),
        "awayChangeRate": round(away_rate, 4),
        "homeFormationChanged": home_formation_changed,
        "awayFormationChanged": away_formation_changed,
        "confidencePenalty": confidence_penalty,
        "riskFlags": flags,
        "lineupShock": lineup_shock,
    }
