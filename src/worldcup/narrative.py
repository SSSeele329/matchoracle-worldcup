ACTION_READ_WITH_CAUTION = "READ_WITH_CAUTION"
ACTION_WAIT_FOR_LINEUP = "WAIT_FOR_LINEUP"
ACTION_DATA_INCOMPLETE = "DATA_INCOMPLETE"
ACTION_MARKET_MOVED = "MARKET_MOVED"
ACTION_NO_ACTION = "NO_ACTION"


def _signal(code, headline, action, priority, detail=None):
    return {
        "code": code,
        "headline": headline,
        "userActionHint": action,
        "priority": priority,
        "detail": detail,
    }


def _audit_codes(data_reliability):
    return {
        event.get("code")
        for event in (data_reliability or {}).get("auditEvents", [])
        if event.get("code")
    }


def _market_disagreement_signal(market_analysis, data_reliability):
    if not market_analysis or (data_reliability or {}).get("status") not in {"OK", "WARN"}:
        return None
    alignment = market_analysis.get("temporalAlignment") or {}
    disagreement = market_analysis.get("biggestDisagreement") or {}
    if not alignment.get("divergenceEnabled") or abs(float(disagreement.get("edge") or 0)) < 0.15:
        return None
    return _signal(
        "MARKET_DIVERGENCE",
        "模型与市场概率存在显著分歧，需要先核查信息差来源。",
        ACTION_MARKET_MOVED,
        80,
    )


def _market_moved_signal(market_analysis):
    if not market_analysis:
        return None
    reverse_line_movement = market_analysis.get("reverseLineMovement") or {}
    if not reverse_line_movement.get("detected"):
        return None
    return _signal(
        "MARKET_MOVED",
        "市场赔率移动与公众方向不一致，先复核盘口变化原因。",
        ACTION_MARKET_MOVED,
        70,
    )


def _lineup_signal(lineup_check):
    lineup_check = lineup_check or {}
    if (lineup_check.get("lineupShock") or {}).get("applied"):
        return _signal(
            "LINEUP_SHOCK",
            "官方首发触发 Lineup Shock，本场解释优先看首发突变。",
            ACTION_READ_WITH_CAUTION,
            90,
        )
    if lineup_check.get("confidencePenalty", 0) > 0:
        return _signal(
            "LINEUP_CHANGED",
            "T-60 首发校验发现偏差，预测置信度已降级。",
            ACTION_READ_WITH_CAUTION,
            65,
        )
    return None


def _upset_risk_signal(upset_risk):
    upset_risk = upset_risk or {}
    level = upset_risk.get("upsetRiskLevel")
    if level not in {"MEDIUM", "HIGH"}:
        return None
    priority = 82 if level == "HIGH" else 62
    return _signal(
        "UPSET_RISK",
        upset_risk.get("explanation") or "热门方仍占优，但爆冷风险层提示本场需要降级解读。",
        ACTION_READ_WITH_CAUTION,
        priority,
        detail={
            "level": level,
            "score": upset_risk.get("upsetRiskScore"),
            "triggers": upset_risk.get("riskFlags") or [],
        },
    )


def _reliability_signals(data_reliability):
    data_reliability = data_reliability or {}
    status = data_reliability.get("status")
    audit_codes = _audit_codes(data_reliability)
    if status == "FATAL":
        return [
            _signal(
                "DATA_RELIABILITY_FATAL",
                "关键数据缺失或冲突，赛前 canonical 概率已阻断。",
                ACTION_DATA_INCOMPLETE,
                100,
            )
        ]
    signals = []
    if "EXPECTED_LINEUP_MISSING" in audit_codes:
        signals.append(_signal(
            "WAIT_FOR_LINEUP",
            "T-24 预计首发缺失，首发相关解释需等待更可靠输入。",
            ACTION_WAIT_FOR_LINEUP,
            55,
        ))
    if status == "CRITICAL":
        signals.append(_signal(
            "DATA_RELIABILITY_DROP",
            "数据可靠性为 CRITICAL，预测只能降级解读。",
            ACTION_DATA_INCOMPLETE,
            75,
        ))
    elif status == "WARN" and not signals:
        signals.append(_signal(
            "DATA_RELIABILITY_DROP",
            "部分赛前数据不完整，预测解释需降级解读。",
            ACTION_DATA_INCOMPLETE,
            50,
        ))
    return signals


def _fallback_signal(canonical_probability):
    source = (canonical_probability or {}).get("source") or "RAW_MODEL"
    if source == "MARKET_ALIGNED_CALIBRATED":
        headline = "当前默认概率来自已对齐的 Raw/Market 透明校准。"
    else:
        headline = "当前默认概率来自 Raw Model，风险信号只做解释。"
    return _signal("CANONICAL_PROBABILITY", headline, ACTION_NO_ACTION, 0)


def build_final_risk_narrative(
    data_reliability=None,
    risk_flags=None,
    market_analysis=None,
    lineup_check=None,
    upset_risk=None,
    canonical_probability=None,
):
    signals = []
    signals.extend(_reliability_signals(data_reliability))
    if (data_reliability or {}).get("status") != "FATAL":
        for candidate in (
            _lineup_signal(lineup_check),
            _upset_risk_signal(upset_risk),
            _market_disagreement_signal(market_analysis, data_reliability),
            _market_moved_signal(market_analysis),
        ):
            if candidate:
                signals.append(candidate)

    if not signals:
        signals.append(_fallback_signal(canonical_probability))

    seen = set()
    deduped = []
    for signal in sorted(signals, key=lambda item: (-item["priority"], item["code"])):
        if signal["code"] in seen:
            continue
        seen.add(signal["code"])
        deduped.append(signal)

    primary = deduped[0]
    secondary = deduped[1:3]
    suppressed_codes = [signal["code"] for signal in deduped[3:]]
    used_codes = {primary["code"], *(signal["code"] for signal in secondary)}
    suppressed_codes.extend(
        f"RISK_FLAG_{index}"
        for index, _ in enumerate(risk_flags or [], start=1)
        if index > max(0, 3 - len(used_codes))
    )

    return {
        "primaryDriver": primary["code"],
        "secondaryDrivers": [signal["code"] for signal in secondary],
        "suppressedSignals": suppressed_codes,
        "finalUserHeadline": primary["headline"],
        "userActionHint": primary["userActionHint"],
    }
