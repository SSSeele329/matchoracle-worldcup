import copy
import os
import re
import time
from datetime import datetime, timezone

from .api_football_adapter import cached_api_football_worldcup_availability
from .football_data_org_adapter import (
    FOOTBALL_DATA_ORG_PROVIDER_ID,
    FootballDataOrgAdapterError,
    fetch_worldcup_structured_facts_payload,
)
from .f05_monte_carlo import apply_score, empty_record, motivation_from_outcome_shares, ranking_for_group
from .factors import clamp
from .historical_features import (
    build_match_prematch_features,
    load_international_results,
    profile_to_goal_data,
)
from .odds_import import import_live_odds_snapshots, list_market_odds_snapshots
from .provider_contracts import parse_iso_timestamp
from .structured_facts_store import list_structured_fact_read_rows
from .the_odds_api_adapter import TheOddsApiError, fetch_the_odds_api_snapshots


TEAM_TRANSLATIONS_ZH = {
    "Argentina": "阿根廷",
    "Algeria": "阿尔及利亚",
    "Australia": "澳大利亚",
    "Austria": "奥地利",
    "Belgium": "比利时",
    "Bosnia-Herzegovina": "波黑",
    "Brazil": "巴西",
    "Canada": "加拿大",
    "Cape Verde Islands": "佛得角",
    "Colombia": "哥伦比亚",
    "Congo DR": "刚果民主共和国",
    "Croatia": "克罗地亚",
    "Curaçao": "库拉索",
    "Czechia": "捷克",
    "Ecuador": "厄瓜多尔",
    "Egypt": "埃及",
    "England": "英格兰",
    "France": "法国",
    "Germany": "德国",
    "Ghana": "加纳",
    "Haiti": "海地",
    "Iran": "伊朗",
    "Iraq": "伊拉克",
    "Ivory Coast": "科特迪瓦",
    "Japan": "日本",
    "Jordan": "约旦",
    "Mexico": "墨西哥",
    "Morocco": "摩洛哥",
    "Netherlands": "荷兰",
    "New Zealand": "新西兰",
    "Norway": "挪威",
    "Panama": "巴拿马",
    "Paraguay": "巴拉圭",
    "Portugal": "葡萄牙",
    "Qatar": "卡塔尔",
    "Saudi Arabia": "沙特阿拉伯",
    "Scotland": "苏格兰",
    "Senegal": "塞内加尔",
    "South Africa": "南非",
    "South Korea": "韩国",
    "Spain": "西班牙",
    "Sweden": "瑞典",
    "Switzerland": "瑞士",
    "Tunisia": "突尼斯",
    "Turkey": "土耳其",
    "United States": "美国",
    "Uruguay": "乌拉圭",
    "USA": "美国",
    "Uzbekistan": "乌兹别克斯坦",
}

TEAM_SHORT_NAMES = {
    "Argentina": "ARG",
    "Algeria": "ALG",
    "Australia": "AUS",
    "Belgium": "BEL",
    "Bosnia-Herzegovina": "BIH",
    "Brazil": "BRA",
    "Canada": "CAN",
    "Cape Verde Islands": "CPV",
    "Colombia": "COL",
    "Congo DR": "COD",
    "Croatia": "CRO",
    "Curaçao": "CUW",
    "Czechia": "CZE",
    "Ecuador": "ECU",
    "Egypt": "EGY",
    "England": "ENG",
    "France": "FRA",
    "Germany": "GER",
    "Ghana": "GHA",
    "Haiti": "HAI",
    "Iran": "IRN",
    "Iraq": "IRQ",
    "Ivory Coast": "CIV",
    "Japan": "JPN",
    "Jordan": "JOR",
    "Mexico": "MEX",
    "Morocco": "MAR",
    "Netherlands": "NED",
    "New Zealand": "NZL",
    "Norway": "NOR",
    "Panama": "PAN",
    "Paraguay": "PAR",
    "Portugal": "POR",
    "Qatar": "QAT",
    "Saudi Arabia": "KSA",
    "Scotland": "SCO",
    "Senegal": "SEN",
    "South Africa": "RSA",
    "South Korea": "KOR",
    "Spain": "ESP",
    "Sweden": "SWE",
    "Switzerland": "SUI",
    "Tunisia": "TUN",
    "Turkey": "TUR",
    "United States": "USA",
    "Uruguay": "URU",
    "USA": "USA",
    "Uzbekistan": "UZB",
}

TEAM_FLAGS = {
    "Argentina": "🇦🇷",
    "Algeria": "🇩🇿",
    "Australia": "🇦🇺",
    "Austria": "🇦🇹",
    "Belgium": "🇧🇪",
    "Bosnia-Herzegovina": "🇧🇦",
    "Brazil": "🇧🇷",
    "Canada": "🇨🇦",
    "Cape Verde Islands": "🇨🇻",
    "Colombia": "🇨🇴",
    "Congo DR": "🇨🇩",
    "Croatia": "🇭🇷",
    "Curaçao": "🇨🇼",
    "Czechia": "🇨🇿",
    "Ecuador": "🇪🇨",
    "Egypt": "🇪🇬",
    "England": "🏴",
    "France": "🇫🇷",
    "Germany": "🇩🇪",
    "Ghana": "🇬🇭",
    "Haiti": "🇭🇹",
    "Iran": "🇮🇷",
    "Iraq": "🇮🇶",
    "Ivory Coast": "🇨🇮",
    "Japan": "🇯🇵",
    "Jordan": "🇯🇴",
    "Mexico": "🇲🇽",
    "Morocco": "🇲🇦",
    "Netherlands": "🇳🇱",
    "New Zealand": "🇳🇿",
    "Norway": "🇳🇴",
    "Panama": "🇵🇦",
    "Paraguay": "🇵🇾",
    "Portugal": "🇵🇹",
    "Qatar": "🇶🇦",
    "Saudi Arabia": "🇸🇦",
    "Scotland": "🏴",
    "Senegal": "🇸🇳",
    "South Africa": "🇿🇦",
    "South Korea": "🇰🇷",
    "Spain": "🇪🇸",
    "Sweden": "🇸🇪",
    "Switzerland": "🇨🇭",
    "Tunisia": "🇹🇳",
    "Turkey": "🇹🇷",
    "United States": "🇺🇸",
    "Uruguay": "🇺🇾",
    "USA": "🇺🇸",
    "Uzbekistan": "🇺🇿",
}

TEAM_ACCENTS = {
    "Argentina": "#75aadb",
    "Brazil": "#f2d04b",
    "Canada": "#d52b1e",
    "France": "#244aa5",
    "Germany": "#f6c85f",
    "Japan": "#bc002d",
    "Mexico": "#006847",
    "Morocco": "#c91f37",
    "Senegal": "#00853f",
    "South Africa": "#007a4d",
    "United States": "#b22234",
    "USA": "#b22234",
}

# This deterministic fallback is only for model continuity. It is not an official
# ranking feed; fixtures from football-data.org do not include FIFA rankings.
TEAM_RANK_PROXY = {
    "Argentina": 1,
    "Algeria": 38,
    "Australia": 24,
    "Austria": 22,
    "Belgium": 8,
    "Bosnia-Herzegovina": 71,
    "France": 2,
    "Brazil": 5,
    "Canada": 30,
    "Colombia": 13,
    "Croatia": 9,
    "Czechia": 39,
    "Ecuador": 31,
    "Egypt": 34,
    "England": 4,
    "Germany": 10,
    "Ghana": 60,
    "Iran": 20,
    "Ivory Coast": 46,
    "United States": 11,
    "USA": 11,
    "Morocco": 12,
    "Mexico": 15,
    "Netherlands": 7,
    "Norway": 43,
    "Portugal": 6,
    "Qatar": 53,
    "Saudi Arabia": 59,
    "Scotland": 45,
    "South Korea": 23,
    "Spain": 3,
    "Sweden": 25,
    "Switzerland": 19,
    "Tunisia": 41,
    "Turkey": 26,
    "Uruguay": 14,
    "Japan": 18,
    "Senegal": 20,
    "South Africa": 58,
}

LIVE_API_FEED_CACHE = {"expiresAt": 0, "feed": None}
LIVE_API_FEED_TTL_SECONDS = 600
INTERNATIONAL_RESULTS_CACHE = None
THE_ODDS_API_CACHE = {"expiresAt": 0, "payload": None}
THE_ODDS_API_TTL_SECONDS = int(os.environ.get("MATCHORACLE_THE_ODDS_API_CACHE_SECONDS", "21600"))
AUTO_F05_CONTEXT_CACHE = {}

STAGE_ZH = {
    "GROUP_STAGE": "小组赛",
    "ROUND_OF_32": "三十二强",
    "ROUND_OF_16": "十六强",
    "QUARTER_FINAL": "四分之一决赛",
    "SEMI_FINAL": "半决赛",
    "THIRD_PLACE": "季军赛",
    "FINAL": "决赛",
}

STAGE_EN = {
    "GROUP_STAGE": "Group stage",
    "ROUND_OF_32": "Round of 32",
    "ROUND_OF_16": "Round of 16",
    "QUARTER_FINAL": "Quarter-final",
    "SEMI_FINAL": "Semi-final",
    "THIRD_PLACE": "Third-place match",
    "FINAL": "Final",
}

STATUS_ZH = {
    "SCHEDULED": "未开赛",
    "TIMED": "未开赛",
    "IN_PLAY": "进行中",
    "PAUSED": "中场",
    "FINISHED": "已完赛",
    "POSTPONED": "延期",
    "SUSPENDED": "中断",
    "CANCELED": "取消",
    "CANCELLED": "取消",
}

PLAYER_TRANSLATIONS_ZH = {
    "Achraf Hakimi": "阿什拉夫·哈基米",
    "Alisson": "阿利松",
    "Antoine Griezmann": "安托万·格列兹曼",
    "Aurelien Tchouameni": "奥雷利安·楚阿梅尼",
    "Bono": "布努",
    "Bruno Guimaraes": "布鲁诺·吉马良斯",
    "Christian Pulisic": "克里斯蒂安·普利西奇",
    "Cristian Romero": "克里斯蒂安·罗梅罗",
    "Emiliano Martinez": "埃米利亚诺·马丁内斯",
    "Enzo Fernandez": "恩佐·费尔南德斯",
    "Folarin Balogun": "福拉林·巴洛贡",
    "Hakim Ziyech": "哈基姆·齐耶赫",
    "Julian Alvarez": "胡利安·阿尔瓦雷斯",
    "Kaoru Mitoma": "三笘薰",
    "Kylian Mbappe": "基利安·姆巴佩",
    "Lautaro Martinez": "劳塔罗·马丁内斯",
    "Marquinhos": "马尔基尼奥斯",
    "Matt Turner": "马特·特纳",
    "Mike Maignan": "迈克·迈尼昂",
    "Rodrygo": "罗德里戈",
    "Sofyan Amrabat": "索菲扬·阿姆拉巴特",
    "Takefusa Kubo": "久保建英",
    "Takehiro Tomiyasu": "富安健洋",
    "Vinicius Junior": "维尼修斯",
    "Wataru Endo": "远藤航",
    "William Saliba": "威廉·萨利巴",
    "Youssef En-Nesyri": "尤瑟夫·恩内斯里",
    "Zion Suzuki": "铃木彩艳",
}

FOOTBALL_DATA_TOKEN_ENVS = (
    "MATCHORACLE_FOOTBALL_DATA_ORG_TOKEN",
    "MATCHORACLE_STRUCTURED_FACTS_PROVIDER_TOKEN",
)

ODDS_TOKEN_ENVS = (
    "MATCHORACLE_THE_ODDS_API_KEY",
    "MATCHORACLE_ODDS_PROVIDER_TOKEN",
    "THE_ODDS_API_KEY",
)

TEAM_ALIASES = {
    "Bosnia and Herzegovina": "Bosnia-Herzegovina",
    "Bosnia-Herzegovina": "Bosnia-Herzegovina",
    "Cape Verde": "Cape Verde Islands",
    "Cape Verde Islands": "Cape Verde Islands",
    "Côte d'Ivoire": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "DR Congo": "Congo DR",
    "Congo DR": "Congo DR",
    "Iran": "Iran",
    "Iran (Islamic Republic of)": "Iran",
    "Korea Republic": "South Korea",
    "South Korea": "South Korea",
    "Türkiye": "Turkey",
    "Turkiye": "Turkey",
    "Turkey": "Turkey",
    "United States": "United States",
    "USA": "United States",
    "USMNT": "United States",
}

FEATURED_MATCHES = [
    {
        "id": "wc2026-brazil-morocco-g3",
        "statusLabel": "样例预测",
        "statusLabelEn": "Sample prediction",
        "stageLabel": "F组 · 第三轮",
        "stageLabelEn": "Group F · Matchday 3",
        "kickoffLabel": "2026-06-24 21:00 ET",
        "venueLabel": "MetLife Stadium · New Jersey",
        "broadcastNote": "样例数据用于展示预测工作流；接入真实事实库后会自动替换。",
        "broadcastNoteEn": "Sample data demonstrates the prediction workflow and is replaced when verified facts are available.",
        "home": {"name": "Brazil", "nameZh": "巴西", "shortName": "BRA", "flag": "🇧🇷", "fifaRank": 5, "form": "W-W-D-W-L", "accent": "#f2d04b"},
        "away": {"name": "Morocco", "nameZh": "摩洛哥", "shortName": "MAR", "flag": "🇲🇦", "fifaRank": 12, "form": "W-D-W-L-W", "accent": "#c91f37"},
        "sourceBadges": ["赛程: 样例数据", "近期状态: 手工样例", "赔率: 样例赔率", "阵容: 样例球员层"],
        "sourceBadgesEn": ["Fixture: sample data", "Form: sample input", "Odds: sample odds", "Lineup: sample player layer"],
        "lineups": {
            "homeFormation": "4-3-3",
            "awayFormation": "4-2-3-1",
            "homePlayers": [
                {"name": "Alisson", "nameZh": "阿利松", "role": "GK", "tier": "TIER_1", "note": "门将稳定性"},
                {"name": "Marquinhos", "nameZh": "马尔基尼奥斯", "role": "CB", "tier": "TIER_1", "note": "后场组织"},
                {"name": "Bruno Guimaraes", "nameZh": "布鲁诺·吉马良斯", "role": "CM", "tier": "TIER_2", "note": "推进节奏"},
                {"name": "Vinicius Junior", "nameZh": "维尼修斯", "role": "LW", "tier": "TIER_1", "note": "左路爆点"},
                {"name": "Rodrygo", "nameZh": "罗德里戈", "role": "RW", "tier": "TIER_1", "note": "二点终结"},
            ],
            "awayPlayers": [
                {"name": "Bono", "nameZh": "布努", "role": "GK", "tier": "TIER_1", "note": "扑救波动"},
                {"name": "Achraf Hakimi", "nameZh": "阿什拉夫·哈基米", "role": "RB", "tier": "TIER_1", "note": "反击出口"},
                {"name": "Sofyan Amrabat", "nameZh": "索菲扬·阿姆拉巴特", "role": "DM", "tier": "TIER_1", "note": "中路拦截"},
                {"name": "Hakim Ziyech", "nameZh": "哈基姆·齐耶赫", "role": "RW", "tier": "TIER_2", "note": "定位球"},
                {"name": "Youssef En-Nesyri", "nameZh": "尤瑟夫·恩内斯里", "role": "ST", "tier": "TIER_2", "note": "禁区终结"},
            ],
        },
        "predictionPayload": {
            "matchId": "wc2026-brazil-morocco-g3",
            "match": {"homeTeam": "Brazil", "awayTeam": "Morocco", "stage": "GROUP_STAGE", "datetime": "2026-06-25T01:00:00+00:00", "venue": "MetLife Stadium", "matchday": 3, "groupRound": 3},
            "teamData": {"home": {"fifaRank": 5}, "away": {"fifaRank": 12}},
            "understatCoverage": {"home": 8, "away": 8},
            "goalData": {"home": {"actualGoals_avg": 2.08, "xGA_avg": 0.82, "setpieceRate": 0.21}, "away": {"actualGoals_avg": 1.34, "xGA_avg": 1.02, "setpieceRate": 0.37}},
            "goalkeeperData": {"home": {"score": 86}, "away": {"score": 82}},
            "formationData": {"home": "4-3-3", "away": "4-2-3-1"},
            "tacticalData": {"homeContinuityScore": 78, "awayContinuityScore": 82},
            "depthData": {"home": {"benchStrength": 86, "penaltyReadiness": 74}, "away": {"benchStrength": 74, "penaltyReadiness": 78}},
            "matchContext": {"groupRound": 3, "homeQualificationStatus": "ALREADY_QUALIFIED", "awayQualificationStatus": "MUST_WIN", "homeMotivationScore": 1.1, "awayMotivationScore": 2.7, "homeRotationRisk": 0.34, "awayRotationRisk": 0.08, "awayMustWinPressure": 0.72, "pathIncentiveRisk": 0.28, "cardRiskImportance": 0.38},
            "expectedLineup": {"homeFormation": "4-3-3", "awayFormation": "4-2-3-1", "homeStarters": ["Alisson", "Marquinhos", "Bruno Guimaraes", "Vinicius Junior", "Rodrygo"], "awayStarters": ["Bono", "Achraf Hakimi", "Sofyan Amrabat", "Hakim Ziyech", "Youssef En-Nesyri"]},
            "decimalOdds": {"home": 1.72, "draw": 3.55, "away": 5.20},
            "openingDecimalOdds": {"home": 1.62, "draw": 3.75, "away": 5.70},
            "publicTicketPercent": {"home": 69, "draw": 17, "away": 14},
            "oddsSnapshotTime": "2026-06-13T09:00:00+00:00",
            "featureSnapshotTime": "2026-06-13T09:08:00+00:00",
        },
    },
    {
        "id": "wc2026-argentina-france-r16",
        "statusLabel": "模拟对阵",
        "statusLabelEn": "Simulated pairing",
        "stageLabel": "十六强 · 90分钟口径",
        "stageLabelEn": "Round of 16 · 90-minute market",
        "kickoffLabel": "2026-06-30 20:00 ET",
        "venueLabel": "AT&T Stadium · Dallas",
        "broadcastNote": "这不是官方赛程，只用于验证淘汰赛展示和晋级层。",
        "broadcastNoteEn": "This is not an official fixture; it only validates knockout display and advancement layers.",
        "home": {"name": "Argentina", "nameZh": "阿根廷", "shortName": "ARG", "flag": "🇦🇷", "fifaRank": 1, "form": "W-D-W-W-D", "accent": "#75aadb"},
        "away": {"name": "France", "nameZh": "法国", "shortName": "FRA", "flag": "🇫🇷", "fifaRank": 2, "form": "W-W-L-W-D", "accent": "#244aa5"},
        "sourceBadges": ["赛程: 模拟样例", "阵容: 样例球员层", "赔率: 样例赔率", "提醒: 非官方赛程"],
        "sourceBadgesEn": ["Fixture: simulated sample", "Lineup: sample player layer", "Odds: sample odds", "Note: not official"],
        "lineups": {
            "homeFormation": "4-3-3",
            "awayFormation": "4-2-3-1",
            "homePlayers": [
                {"name": "Emiliano Martinez", "nameZh": "埃米利亚诺·马丁内斯", "role": "GK", "tier": "TIER_1", "note": "点球/门线"},
                {"name": "Cristian Romero", "nameZh": "克里斯蒂安·罗梅罗", "role": "CB", "tier": "TIER_1", "note": "对抗强度"},
                {"name": "Enzo Fernandez", "nameZh": "恩佐·费尔南德斯", "role": "CM", "tier": "TIER_1", "note": "中场推进"},
                {"name": "Julian Alvarez", "nameZh": "胡利安·阿尔瓦雷斯", "role": "ST", "tier": "TIER_1", "note": "前场压迫"},
                {"name": "Lautaro Martinez", "nameZh": "劳塔罗·马丁内斯", "role": "ST", "tier": "TIER_1", "note": "终结效率"},
            ],
            "awayPlayers": [
                {"name": "Mike Maignan", "nameZh": "迈克·迈尼昂", "role": "GK", "tier": "TIER_1", "note": "出球质量"},
                {"name": "William Saliba", "nameZh": "威廉·萨利巴", "role": "CB", "tier": "TIER_1", "note": "防线稳定"},
                {"name": "Aurelien Tchouameni", "nameZh": "奥雷利安·楚阿梅尼", "role": "DM", "tier": "TIER_1", "note": "中场屏障"},
                {"name": "Kylian Mbappe", "nameZh": "基利安·姆巴佩", "role": "LW", "tier": "TIER_1", "note": "转换速度"},
                {"name": "Antoine Griezmann", "nameZh": "安托万·格列兹曼", "role": "AM", "tier": "TIER_1", "note": "机会创造"},
            ],
        },
        "predictionPayload": {
            "matchId": "wc2026-argentina-france-r16",
            "match": {"homeTeam": "Argentina", "awayTeam": "France", "stage": "ROUND_OF_16", "datetime": "2026-07-01T00:00:00+00:00", "venue": "AT&T Stadium"},
            "teamData": {"home": {"fifaRank": 1}, "away": {"fifaRank": 2}},
            "understatCoverage": {"home": 8, "away": 8},
            "goalData": {"home": {"actualGoals_avg": 1.76, "xGA_avg": 0.88, "setpieceRate": 0.26}, "away": {"actualGoals_avg": 1.82, "xGA_avg": 0.86, "setpieceRate": 0.24}},
            "goalkeeperData": {"home": {"score": 84}, "away": {"score": 85}},
            "formationData": {"home": "4-3-3", "away": "4-2-3-1"},
            "tacticalData": {"homeContinuityScore": 84, "awayContinuityScore": 80},
            "depthData": {"home": {"benchStrength": 82, "penaltyReadiness": 86}, "away": {"benchStrength": 88, "penaltyReadiness": 82}},
            "matchContext": {"homeQualificationStatus": "MUST_WIN", "awayQualificationStatus": "MUST_WIN", "homeMotivationScore": 2.8, "awayMotivationScore": 2.8, "homeRotationRisk": 0.04, "awayRotationRisk": 0.04, "cardRiskImportance": 0.42},
            "expectedLineup": {"homeFormation": "4-3-3", "awayFormation": "4-2-3-1", "homeStarters": ["Emiliano Martinez", "Cristian Romero", "Enzo Fernandez", "Julian Alvarez", "Lautaro Martinez"], "awayStarters": ["Mike Maignan", "William Saliba", "Aurelien Tchouameni", "Kylian Mbappe", "Antoine Griezmann"]},
            "decimalOdds": {"home": 2.62, "draw": 3.05, "away": 2.78},
            "openingDecimalOdds": {"home": 2.70, "draw": 3.10, "away": 2.62},
            "publicTicketPercent": {"home": 40, "draw": 18, "away": 42},
            "oddsSnapshotTime": "2026-06-13T09:00:00+00:00",
            "featureSnapshotTime": "2026-06-13T09:08:00+00:00",
        },
    },
    {
        "id": "wc2026-usa-japan-g1",
        "statusLabel": "样例预测",
        "statusLabelEn": "Sample prediction",
        "stageLabel": "D组 · 第一轮",
        "stageLabelEn": "Group D · Matchday 1",
        "kickoffLabel": "2026-06-15 18:00 PT",
        "venueLabel": "SoFi Stadium · Los Angeles",
        "broadcastNote": "样例数据用于展示首战波动、置信度和风险解释。",
        "broadcastNoteEn": "Sample data shows opening-match volatility, confidence, and risk explanation.",
        "home": {"name": "United States", "nameZh": "美国", "shortName": "USA", "flag": "🇺🇸", "fifaRank": 11, "form": "D-W-W-L-W", "accent": "#b22234"},
        "away": {"name": "Japan", "nameZh": "日本", "shortName": "JPN", "flag": "🇯🇵", "fifaRank": 18, "form": "W-W-D-W-L", "accent": "#bc002d"},
        "sourceBadges": ["赛程: 样例数据", "近期状态: 手工样例", "赔率: 样例赔率", "阵容: 样例球员层"],
        "sourceBadgesEn": ["Fixture: sample data", "Form: sample input", "Odds: sample odds", "Lineup: sample player layer"],
        "lineups": {
            "homeFormation": "4-2-3-1",
            "awayFormation": "4-3-3",
            "homePlayers": [
                {"name": "Matt Turner", "nameZh": "马特·特纳", "role": "GK", "tier": "TIER_2", "note": "扑救稳定"},
                {"name": "Antonee Robinson", "nameZh": "安东尼·罗宾逊", "role": "LB", "tier": "TIER_1", "note": "左路推进"},
                {"name": "Weston McKennie", "nameZh": "韦斯顿·麦肯尼", "role": "CM", "tier": "TIER_1", "note": "二点球"},
                {"name": "Christian Pulisic", "nameZh": "克里斯蒂安·普利西奇", "role": "LW", "tier": "TIER_1", "note": "主要创造"},
                {"name": "Folarin Balogun", "nameZh": "福拉林·巴洛贡", "role": "ST", "tier": "TIER_2", "note": "纵深跑动"},
            ],
            "awayPlayers": [
                {"name": "Zion Suzuki", "nameZh": "铃木彩艳", "role": "GK", "tier": "TIER_2", "note": "反应速度"},
                {"name": "Takehiro Tomiyasu", "nameZh": "富安健洋", "role": "CB", "tier": "TIER_1", "note": "防线覆盖"},
                {"name": "Wataru Endo", "nameZh": "远藤航", "role": "DM", "tier": "TIER_1", "note": "中路保护"},
                {"name": "Kaoru Mitoma", "nameZh": "三笘薰", "role": "LW", "tier": "TIER_1", "note": "边路突破"},
                {"name": "Takefusa Kubo", "nameZh": "久保建英", "role": "RW", "tier": "TIER_1", "note": "右侧组织"},
            ],
        },
        "predictionPayload": {
            "matchId": "wc2026-usa-japan-g1",
            "match": {"homeTeam": "United States", "awayTeam": "Japan", "stage": "GROUP_STAGE", "datetime": "2026-06-16T01:00:00+00:00", "venue": "SoFi Stadium", "matchday": 1, "groupRound": 1},
            "teamData": {"home": {"fifaRank": 11}, "away": {"fifaRank": 18}},
            "understatCoverage": {"home": 7, "away": 7},
            "goalData": {"home": {"actualGoals_avg": 1.46, "xGA_avg": 1.06, "setpieceRate": 0.29}, "away": {"actualGoals_avg": 1.54, "xGA_avg": 0.98, "setpieceRate": 0.23}},
            "goalkeeperData": {"home": {"score": 76}, "away": {"score": 78}},
            "formationData": {"home": "4-2-3-1", "away": "4-3-3"},
            "tacticalData": {"homeContinuityScore": 76, "awayContinuityScore": 86},
            "depthData": {"home": {"benchStrength": 76, "penaltyReadiness": 72}, "away": {"benchStrength": 79, "penaltyReadiness": 76}},
            "matchContext": {"groupRound": 1, "homeQualificationStatus": "UNKNOWN", "awayQualificationStatus": "UNKNOWN", "homeMotivationScore": 2.5, "awayMotivationScore": 2.5, "homeRotationRisk": 0.06, "awayRotationRisk": 0.06, "cardRiskImportance": 0.24},
            "expectedLineup": {"homeFormation": "4-2-3-1", "awayFormation": "4-3-3", "homeStarters": ["Matt Turner", "Antonee Robinson", "Weston McKennie", "Christian Pulisic", "Folarin Balogun"], "awayStarters": ["Zion Suzuki", "Takehiro Tomiyasu", "Wataru Endo", "Kaoru Mitoma", "Takefusa Kubo"]},
            "decimalOdds": {"home": 2.28, "draw": 3.22, "away": 3.18},
            "openingDecimalOdds": {"home": 2.36, "draw": 3.16, "away": 3.05},
            "publicTicketPercent": {"home": 58, "draw": 19, "away": 23},
            "oddsSnapshotTime": "2026-06-13T09:00:00+00:00",
            "featureSnapshotTime": "2026-06-13T09:08:00+00:00",
        },
    },
]


def team_zh(name):
    return TEAM_TRANSLATIONS_ZH.get(name, name)


def team_short_name(name, fact=None, side=None):
    if fact and side:
        value = fact.get(f"{side}TeamTla")
        if value:
            return str(value)
    return TEAM_SHORT_NAMES.get(name, str(name or "")[:3].upper())


def safe_iso(value):
    parsed = parse_iso_timestamp(value)
    if parsed:
        return parsed.isoformat()
    return None


def latest_row_sort_key(row):
    return (
        parse_iso_timestamp(row.get("snapshotTime")) or datetime.min.replace(tzinfo=timezone.utc),
        parse_iso_timestamp(row.get("ingestedAt")) or datetime.min.replace(tzinfo=timezone.utc),
        parse_iso_timestamp(row.get("createdAt")) or datetime.min.replace(tzinfo=timezone.utc),
    )


def latest_rows_by_match(fact_key):
    latest = {}
    for row in list_structured_fact_read_rows(fact_key=fact_key):
        match_id = row.get("matchId")
        if not match_id:
            continue
        current = latest.get(match_id)
        if current is None or latest_row_sort_key(row) > latest_row_sort_key(current):
            latest[match_id] = row
    return latest


def latest_rows(fact_key):
    rows = list_structured_fact_read_rows(fact_key=fact_key)
    parsed_rows = [(parse_iso_timestamp(row["snapshotTime"]), row) for row in rows]
    parsed_rows = [(snapshot, row) for snapshot, row in parsed_rows if snapshot]
    if not parsed_rows:
        return []
    latest_snapshot = max(snapshot for snapshot, _ in parsed_rows)
    return [row for snapshot, row in parsed_rows if snapshot == latest_snapshot]


def format_kickoff_label(kickoff_at):
    parsed = parse_iso_timestamp(kickoff_at)
    if not parsed:
        return "开球时间待定"
    utc = parsed.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%d %H:%M UTC")


def venue_labels(fact):
    venue = fact.get("venue")
    return {
        "zh": venue or "场馆待定",
        "en": venue or "Venue pending",
    }


def group_letter(group):
    if not group:
        return None
    text = str(group)
    match = re.search(r"(?:GROUP[_\s-]?|Group\s+)?([A-L])$", text, flags=re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return None


def stage_label(stage, fact=None):
    stage = stage or "GROUP_STAGE"
    group = (fact or {}).get("group")
    matchday = (fact or {}).get("matchday")
    zh = STAGE_ZH.get(stage, stage)
    en = STAGE_EN.get(stage, stage)
    if group and stage == "GROUP_STAGE":
        group_label = group_letter(group) or str(group).replace("Group ", "").replace("GROUP_", "")
        zh = f"{group_label}组 · 第{matchday or '?'}轮"
        en = f"Group {group_label} · Matchday {matchday or '?'}"
    return zh, en


def status_label(status):
    status = str(status or "SCHEDULED").upper()
    return STATUS_ZH.get(status, status.replace("_", " ").title())


def api_connection_status():
    football_token = any(os.environ.get(env_name) for env_name in FOOTBALL_DATA_TOKEN_ENVS)
    odds_token = any(os.environ.get(env_name) for env_name in ODDS_TOKEN_ENVS)
    api_football = cached_api_football_worldcup_availability()
    return {
        "footballDataOrg": {
            "connected": football_token,
            "mode": "LIVE_API" if football_token else "TOKEN_MISSING",
            "requiredEnv": list(FOOTBALL_DATA_TOKEN_ENVS),
        },
        "theOddsApi": {
            "connected": odds_token,
            "mode": "LIVE_API" if odds_token else "TOKEN_MISSING",
            "requiredEnv": list(ODDS_TOKEN_ENVS),
        },
        "lineupProvider": {
            "connected": api_football.get("connected", False),
            "mode": "API_FOOTBALL" if api_football.get("connected") else api_football.get("mode", "NO_PROVIDER_ADAPTER"),
            "requiredEnv": api_football.get("requiredEnv", []),
            "provider": "api_football",
            "reason": api_football.get("reason"),
        },
        "apiFootball": {
            **api_football,
            "role": "lineups_injuries_players",
        },
    }


def side_team(name, fact=None, side=None):
    return {
        "name": name,
        "nameZh": team_zh(name),
        "shortName": team_short_name(name, fact=fact, side=side),
        "flag": TEAM_FLAGS.get(name, "🏳"),
        "fifaRank": TEAM_RANK_PROXY.get(name, 80),
        "accent": TEAM_ACCENTS.get(name, "#d8b45d"),
    }


def form_text(profile):
    sequence = profile.get("recentFormSequence")
    if sequence:
        return sequence
    return ""


def canonical_team_key(name):
    canonical = TEAM_ALIASES.get(str(name or "").strip(), str(name or "").strip())
    return "".join(character.lower() for character in canonical if character.isalnum())


def placeholder_team(label, short_name, flag="◇"):
    return {
        "name": label,
        "nameZh": label,
        "shortName": short_name,
        "flag": flag,
        "fifaRank": None,
        "accent": "#d8b45d",
        "form": "",
        "placeholder": True,
    }


def score_from_row(score_row):
    fact = (score_row or {}).get("fact") or {}
    full_time = fact.get("fullTime") if isinstance(fact.get("fullTime"), dict) else {}
    home = full_time.get("home")
    away = full_time.get("away")
    if home is None or away is None:
        regular_time = fact.get("regularTime") if isinstance(fact.get("regularTime"), dict) else {}
        home = regular_time.get("home")
        away = regular_time.get("away")
    if home is None or away is None:
        return None
    return {
        "home": home,
        "away": away,
        "winner": fact.get("winner"),
        "status": fact.get("status"),
        "duration": fact.get("duration"),
    }


def player_name_from_lineup_item(item):
    if isinstance(item, dict):
        return item.get("name") or item.get("playerName") or item.get("shortName")
    return item


def player_row_from_lineup_item(item):
    if isinstance(item, dict):
        name = player_name_from_lineup_item(item)
        return {
            "name": name,
            "nameZh": PLAYER_TRANSLATIONS_ZH.get(name, item.get("nameZh") or name),
            "role": item.get("role") or item.get("position") or "--",
            "tier": item.get("tier") or "OFFICIAL",
            "note": item.get("note") or item.get("status") or "官方首发",
        }
    name = str(item)
    return {
        "name": name,
        "nameZh": PLAYER_TRANSLATIONS_ZH.get(name, name),
        "role": "--",
        "tier": "OFFICIAL",
        "note": "官方首发",
    }


def lineup_names(items):
    names = []
    for item in items or []:
        name = player_name_from_lineup_item(item)
        if name:
            names.append(str(name))
    return names


def lineup_key_players(items):
    players = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        name = player_name_from_lineup_item(item)
        if not name:
            continue
        if item.get("tier") or item.get("role") or item.get("position") or item.get("startProbability") is not None:
            player = {
                "name": name,
                "tier": item.get("tier") or "OFFICIAL",
                "role": item.get("role") or item.get("position") or "STARTER",
            }
            if item.get("startProbability") is not None:
                player["startProbability"] = item.get("startProbability")
            players.append(player)
    return players


def lineup_payload_from_row(lineup_row):
    fact = (lineup_row or {}).get("fact") or {}
    home_starters = fact.get("homeStarters") or []
    away_starters = fact.get("awayStarters") or []
    return {
        "homeFormation": fact.get("homeFormation"),
        "awayFormation": fact.get("awayFormation"),
        "homeStarters": lineup_names(home_starters),
        "awayStarters": lineup_names(away_starters),
        "homeKeyPlayers": fact.get("homeKeyPlayers") or lineup_key_players(home_starters),
        "awayKeyPlayers": fact.get("awayKeyPlayers") or lineup_key_players(away_starters),
    }


def lineup_display_from_row(lineup_row):
    fact = (lineup_row or {}).get("fact") or {}
    payload = lineup_payload_from_row(lineup_row)
    return {
        "homeFormation": payload["homeFormation"],
        "awayFormation": payload["awayFormation"],
        "homePlayers": [player_row_from_lineup_item(item) for item in fact.get("homeStarters") or []],
        "awayPlayers": [player_row_from_lineup_item(item) for item in fact.get("awayStarters") or []],
    }


def knockout_placeholder_label(stage, provider_match_id, sequence_number):
    stage_zh = STAGE_ZH.get(stage, stage or "淘汰赛")
    stage_en = STAGE_EN.get(stage, stage or "Knockout")
    match_no = sequence_number or provider_match_id
    return {
        "zh": f"M{match_no} · {stage_zh}席位待定",
        "en": f"M{match_no} · {stage_en} slots pending",
        "short": f"M{match_no}",
    }


def odds_for_match(fact, year):
    snapshots = list_market_odds_snapshots(
        year=year,
        home_team=fact.get("homeTeam"),
        away_team=fact.get("awayTeam"),
        limit=1,
    )
    if snapshots:
        snapshot = snapshots[0]
        decimal_odds = snapshot.get("decimalOdds") or {}
        return {
            "decimalOdds": {
                "home": decimal_odds.get("home"),
                "draw": decimal_odds.get("draw"),
                "away": decimal_odds.get("away"),
            },
            "oddsSnapshotTime": snapshot["snapshotTime"],
            "source": snapshot.get("source"),
        }
    live_snapshot = live_odds_for_match(fact)
    if live_snapshot:
        return {
            "decimalOdds": live_snapshot["decimalOdds"],
            "oddsSnapshotTime": live_snapshot["snapshotTime"],
            "source": live_snapshot.get("source"),
            "provider": live_snapshot.get("provider"),
        }
    return None


def live_odds_payload():
    now = time.time()
    cached = THE_ODDS_API_CACHE.get("payload")
    if cached and THE_ODDS_API_CACHE.get("expiresAt", 0) > now:
        return copy.deepcopy(cached)
    token_configured = any(os.environ.get(env_name) for env_name in ODDS_TOKEN_ENVS)
    if not token_configured:
        return None
    try:
        payload = fetch_the_odds_api_snapshots()
    except TheOddsApiError:
        return None
    try:
        import_live_odds_snapshots(payload.get("snapshots") or [], source_name="the_odds_api")
    except Exception:
        payload["storePersisted"] = False
    else:
        payload["storePersisted"] = True
    THE_ODDS_API_CACHE["payload"] = copy.deepcopy(payload)
    THE_ODDS_API_CACHE["expiresAt"] = now + THE_ODDS_API_TTL_SECONDS
    return payload


def live_odds_for_match(fact):
    payload = live_odds_payload()
    if not payload:
        return None
    home_key = canonical_team_key(fact.get("homeTeam"))
    away_key = canonical_team_key(fact.get("awayTeam"))
    kickoff = parse_iso_timestamp(fact.get("kickoffAt") or fact.get("utcDate"))
    for snapshot in payload.get("snapshots") or []:
        left = canonical_team_key(snapshot.get("homeTeam"))
        right = canonical_team_key(snapshot.get("awayTeam"))
        if {left, right} != {home_key, away_key}:
            continue
        event_time = parse_iso_timestamp(snapshot.get("kickoffAt"))
        if kickoff and event_time and abs((event_time - kickoff).total_seconds()) > 36 * 3600:
            continue
        if left == home_key and right == away_key:
            return snapshot
        if left == away_key and right == home_key:
            return {
                **snapshot,
                "homeTeam": fact.get("homeTeam"),
                "awayTeam": fact.get("awayTeam"),
                "decimalOdds": {
                    "home": snapshot["decimalOdds"]["away"],
                    "draw": snapshot["decimalOdds"]["draw"],
                    "away": snapshot["decimalOdds"]["home"],
                },
            }
    return None


def rank_proxy_probabilities(home_team, away_team):
    home_rank = TEAM_RANK_PROXY.get(home_team, 80)
    away_rank = TEAM_RANK_PROXY.get(away_team, 80)
    edge = max(-2.2, min(2.2, (away_rank - home_rank) / 32.0))
    home_raw = pow(2.718281828, edge)
    away_raw = pow(2.718281828, -edge)
    draw_raw = 1.05
    total = home_raw + draw_raw + away_raw
    return {
        "home": round(home_raw / total, 4),
        "draw": round(draw_raw / total, 4),
        "away": round(away_raw / total, 4),
    }


def f05_match_from_row(fixture_row, score_rows):
    fact = fixture_row.get("fact") or {}
    if (fact.get("stage") or "GROUP_STAGE") != "GROUP_STAGE":
        return None
    home = fact.get("homeTeam")
    away = fact.get("awayTeam")
    group = fact.get("group")
    if not home or not away or not group:
        return None
    score = score_from_row(score_rows.get(fixture_row.get("matchId")))
    item = {
        "matchId": fact.get("matchId") or fixture_row.get("matchId"),
        "stage": "GROUP_STAGE",
        "group": group,
        "homeTeam": home,
        "awayTeam": away,
        "datetime": safe_iso(fact.get("kickoffAt") or fact.get("utcDate")),
        "matchday": fact.get("matchday"),
        "probabilities": rank_proxy_probabilities(home, away),
    }
    if score:
        item["actualScore"] = {"home": int(score["home"]), "away": int(score["away"])}
    return item


def neutral_f05_context(fact, reason=None):
    return {
        "groupRound": fact.get("matchday"),
        "homeQualificationStatus": "UNKNOWN",
        "awayQualificationStatus": "UNKNOWN",
        "homeMotivationScore": 2.5,
        "awayMotivationScore": 2.5,
        "homeRotationRisk": 0.02,
        "awayRotationRisk": 0.02,
        "homeQualificationByOutcome": {"W": 0.0, "D": 0.0, "L": 0.0},
        "awayQualificationByOutcome": {"W": 0.0, "D": 0.0, "L": 0.0},
        "homeMustWinPressure": 0.0,
        "awayMustWinPressure": 0.0,
        "matchDrawIncentive": 0.0,
        "qualificationModel": "WC2026_48_FAST_PATH",
        "reasoning": reason or "小组首轮或赛程上下文不足，F05自动层按中性处理。",
    }


def qualification_status(scores, rotation_risk):
    if not scores:
        return "UNKNOWN"
    win = float(scores.get("W", 0))
    draw = float(scores.get("D", 0))
    loss = float(scores.get("L", 0))
    if loss >= 0.85:
        return "ALREADY_QUALIFIED"
    if win <= 0.12:
        return "ELIMINATED_RISK"
    if win - draw >= 0.35:
        return "MUST_WIN"
    if draw - loss >= 0.25 or rotation_risk >= 0.18:
        return "NEED_DRAW"
    return "OPEN"


def enrich_f05_context(context):
    home_scores = context.get("homeQualificationByOutcome") or {}
    away_scores = context.get("awayQualificationByOutcome") or {}
    context["homeQualificationStatus"] = qualification_status(home_scores, context.get("homeRotationRisk", 0))
    context["awayQualificationStatus"] = qualification_status(away_scores, context.get("awayRotationRisk", 0))
    context["pathIncentiveRisk"] = round(min(1.0, max(0.0, context.get("matchDrawIncentive", 0)) * 0.65), 4)
    context["mutualDrawIncentive"] = context.get("matchDrawIncentive", 0)
    return context


def auto_f05_contexts(fixture_rows, score_rows):
    snapshot_key = stable_f05_context_key(fixture_rows, score_rows)
    if snapshot_key in AUTO_F05_CONTEXT_CACHE:
        return copy.deepcopy(AUTO_F05_CONTEXT_CACHE[snapshot_key])
    matches = [
        match for match in (f05_match_from_row(row, score_rows) for row in fixture_rows.values())
        if match
    ]
    if len({match["group"] for match in matches}) < 12:
        return {}
    contexts = {}
    for match in matches:
        fact = {"matchday": match.get("matchday")}
        if match.get("actualScore"):
            contexts[match["matchId"]] = neutral_f05_context(fact, reason="比赛已完赛，F05仅保留赛后解释层。")
            continue
        if int(match.get("matchday") or 1) <= 1 and not any(
            team_played_before(matches, match, team)
            for team in (match["homeTeam"], match["awayTeam"])
        ):
            contexts[match["matchId"]] = neutral_f05_context(fact)
            continue
        contexts[match["matchId"]] = build_fast_f05_context(matches, match)
    AUTO_F05_CONTEXT_CACHE[snapshot_key] = copy.deepcopy(contexts)
    return contexts


def group_matches_for_current(matches, current):
    return [match for match in matches if match.get("group") == current.get("group")]


def table_before_match(group_items, current):
    table = {}
    for match in group_items:
        table.setdefault(match["homeTeam"], empty_record())
        table.setdefault(match["awayTeam"], empty_record())
    current_time = parse_iso_timestamp(current.get("datetime"))
    for match in group_items:
        match_time = parse_iso_timestamp(match.get("datetime"))
        if not match.get("actualScore") or not match_time or not current_time or match_time >= current_time:
            continue
        apply_score(
            table,
            match["homeTeam"],
            match["awayTeam"],
            int(match["actualScore"]["home"]),
            int(match["actualScore"]["away"]),
        )
    return table


def remaining_matches_after(group_items, current, team):
    current_time = parse_iso_timestamp(current.get("datetime"))
    count = 0
    for match in group_items:
        if team not in {match.get("homeTeam"), match.get("awayTeam")}:
            continue
        match_time = parse_iso_timestamp(match.get("datetime"))
        if match.get("matchId") == current.get("matchId"):
            continue
        if match.get("actualScore"):
            continue
        if match_time and current_time and match_time > current_time:
            count += 1
    return count


def outcome_score_for_team(current, team, outcome):
    if outcome == "D":
        return 1, 1
    team_is_home = team == current["homeTeam"]
    if outcome == "W":
        return (1, 0) if team_is_home else (0, 1)
    return (0, 1) if team_is_home else (1, 0)


def apply_current_outcome(table, current, team, outcome):
    copied = copy.deepcopy(table)
    home_goals, away_goals = outcome_score_for_team(current, team, outcome)
    apply_score(copied, current["homeTeam"], current["awayTeam"], home_goals, away_goals)
    return copied


def third_place_chance(points, goal_difference, goals_for, remaining):
    projected_points = points + remaining * 1.25
    if projected_points >= 5:
        base = 0.82
    elif projected_points >= 4:
        base = 0.63
    elif projected_points >= 3:
        base = 0.36
    elif projected_points >= 2:
        base = 0.16
    else:
        base = 0.04
    return clamp(base + goal_difference * 0.06 + goals_for * 0.015, 0.02, 0.9)


def estimated_advancement_probability(table, team, remaining):
    rankings = ranking_for_group(table)
    row = next((item for item in rankings if item["team"] == team), None)
    if not row:
        return 0.0
    if row["rank"] <= 2:
        return clamp(0.82 + row["points"] * 0.025 + row["gd"] * 0.03 + remaining * 0.03, 0.12, 0.98)
    if row["rank"] == 3:
        return third_place_chance(row["points"], row["gd"], row["gf"], remaining)
    return clamp(third_place_chance(row["points"], row["gd"], row["gf"], remaining) * 0.55, 0.01, 0.45)


def qualification_by_outcome(table, group_items, current, team):
    remaining = remaining_matches_after(group_items, current, team)
    scores = {}
    for outcome in ("W", "D", "L"):
        outcome_table = apply_current_outcome(table, current, team, outcome)
        scores[outcome] = round(estimated_advancement_probability(outcome_table, team, remaining), 4)
    return scores


def build_fast_f05_context(matches, current):
    group_items = group_matches_for_current(matches, current)
    table = table_before_match(group_items, current)
    home = current["homeTeam"]
    away = current["awayTeam"]
    home_scores = qualification_by_outcome(table, group_items, current, home)
    away_scores = qualification_by_outcome(table, group_items, current, away)
    home_motivation, home_rotation, home_draw_incentive, home_note = motivation_from_outcome_shares(
        home_scores,
        completed_fast_played_count(group_items, current, home),
    )
    away_motivation, away_rotation, away_draw_incentive, away_note = motivation_from_outcome_shares(
        away_scores,
        completed_fast_played_count(group_items, current, away),
    )
    home_note = home_note.replace("48队模拟", "48队路径模型")
    away_note = away_note.replace("48队模拟", "48队路径模型")
    match_draw_incentive = round(min(home_draw_incentive, away_draw_incentive), 4)
    return enrich_f05_context({
        "groupRound": current.get("matchday"),
        "homeMotivationScore": round(home_motivation, 2),
        "awayMotivationScore": round(away_motivation, 2),
        "homeRotationRisk": round(home_rotation, 2),
        "awayRotationRisk": round(away_rotation, 2),
        "homeQualificationByOutcome": home_scores,
        "awayQualificationByOutcome": away_scores,
        "homeMustWinPressure": round(max(0.0, home_scores["W"] - home_scores["D"]), 4),
        "awayMustWinPressure": round(max(0.0, away_scores["W"] - away_scores["D"]), 4),
        "matchDrawIncentive": match_draw_incentive,
        "qualificationModel": "WC2026_48_FAST_PATH",
        "reasoning": f"{home}: {home_note} {away}: {away_note}",
    })


def completed_fast_played_count(group_items, current, team):
    current_time = parse_iso_timestamp(current.get("datetime"))
    count = 0
    for match in group_items:
        if team not in {match.get("homeTeam"), match.get("awayTeam")}:
            continue
        match_time = parse_iso_timestamp(match.get("datetime"))
        if match.get("actualScore") and match_time and current_time and match_time < current_time:
            count += 1
    return count


def stable_f05_context_key(fixture_rows, score_rows):
    items = []
    for match_id, row in sorted(fixture_rows.items()):
        fact = row.get("fact") or {}
        score = score_from_row(score_rows.get(match_id))
        items.append((
            match_id,
            fact.get("homeTeam"),
            fact.get("awayTeam"),
            fact.get("group"),
            fact.get("matchday"),
            fact.get("kickoffAt") or fact.get("utcDate"),
            score.get("home") if score else None,
            score.get("away") if score else None,
        ))
    return str(abs(hash(tuple(items))))


def team_played_before(matches, current, team):
    current_time = parse_iso_timestamp(current.get("datetime"))
    for match in matches:
        if team not in {match.get("homeTeam"), match.get("awayTeam")}:
            continue
        match_time = parse_iso_timestamp(match.get("datetime"))
        if match.get("actualScore") and match_time and current_time and match_time < current_time:
            return True
    return False


def international_results():
    global INTERNATIONAL_RESULTS_CACHE
    if INTERNATIONAL_RESULTS_CACHE is None:
        INTERNATIONAL_RESULTS_CACHE = load_international_results()
    return INTERNATIONAL_RESULTS_CACHE


def build_prediction_payload(fixture_row, status_row=None, lineup_row=None, f05_context=None):
    fact = fixture_row["fact"]
    home = fact.get("homeTeam")
    away = fact.get("awayTeam")
    kickoff_iso = safe_iso(fact.get("kickoffAt") or fact.get("utcDate"))
    kickoff_date = (kickoff_iso or datetime.now(timezone.utc).isoformat())[:10]
    year = int(kickoff_date[:4])
    features = build_match_prematch_features(international_results(), home, away, kickoff_date)
    home_profile = features["home"]
    away_profile = features["away"]
    odds = odds_for_match(fact, year)
    status_fact = (status_row or {}).get("fact") or {}
    stage = fact.get("stage") or "GROUP_STAGE"
    expected_lineup = lineup_payload_from_row(lineup_row)
    lineup_connected = bool(expected_lineup["homeStarters"] or expected_lineup["awayStarters"])
    payload = {
        "matchId": fact.get("matchId") or fixture_row["matchId"],
        "match": {
            "homeTeam": home,
            "awayTeam": away,
            "stage": stage,
            "datetime": kickoff_iso,
            "venue": fact.get("venue"),
            "matchday": fact.get("matchday"),
            "group": fact.get("group"),
            "groupRound": fact.get("matchday"),
            "providerStatus": status_fact.get("status"),
        },
        "teamData": {
            "home": {
                "fifaRank": fact.get("homeFifaRank") or TEAM_RANK_PROXY.get(home, 80),
                "recentFormScore": home_profile.get("recentFormScore"),
            },
            "away": {
                "fifaRank": fact.get("awayFifaRank") or TEAM_RANK_PROXY.get(away, 80),
                "recentFormScore": away_profile.get("recentFormScore"),
            },
        },
        "understatCoverage": {
            "home": home_profile.get("matchesUsed", 0),
            "away": away_profile.get("matchesUsed", 0),
        },
        "goalData": {
            "home": profile_to_goal_data(home_profile),
            "away": profile_to_goal_data(away_profile),
        },
        "matchContext": f05_context or {
            "groupRound": fact.get("matchday"),
            "homeQualificationStatus": "UNKNOWN",
            "awayQualificationStatus": "UNKNOWN",
            "homeMotivationScore": 2.5,
            "awayMotivationScore": 2.5,
            "homeRotationRisk": 0.0,
            "awayRotationRisk": 0.0,
        },
        "expectedLineup": expected_lineup,
        "featureSnapshotTime": fixture_row["snapshotTime"],
        "inputQuality": {
            "fixture": "STRUCTURED_FACTS",
            "teamStrength": "RANK_PROXY_WHEN_PROVIDER_RANK_MISSING",
            "goals": "HISTORICAL_RESULTS_PROXY",
            "lineup": "OFFICIAL_LINEUPS" if lineup_connected else "NOT_CONNECTED",
            "odds": "MARKET_SNAPSHOT" if odds else "NOT_CONNECTED",
            "tournamentMotivation": "AUTO_F05_PATH_MODEL" if f05_context else "NEUTRAL_DEFAULT",
        },
    }
    if odds:
        payload.update({
            "decimalOdds": odds["decimalOdds"],
            "oddsSnapshotTime": odds["oddsSnapshotTime"],
        })
    return payload, features, odds


def build_real_match(fixture_row, status_row=None, score_row=None, lineup_row=None, sequence_number=None, f05_context=None):
    fact = fixture_row["fact"]
    if fact.get("demoOnly") or fact.get("notOfficialData"):
        return None
    home_name = fact.get("homeTeam")
    away_name = fact.get("awayTeam")
    stage_zh, stage_en = stage_label(fact.get("stage"), fact=fact)
    venue = venue_labels(fact)
    status_fact = (status_row or {}).get("fact") or {}
    status = status_fact.get("status") or fact.get("status")
    score = score_from_row(score_row)
    if not home_name or not away_name:
        label = knockout_placeholder_label(fact.get("stage"), fact.get("providerMatchId"), sequence_number)
        return {
            "id": fact.get("matchId") or fixture_row["matchId"],
            "statusCode": status,
            "statusLabel": status_label(status),
            "statusLabelEn": str(status or "scheduled").replace("_", " ").title(),
            "stageLabel": stage_zh,
            "stageLabelEn": stage_en,
            "kickoffAt": safe_iso(fact.get("kickoffAt")),
            "kickoffLabel": format_kickoff_label(fact.get("kickoffAt")),
            "venueLabel": venue["zh"],
            "venueLabelEn": venue["en"],
            "broadcastNote": "淘汰赛席位暂未由小组排名确定，当前只展示赛程时间与轮次。",
            "broadcastNoteEn": "Knockout slots are not determined by group standings yet; only time and round are shown.",
            "home": placeholder_team(label["zh"], label["short"]),
            "away": placeholder_team("对手待定", "TBD"),
            "displayTitle": label["zh"],
            "displayTitleEn": label["en"],
            "score": score,
            "predictionAvailable": False,
            "sourceBadges": [f"赛程: {fixture_row.get('source') or 'structured facts'}", "对阵: 待小组结果"],
            "sourceBadgesEn": [f"Fixture: {fixture_row.get('source') or 'structured facts'}", "Teams: pending group results"],
            "lineups": {"homeFormation": None, "awayFormation": None, "homePlayers": [], "awayPlayers": []},
            "sourceStatus": {
                "mode": "LIVE_STRUCTURED_FACTS",
                "label": "真实赛程占位",
                "labelEn": "Verified schedule placeholder",
                "tone": "ok",
                "primarySource": fixture_row.get("source"),
                "providerId": fixture_row.get("providerId"),
                "snapshotTime": fixture_row.get("snapshotTime"),
                "fallback": False,
            },
            "predictionPayload": None,
        }

    prediction_payload, features, odds = build_prediction_payload(
        fixture_row,
        status_row=status_row,
        lineup_row=lineup_row,
        f05_context=f05_context,
    )
    lineup_display = lineup_display_from_row(lineup_row)
    lineup_connected = bool(lineup_display["homePlayers"] or lineup_display["awayPlayers"])
    return {
        "id": fact.get("matchId") or fixture_row["matchId"],
        "statusCode": status,
        "statusLabel": status_label(status),
        "statusLabelEn": str(status or "scheduled").replace("_", " ").title(),
        "stageLabel": stage_zh,
        "stageLabelEn": stage_en,
        "kickoffAt": safe_iso(fact.get("kickoffAt")),
        "kickoffLabel": format_kickoff_label(fact.get("kickoffAt")),
        "venueLabel": venue["zh"],
        "venueLabelEn": venue["en"],
        "broadcastNote": "赛程来自结构化事实库；缺失的阵容、真 xG 和部分强度字段会以代理输入降级。",
        "broadcastNoteEn": "Fixture comes from the structured facts store; missing lineup, true xG, and some strength fields degrade to proxy inputs.",
        "home": {**side_team(home_name, fact=fact, side="home"), "form": form_text(features["home"])},
        "away": {**side_team(away_name, fact=fact, side="away"), "form": form_text(features["away"])},
        "score": score,
        "qualificationContext": f05_context,
        "predictionAvailable": True,
        "sourceBadges": [
            f"赛程: {fixture_row.get('source') or 'structured facts'}",
            f"快照: {fixture_row.get('snapshotTime')}",
            "近期状态: 历史赛果代理",
            "阵容: 官方首发" if lineup_connected else "阵容: 未接入",
            "赔率: 已接入快照" if odds else "赔率: 未接入",
            "F05: 自动出线动机",
        ],
        "sourceBadgesEn": [
            f"Fixture: {fixture_row.get('source') or 'structured facts'}",
            f"Snapshot: {fixture_row.get('snapshotTime')}",
            "Form: historical results proxy",
            "Lineup: official starters" if lineup_connected else "Lineup: unavailable",
            "Odds: snapshot connected" if odds else "Odds: unavailable",
            "F05: automatic motivation",
        ],
        "lineups": lineup_display,
        "sourceStatus": {
            "mode": "LIVE_STRUCTURED_FACTS",
            "label": "真实赛程",
            "labelEn": "Verified fixture",
            "tone": "ok",
            "primarySource": fixture_row.get("source"),
            "providerId": fixture_row.get("providerId"),
            "snapshotTime": fixture_row.get("snapshotTime"),
            "fallback": False,
            "caveats": [
                "赛程/开球时间来自结构化事实源。",
                "球队强度、近期状态和进球均值仍含代理输入。",
                "官方首发和实时赔率未接入时不会伪装为真实值。",
            ],
            "caveatsEn": [
                "Fixture and kickoff time come from the structured facts source.",
                "Team strength, recent form, and goal averages still include proxy inputs.",
                "Official lineups and live odds are not presented as real values when unavailable.",
            ],
        },
        "predictionPayload": prediction_payload,
    }


def build_group_rows(rows=None):
    groups = {}
    for row in rows if rows is not None else latest_rows("standings"):
        fact = row["fact"]
        group = fact.get("group") or "未分组"
        groups.setdefault(group, []).append({
            "team": fact.get("team"),
            "teamZh": team_zh(fact.get("team")),
            "position": fact.get("position"),
            "playedGames": fact.get("playedGames"),
            "points": fact.get("points"),
            "goalDifference": fact.get("goalDifference"),
        })
    result = []
    for group, rows in sorted(groups.items()):
        letter = group_letter(group)
        result.append({
            "group": group,
            "label": f"{letter}组" if letter else group,
            "standings": sorted(rows, key=lambda item: (item.get("position") or 99, item.get("team") or "")),
        })
    return result


def build_default_path():
    return [
        {"stage": "GROUP_STAGE", "label": "小组赛", "labelEn": "Group stage", "slots": 48, "advance": "每组前二 + 8个成绩最好第三名", "advanceEn": "Top two in each group plus the eight best third-place teams"},
        {"stage": "ROUND_OF_32", "label": "三十二强", "labelEn": "Round of 32", "slots": 32, "advance": "单场淘汰", "advanceEn": "Single-elimination match"},
        {"stage": "ROUND_OF_16", "label": "十六强", "labelEn": "Round of 16", "slots": 16, "advance": "单场淘汰", "advanceEn": "Single-elimination match"},
        {"stage": "QUARTER_FINAL", "label": "四分之一决赛", "labelEn": "Quarter-final", "slots": 8, "advance": "单场淘汰", "advanceEn": "Single-elimination match"},
        {"stage": "SEMI_FINAL", "label": "半决赛", "labelEn": "Semi-final", "slots": 4, "advance": "胜者进决赛", "advanceEn": "Winners reach the final"},
        {"stage": "FINAL", "label": "决赛", "labelEn": "Final", "slots": 2, "advance": "冠军", "advanceEn": "Champion"},
    ]


def build_fallback_feed():
    sample_matches = copy.deepcopy(FEATURED_MATCHES)
    for match in sample_matches:
        match["isDemoData"] = True
        match["sourceStatus"] = {
            "mode": "FALLBACK_STATIC_SAMPLE",
            "label": "样例数据",
            "labelEn": "Sample data",
            "tone": "warn",
            "fallback": True,
            "primarySource": "local static fallback",
            "snapshotTime": match["predictionPayload"].get("featureSnapshotTime"),
            "caveats": [
                "当前 structured facts store 没有可用真实赛程。",
                "这些比赛仅用于展示页面、预测接口和风险解释。",
                "接入 football-data.org 并完成 worker 同步后会自动替换。",
            ],
            "caveatsEn": [
                "The structured facts store has no verified fixtures available yet.",
                "These matches only demonstrate the page, prediction API, and risk explanation.",
                "They will be replaced after football-data.org sync writes verified facts.",
            ],
        }
        for side in ("homePlayers", "awayPlayers"):
            for player in (match.get("lineups") or {}).get(side) or []:
                player.setdefault("nameZh", PLAYER_TRANSLATIONS_ZH.get(player.get("name"), player.get("name")))
    token_configured = any(os.environ.get(env_name) for env_name in FOOTBALL_DATA_TOKEN_ENVS)
    return {
        "matches": [],
        "sampleMatches": sample_matches,
        "feedStatus": {
            "sourceMode": "FALLBACK_STATIC_SAMPLE",
            "label": "真实赛程未同步",
            "labelEn": "Verified fixtures not synced",
            "ok": False,
            "fallback": True,
            "message": "主赛事列表不会展示样例比赛。当前 structured facts store 没有真实赛程；配置 football-data.org token 并完成同步后才会展示赛事。",
            "messageEn": "The primary fixture list does not show sample matches. Verified fixtures appear only after football-data.org sync writes facts to the store.",
            "primaryBlocker": "FOOTBALL_DATA_ORG_TOKEN_MISSING" if not token_configured else "STRUCTURED_FACTS_EMPTY",
            "requiredEnv": list(FOOTBALL_DATA_TOKEN_ENVS),
            "tokenConfigured": token_configured,
            "factsAvailable": False,
            "apiConnections": api_connection_status(),
        },
        "tournament": {
            "groups": [],
            "path": build_default_path(),
        },
    }


def row_time(row):
    fact = row.get("fact") or {}
    return parse_iso_timestamp(fact.get("kickoffAt")) or datetime.max.replace(tzinfo=timezone.utc)


def build_feed_from_rows(fixture_rows, status_rows, score_rows, lineup_rows, standings_rows, limit=104):
    matches = []
    ordered_fixture_rows = sorted(fixture_rows.values(), key=row_time)
    f05_contexts = auto_f05_contexts(fixture_rows, score_rows)
    for index, fixture_row in enumerate(ordered_fixture_rows, start=1):
        match_id = fixture_row.get("matchId")
        match = build_real_match(
            fixture_row,
            status_row=status_rows.get(match_id),
            score_row=score_rows.get(match_id),
            lineup_row=lineup_rows.get(match_id),
            sequence_number=index,
            f05_context=f05_contexts.get(match_id),
        )
        if match:
            matches.append(match)
    matches.sort(key=lambda item: item.get("kickoffAt") or "")
    matches = matches[:max(1, int(limit))]
    if not matches:
        return None
    snapshot_times = [
        item["sourceStatus"]["snapshotTime"]
        for item in matches
        if item["sourceStatus"].get("snapshotTime")
    ]
    latest_snapshot = max(snapshot_times) if snapshot_times else None
    return {
        "matches": matches,
        "feedStatus": {
            "sourceMode": "LIVE_STRUCTURED_FACTS",
            "label": "真实赛程已同步",
            "labelEn": "Verified fixtures synced",
            "ok": True,
            "fallback": False,
            "message": "赛程、开球时间和状态来自 structured facts store；缺失因子以代理或未接入标识展示。",
            "messageEn": "Fixtures, kickoff time, and status come from the structured facts store; missing factors are shown as proxy or unavailable.",
            "latestSnapshotTime": latest_snapshot,
            "tokenConfigured": any(os.environ.get(env_name) for env_name in FOOTBALL_DATA_TOKEN_ENVS),
            "factsAvailable": True,
            "apiConnections": api_connection_status(),
        },
        "tournament": {
            "groups": build_group_rows(standings_rows),
            "path": build_default_path(),
        },
    }


def build_real_feed(limit=104):
    return build_feed_from_rows(
        latest_rows_by_match("fixtures"),
        latest_rows_by_match("match_status"),
        latest_rows_by_match("scores"),
        latest_rows_by_match("official_lineups"),
        latest_rows("standings"),
        limit=limit,
    )


def payload_rows_by_match(payload, fact_key):
    rows = {}
    snapshot_time = payload.get("snapshotTime")
    provider = payload.get("provider") or {}
    for index, fact in enumerate((payload.get("facts") or {}).get(fact_key) or []):
        match_id = fact.get("matchId")
        if not match_id:
            continue
        rows[match_id] = {
            "factItemId": f"live-api:{fact_key}:{index}",
            "ingestionId": "live-api",
            "factKey": fact_key,
            "itemIndex": index,
            "matchId": match_id,
            "snapshotTime": snapshot_time,
            "source": payload.get("source"),
            "providerId": provider.get("providerId") or FOOTBALL_DATA_ORG_PROVIDER_ID,
            "providerCategory": provider.get("category"),
            "ingestedAt": snapshot_time,
            "createdAt": snapshot_time,
            "fact": fact,
        }
    return rows


def payload_rows(payload, fact_key):
    snapshot_time = payload.get("snapshotTime")
    provider = payload.get("provider") or {}
    rows = []
    for index, fact in enumerate((payload.get("facts") or {}).get(fact_key) or []):
        rows.append({
            "factItemId": f"live-api:{fact_key}:{index}",
            "ingestionId": "live-api",
            "factKey": fact_key,
            "itemIndex": index,
            "matchId": fact.get("matchId"),
            "snapshotTime": snapshot_time,
            "source": payload.get("source"),
            "providerId": provider.get("providerId") or FOOTBALL_DATA_ORG_PROVIDER_ID,
            "providerCategory": provider.get("category"),
            "ingestedAt": snapshot_time,
            "createdAt": snapshot_time,
            "fact": fact,
        })
    return rows


def build_live_api_feed(limit=104):
    now = time.time()
    cached = LIVE_API_FEED_CACHE.get("feed")
    if cached and LIVE_API_FEED_CACHE.get("expiresAt", 0) > now:
        return copy.deepcopy(cached)
    token_configured = any(os.environ.get(env_name) for env_name in FOOTBALL_DATA_TOKEN_ENVS)
    if not token_configured:
        return None
    try:
        payload = fetch_worldcup_structured_facts_payload()
    except FootballDataOrgAdapterError:
        return None
    feed = build_feed_from_rows(
        payload_rows_by_match(payload, "fixtures"),
        payload_rows_by_match(payload, "match_status"),
        payload_rows_by_match(payload, "scores"),
        payload_rows_by_match(payload, "official_lineups"),
        payload_rows(payload, "standings"),
        limit=limit,
    )
    if not feed:
        return None
    feed["feedStatus"]["sourceMode"] = "LIVE_API"
    feed["feedStatus"]["label"] = "真实赛程实时 API"
    feed["feedStatus"]["labelEn"] = "Verified fixtures live API"
    feed["feedStatus"]["message"] = "赛程、比分和状态直接来自 football-data.org；缺失的阵容和部分高级因子会标为未接入。"
    feed["feedStatus"]["messageEn"] = "Fixtures, scores, and status come directly from football-data.org; missing lineups and advanced factors are marked unavailable."
    LIVE_API_FEED_CACHE["feed"] = copy.deepcopy(feed)
    LIVE_API_FEED_CACHE["expiresAt"] = now + LIVE_API_FEED_TTL_SECONDS
    return feed


def get_featured_feed(limit=104):
    feed = build_real_feed(limit=limit)
    if feed:
        return feed
    feed = build_live_api_feed(limit=limit)
    if feed:
        return feed
    return build_fallback_feed()


def get_featured_matches():
    return get_featured_feed()["matches"]
