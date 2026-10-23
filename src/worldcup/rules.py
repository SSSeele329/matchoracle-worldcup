GROUP_STAGE = "GROUP_STAGE"
ROUND_OF_32 = "ROUND_OF_32"
ROUND_OF_16 = "ROUND_OF_16"
QUARTER_FINAL = "QUARTER_FINAL"
SEMI_FINAL = "SEMI_FINAL"
THIRD_PLACE = "THIRD_PLACE"
FINAL = "FINAL"

KNOCKOUT_STAGES = {
    ROUND_OF_32,
    ROUND_OF_16,
    QUARTER_FINAL,
    SEMI_FINAL,
    THIRD_PLACE,
    FINAL,
    "KNOCKOUT",
    "SEMI_AND_FINAL",
}

STAGE_ALIASES = {
    "GROUP": GROUP_STAGE,
    "GROUPS": GROUP_STAGE,
    "GROUP_STAGE": GROUP_STAGE,
    "ROUND_OF_32": ROUND_OF_32,
    "R32": ROUND_OF_32,
    "1/16": ROUND_OF_32,
    "ROUND_OF_16": ROUND_OF_16,
    "R16": ROUND_OF_16,
    "1/8": ROUND_OF_16,
    "QUARTER_FINAL": QUARTER_FINAL,
    "QUARTER": QUARTER_FINAL,
    "QF": QUARTER_FINAL,
    "1/4": QUARTER_FINAL,
    "SEMI_FINAL": SEMI_FINAL,
    "SEMIFINAL": SEMI_FINAL,
    "SF": SEMI_FINAL,
    "FINAL": FINAL,
    "THIRD_PLACE": THIRD_PLACE,
    "KNOCKOUT": ROUND_OF_32,
    "SEMI_AND_FINAL": SEMI_FINAL,
}

STAGE_LABELS = {
    GROUP_STAGE: "小组赛",
    ROUND_OF_32: "1/16决赛 / Round of 32",
    ROUND_OF_16: "1/8决赛 / Round of 16",
    QUARTER_FINAL: "1/4决赛",
    SEMI_FINAL: "半决赛",
    THIRD_PLACE: "三四名决赛",
    FINAL: "决赛",
}


def normalize_stage(stage):
    return STAGE_ALIASES.get(str(stage or GROUP_STAGE).upper(), GROUP_STAGE)


def is_knockout_stage(stage):
    return normalize_stage(stage) in KNOCKOUT_STAGES


def get_competition_rules(stage):
    normalized = normalize_stage(stage)
    knockout = is_knockout_stage(normalized)
    if not knockout:
        return {
            "stage": normalized,
            "stageLabel": STAGE_LABELS[normalized],
            "stageType": "GROUP",
            "modelOutcomeType": "REGULAR_TIME_1X2",
            "competitionOutcomeType": "GROUP_POINTS",
            "regularTimeDrawAllowed": True,
            "advancementRequiresWinner": False,
            "extraTime": False,
            "penalties": False,
            "scoreStorageRule": "Store the 90-minute score as the match score for 1X2 calibration.",
            "explanation": "小组赛按90分钟胜平负记录赛果，胜3分、平1分、负0分。",
        }
    return {
        "stage": normalized,
        "stageLabel": STAGE_LABELS[normalized],
        "stageType": "KNOCKOUT",
        "modelOutcomeType": "REGULAR_TIME_1X2",
        "competitionOutcomeType": "ADVANCEMENT_WINNER",
        "regularTimeDrawAllowed": True,
        "advancementRequiresWinner": True,
        "extraTime": True,
        "extraTimePeriods": {"periods": 2, "minutesEach": 15},
        "penalties": True,
        "scoreStorageRule": "For 1X2 calibration and betting-style result checks, store the 90-minute score. Do not replace it with after-extra-time or penalty winner score.",
        "explanation": "淘汰赛赛制层面必须决出晋级者；模型/赔率层面仍先预测90分钟胜平负。90分钟打平进入30分钟加时，加时仍平则点球大战。",
    }
