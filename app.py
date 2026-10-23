import copy
import os

from flask import Flask, jsonify, request
from flask_cors import CORS

from src.calibration import run_split_backtest, run_wc2022_calibration
from src.worldcup import WorldCupPredictor
from src.worldcup.football_data_org_adapter import (
    FOOTBALL_DATA_ORG_PROVIDER_ID,
    FOOTBALL_DATA_ORG_TOKEN_ENV,
    FootballDataOrgAdapterError,
    fetch_worldcup_structured_facts_payload,
)
from src.worldcup.job_queue import (
    JOB_TYPE_F05_MONTE_CARLO,
    JOB_TYPE_ODDS_IMPORT,
    JOB_TYPE_STRUCTURED_FACTS_SYNC,
    JOB_TYPE_T60_LINEUP_RECALC,
    BackgroundJobError,
    background_job_concurrency_limit,
    claim_next_background_job,
    enqueue_background_job,
    get_background_job,
    list_background_jobs,
    mark_background_job_failed,
    mark_background_job_succeeded,
    public_job_summary,
)
from src.worldcup.f05_monte_carlo import F05MonteCarloError, run_f05_monte_carlo
from src.worldcup.consumer_fixtures import get_featured_feed
from src.worldcup.consumer_page import CONSUMER_PAGE_HTML
from src.worldcup.internal_board import INTERNAL_TEST_BOARD_HTML
from src.worldcup.odds_import import import_odds_csv, list_market_odds_snapshots
from src.worldcup.provider_contracts import StructuredFactsPayloadError
from src.worldcup.readiness import build_readiness_report, env_value, worker_auth_state, worker_token_required
from src.worldcup.snapshot import stable_hash
from src.worldcup.snapshot_store import (
    PREMATCH_FINAL,
    SnapshotFreezeError,
    append_prediction_snapshot,
    compare_replay,
    current_utc_iso,
    get_latest_prematch_final,
    get_last_good_prediction_snapshot,
    get_prediction_snapshot,
    is_after_kickoff,
    latest_prediction_snapshot,
    list_prediction_snapshots,
    match_datetime_from_payload,
    snapshot_type_from_request,
)
from src.worldcup.structured_facts_http_provider import (
    StructuredFactsHttpProviderError,
    fetch_validate_and_optionally_ingest_structured_facts,
)
from src.worldcup.structured_facts_store import ingest_structured_facts_payload

app = Flask(__name__)
CORS(app)

predictor = WorldCupPredictor()
PREDICTION_VIEW_CANONICAL_VERSION = 1
ODDS_IMPORT_PATH_ROOT_ENV = "MATCHORACLE_ODDS_IMPORT_PATH_ROOT"
DEFAULT_ODDS_IMPORT_PATH_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "data", "odds"))


def requested_prediction_snapshot_id(payload):
    prediction_card = (payload or {}).get("predictionCard") or {}
    return (
        request.args.get("predictionSnapshotId")
        or (payload or {}).get("predictionSnapshotId")
        or prediction_card.get("predictionSnapshotId")
    )


def attach_prediction_view_model(prediction, source="LIVE", stale=False, reason=None):
    snapshot_id = prediction.get("predictionSnapshotId")
    manifest = prediction.get("predictionManifest") or {}
    market_snapshot_id = snapshot_id if prediction.get("marketAnalysis") else None
    prediction["predictionViewModel"] = {
        "predictionSnapshotId": snapshot_id,
        "canonicalVersion": PREDICTION_VIEW_CANONICAL_VERSION,
        "probabilitySnapshotId": snapshot_id if prediction.get("probabilities") else None,
        "narrativeSnapshotId": snapshot_id if prediction.get("finalRiskNarrative") or prediction.get("verdict") else None,
        "reliabilitySnapshotId": snapshot_id if prediction.get("dataReliability") else None,
        "marketSnapshotId": market_snapshot_id,
        "f05DependencySnapshotId": manifest.get("dependencySnapshotId"),
        "source": source,
        "snapshotConsistency": {
            "status": "FALLBACK" if stale else "CONSISTENT",
            "stale": bool(stale),
            "reason": reason,
        },
    }
    return prediction


def snapshot_serving_metadata(record, reason, stale=False):
    return {
        "reason": reason,
        "snapshotRecordId": record.get("snapshotRecordId"),
        "predictionSnapshotId": record.get("predictionSnapshotId"),
        "snapshotType": record.get("snapshotType"),
        "freezeStatus": record.get("freezeStatus"),
        "frozenAt": record.get("frozenAt"),
        "kickoffAt": record.get("kickoffAt"),
        "savedAt": record.get("savedAt"),
        "stale": bool(stale),
    }


def prediction_from_snapshot_record(record, reason, stale=False):
    prediction = copy.deepcopy(record["prediction"])
    prediction["servedFromSnapshot"] = snapshot_serving_metadata(record, reason, stale=stale)
    if stale:
        prediction["fallback"] = {
            "mode": "LAST_GOOD_SNAPSHOT",
            "reason": reason,
            "servedAt": current_utc_iso(),
            "lastGoodSnapshotId": record.get("predictionSnapshotId"),
            "lastGoodSavedAt": record.get("savedAt"),
        }
    return attach_prediction_view_model(
        prediction,
        source="LAST_GOOD_SNAPSHOT" if stale else "SNAPSHOT",
        stale=stale,
        reason=reason,
    )


def static_fallback_prediction(payload, reason, detail=None):
    payload = payload or {}
    match = payload.get("match") or {}
    match_id = payload.get("matchId", f"{match.get('homeTeam', 'HOME')}-{match.get('awayTeam', 'AWAY')}")
    snapshot_id = "static-" + stable_hash({
        "matchId": match_id,
        "homeTeam": match.get("homeTeam"),
        "awayTeam": match.get("awayTeam"),
        "stage": match.get("stage", "GROUP_STAGE"),
        "reason": "STATIC_FALLBACK",
    })
    prediction = {
        "matchId": match_id,
        "modelVersion": "STATIC_FALLBACK",
        "predictionSnapshotId": snapshot_id,
        "generatedAt": current_utc_iso(),
        "match": {
            "homeTeam": match.get("homeTeam"),
            "awayTeam": match.get("awayTeam"),
            "stage": match.get("stage", "GROUP_STAGE"),
            "datetime": match.get("datetime"),
            "venue": match.get("venue"),
        },
        "verdict": {
            "result": "ABORTED",
            "confidence": "NONE",
            "confidenceScore": 0,
            "executiveSummary": "动态预测暂不可用，且没有可用的 last good snapshot；当前只显示静态降级状态。",
        },
        "canonicalProbability": {
            "status": "FALLBACK_STATIC",
            "source": "STATIC_FALLBACK",
            "probabilities": None,
            "reason": "No live canonical probability is emitted while prediction data is unavailable.",
        },
        "dataReliability": {
            "status": "FATAL",
            "score": 0,
            "lineupReliability": 0,
            "injuryReliability": 0,
            "oddsFreshness": 0,
            "standingsFreshness": 0,
            "sourceConsistency": 0,
            "missingCriticalFields": [],
            "auditEvents": [{
                "level": "FATAL",
                "code": "STATIC_FALLBACK_ACTIVE",
                "message": "动态预测或绑定快照不可用，系统已进入静态降级。",
            }],
        },
        "predictionManifest": {
            "predictionSnapshotId": snapshot_id,
            "modelVersion": "STATIC_FALLBACK",
            "configVersion": "static-fallback-v1",
            "matchId": match_id,
            "activeFactorIds": [],
            "disabledCoreFactorIds": [],
        },
        "riskFlags": ["动态预测不可用，不能输出伪实时概率。"],
        "finalRiskNarrative": {
            "primaryDriver": "DATA_RELIABILITY_FATAL",
            "secondaryDrivers": [],
            "suppressedSignals": [],
            "finalUserHeadline": "动态预测不可用，当前只显示静态降级状态。",
            "userActionHint": "DATA_INCOMPLETE",
        },
        "fallback": {
            "mode": "STATIC_FALLBACK",
            "reason": reason,
            "detail": detail,
            "servedAt": current_utc_iso(),
        },
    }
    return attach_prediction_view_model(prediction, source="STATIC_FALLBACK", stale=True, reason=reason)


def prediction_fallback(payload, reason, detail=None):
    match_id = (payload or {}).get("matchId")
    try:
        last_good = get_last_good_prediction_snapshot(match_id=match_id) if match_id else None
    except Exception:
        last_good = None
    if last_good:
        return prediction_from_snapshot_record(last_good, reason, stale=True)
    return static_fallback_prediction(payload, reason, detail=detail)


def payload_has_values(value):
    if value in (None, "", [], {}):
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(payload_has_values(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(payload_has_values(item) for item in value)
    return True


def background_job_type_for_prediction_payload(payload):
    if payload_has_values((payload or {}).get("actualLineup")):
        return JOB_TYPE_T60_LINEUP_RECALC
    return None


def enqueue_prediction_background_job(job_type, payload, snapshot_type):
    job_payload = {
        "requestPayload": payload,
        "snapshotType": snapshot_type,
    }
    return enqueue_background_job(job_type, job_payload, priority=10)


def worker_request_authorized():
    token = env_value("MATCHORACLE_WORKER_TOKEN")
    if token:
        return request.headers.get("X-MatchOracle-Worker-Token") == token
    if worker_token_required():
        return False
    return request.headers.get("X-MatchOracle-Worker") == "1"


def odds_import_path_root():
    configured = env_value(ODDS_IMPORT_PATH_ROOT_ENV) or DEFAULT_ODDS_IMPORT_PATH_ROOT
    return os.path.abspath(os.path.expanduser(configured))


def validate_odds_import_path(source_path):
    if not isinstance(source_path, str) or not source_path.strip():
        raise BackgroundJobError(
            "ODDS_IMPORT_PATH_INVALID",
            "Odds import path must be a non-empty string.",
        )
    allowed_root = odds_import_path_root()
    normalized_path = os.path.abspath(os.path.expanduser(source_path.strip()))
    try:
        inside_allowed_root = os.path.commonpath([allowed_root, normalized_path]) == allowed_root
    except ValueError:
        inside_allowed_root = False
    if not inside_allowed_root:
        raise BackgroundJobError(
            "ODDS_IMPORT_PATH_NOT_ALLOWED",
            "Odds import path must be under the configured local odds import root.",
            details={"allowedRootEnv": ODDS_IMPORT_PATH_ROOT_ENV},
        )
    if not os.path.isfile(normalized_path):
        raise BackgroundJobError(
            "ODDS_IMPORT_PATH_NOT_FOUND",
            "Odds import path must point to an existing local CSV file.",
        )
    return normalized_path


def read_odds_import_csv(job_payload):
    if job_payload.get("csvText") is not None:
        return job_payload.get("csvText")
    source_path = job_payload.get("path")
    if not source_path:
        raise BackgroundJobError(
            "ODDS_CSV_MISSING",
            "ODDS_IMPORT jobs require csvText or path.",
        )
    with open(validate_odds_import_path(source_path), "r", encoding="utf-8") as handle:
        return handle.read()


def run_odds_import_background_job(job):
    job_payload = job.get("payload") or {}
    result = import_odds_csv(
        read_odds_import_csv(job_payload),
        source_name=job_payload.get("sourceName") or ("local-path-import" if job_payload.get("path") else None),
        known_teams=job_payload.get("knownTeams"),
        team_aliases=job_payload.get("teamAliases"),
    )
    if result["status"] == "REJECTED":
        raise BackgroundJobError(
            "ODDS_CSV_IMPORT_REJECTED",
            "Odds CSV import rejected by schema or row-level validation.",
            details=result,
        )
    return result


def run_f05_monte_carlo_background_job(job):
    try:
        return run_f05_monte_carlo(job.get("payload") or {})
    except F05MonteCarloError as error:
        raise BackgroundJobError(error.code, error.message, details=error.details)


def run_structured_facts_sync_background_job(job):
    job_payload = job.get("payload") or {}
    provider = (env_value("MATCHORACLE_STRUCTURED_FACTS_PROVIDER") or "").strip().lower()
    try:
        if provider == FOOTBALL_DATA_ORG_PROVIDER_ID:
            payload = fetch_worldcup_structured_facts_payload(
                token=env_value("MATCHORACLE_STRUCTURED_FACTS_PROVIDER_TOKEN") or env_value(FOOTBALL_DATA_ORG_TOKEN_ENV),
                base_url=env_value("MATCHORACLE_STRUCTURED_FACTS_API_BASE_URL") or None,
                match_id=job_payload.get("matchId"),
                snapshot_time=job_payload.get("snapshotTime"),
            )
            result = {
                "status": "VALIDATED" if bool(job_payload.get("dryRun")) else "INGESTED",
                "source": payload.get("source"),
                "snapshotTime": payload.get("snapshotTime"),
                "providerId": payload.get("provider", {}).get("providerId"),
                "factKeys": sorted((payload.get("facts") or {}).keys()),
                "factCounts": {key: len(value) for key, value in sorted((payload.get("facts") or {}).items())},
            }
            if not bool(job_payload.get("dryRun")):
                result["ingestion"] = ingest_structured_facts_payload(
                    payload,
                    created_by="background_football_data_org_sync",
                )
            return result
        return fetch_validate_and_optionally_ingest_structured_facts(
            match_id=job_payload.get("matchId"),
            snapshot_time=job_payload.get("snapshotTime"),
            dry_run=bool(job_payload.get("dryRun")),
            created_by="background_structured_facts_sync",
        )
    except FootballDataOrgAdapterError as error:
        raise BackgroundJobError(error.code, error.message, details=error.details)
    except StructuredFactsHttpProviderError as error:
        raise BackgroundJobError(error.code, error.message, details=error.details)
    except StructuredFactsPayloadError as error:
        raise BackgroundJobError(error.code, error.message, details=error.details)


def run_prediction_background_job(job):
    if job.get("jobType") == JOB_TYPE_ODDS_IMPORT:
        return run_odds_import_background_job(job)
    if job.get("jobType") == JOB_TYPE_F05_MONTE_CARLO:
        return run_f05_monte_carlo_background_job(job)
    if job.get("jobType") == JOB_TYPE_STRUCTURED_FACTS_SYNC:
        return run_structured_facts_sync_background_job(job)
    if job.get("jobType") != JOB_TYPE_T60_LINEUP_RECALC:
        raise BackgroundJobError(
            "BACKGROUND_JOB_HANDLER_NOT_IMPLEMENTED",
            f"No handler is implemented for {job.get('jobType')}.",
        )
    job_payload = job.get("payload") or {}
    request_payload = job_payload.get("requestPayload") or {}
    snapshot_type = snapshot_type_from_request(request_payload, job_payload.get("snapshotType"))
    match_id = request_payload.get("matchId")

    if is_after_kickoff(match_datetime_from_payload(request_payload)):
        frozen_record = get_latest_prematch_final(match_id) if match_id else None
        if frozen_record:
            return {
                "skipped": True,
                "reason": "PREMATCH_FINAL_ALREADY_FROZEN",
                "servedSnapshot": snapshot_serving_metadata(
                    frozen_record,
                    "PREMATCH_FINAL_FROZEN_AFTER_KICKOFF",
                ),
            }
        raise SnapshotFreezeError(
            "PREMATCH_JOB_CUTOFF_PASSED",
            "Prematch background jobs must persist snapshots before kickoff.",
        )

    prediction = predictor.predict(request_payload)
    attach_prediction_view_model(prediction, source="BACKGROUND_JOB")
    record = append_prediction_snapshot(
        prediction,
        request_payload=request_payload,
        snapshot_type=snapshot_type,
    )
    return {
        "skipped": False,
        "predictionSnapshotId": prediction.get("predictionSnapshotId"),
        "savedSnapshot": {key: value for key, value in record.items() if key != "prediction"},
    }


@app.route("/", methods=["GET"])
def consumer_home_page():
    return CONSUMER_PAGE_HTML


@app.route("/manual", methods=["GET"])
def manual_page():
    return """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>World Cup Probability Dashboard V4-P0</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #18202a;
      --muted: #5d6876;
      --line: #d9dee7;
      --accent: #0d6efd;
      --accent-dark: #084db4;
      --good: #0a7d42;
      --warn: #aa6708;
      --bad: #b42318;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
    }
    header {
      padding: 28px 24px 18px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }
    main {
      max-width: 1120px;
      margin: 0 auto;
      padding: 24px;
    }
    h1 {
      margin: 0 0 6px;
      font-size: 28px;
      letter-spacing: 0;
    }
    h2 {
      margin: 0 0 16px;
      font-size: 20px;
    }
    p {
      margin: 0;
      color: var(--muted);
    }
    .tabs {
      display: flex;
      gap: 8px;
      margin-bottom: 18px;
      flex-wrap: wrap;
    }
    button {
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--ink);
      padding: 10px 14px;
      border-radius: 8px;
      font-size: 15px;
      cursor: pointer;
    }
    button.primary, button.active {
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }
    button.primary:hover, button.active:hover {
      background: var(--accent-dark);
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 20px;
      margin-bottom: 18px;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }
    label {
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 14px;
    }
    input, select, textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px 12px;
      font-size: 15px;
      color: var(--ink);
      background: #fff;
    }
    textarea {
      min-height: 96px;
      resize: vertical;
    }
    .metrics {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-top: 12px;
    }
    .metric {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      background: #fbfcfe;
    }
    .metric strong {
      display: block;
      font-size: 24px;
      margin-bottom: 3px;
    }
    .result-layout {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }
    .bar {
      height: 12px;
      background: #e9edf3;
      border-radius: 999px;
      overflow: hidden;
      margin: 8px 0 12px;
    }
    .bar span {
      display: block;
      height: 100%;
      background: var(--accent);
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }
    th, td {
      text-align: left;
      border-bottom: 1px solid var(--line);
      padding: 10px 8px;
      vertical-align: top;
    }
    th {
      color: var(--muted);
      font-weight: 600;
    }
    .hidden { display: none; }
    .note {
      padding: 12px 14px;
      background: #fff8e6;
      border: 1px solid #f0d48a;
      border-radius: 8px;
      color: #5d4300;
      margin-bottom: 18px;
    }
    .pill {
      display: inline-block;
      padding: 3px 8px;
      border-radius: 999px;
      background: #eef4ff;
      color: #084db4;
      font-size: 13px;
    }
    .good { color: var(--good); }
    .warn { color: var(--warn); }
    .bad { color: var(--bad); }
    @media (max-width: 760px) {
      main { padding: 16px; }
      .grid, .metrics, .result-layout { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <h1>World Cup Probability Dashboard V4-P0</h1>
    <p>概率模型 + 数据可靠性 + 首发异动解释。当前仍是本地MVP界面，不需要付费API。</p>
  </header>
  <main>
    <div class="note">For sports data research and entertainment only. This is not betting, financial, or investment advice. No guarantee of accuracy, profit, or outcome. We do not accept wagers or facilitate betting transactions.</div>
    <div class="note">V4-P0 已加入 Data Reliability 熔断、Canonical Probability、Prediction Manifest 和 Tier-based Lineup Shock。高级输入可手动填写，暂不需要任何付费API。</div>

    <div class="tabs">
      <button id="tabPredict" class="active" onclick="showTab('predict')">单场预测</button>
      <button id="tabCalibration" onclick="showTab('calibration')">2022校准报告</button>
    </div>

    <section id="predictPanel">
      <h2>单场预测</h2>
      <div class="grid">
        <label>主队名称 <input id="homeTeam" value="Argentina"></label>
        <label>客队名称 <input id="awayTeam" value="France"></label>
        <label>比赛阶段
          <select id="stage">
            <option value="GROUP_STAGE">小组赛</option>
            <option value="ROUND_OF_32">1/16决赛 / Round of 32</option>
            <option value="ROUND_OF_16">1/8决赛 / Round of 16</option>
            <option value="QUARTER_FINAL">1/4决赛</option>
            <option value="SEMI_FINAL">半决赛</option>
            <option value="FINAL" selected>决赛</option>
          </select>
        </label>
        <label>比赛场馆 <input id="venue" value="MetLife Stadium"></label>
        <label>主队FIFA排名 <input id="homeRank" type="number" value="3"></label>
        <label>客队FIFA排名 <input id="awayRank" type="number" value="4"></label>
        <label>主队门将评分 0-100（可选） <input id="homeGoalkeeperScore" type="number" step="1" value=""></label>
        <label>客队门将评分 0-100（可选） <input id="awayGoalkeeperScore" type="number" step="1" value=""></label>
        <label>主队赛制动机 -5到+5（可选） <input id="homeMotivationScore" type="number" step="0.5" value=""></label>
        <label>客队赛制动机 -5到+5（可选） <input id="awayMotivationScore" type="number" step="0.5" value=""></label>
        <label>主队轮换风险 0-1（可选） <input id="homeRotationRisk" type="number" step="0.1" value=""></label>
        <label>客队轮换风险 0-1（可选） <input id="awayRotationRisk" type="number" step="0.1" value=""></label>
        <label>主队预计阵型 <input id="homeFormation" value="4-3-3" placeholder="例如 4-3-3"></label>
        <label>客队预计阵型 <input id="awayFormation" value="4-2-3-1" placeholder="例如 4-2-3-1"></label>
        <label>主队阵容连续性 0-100（可选） <input id="homeContinuityScore" type="number" step="1" value=""></label>
        <label>客队阵容连续性 0-100（可选） <input id="awayContinuityScore" type="number" step="1" value=""></label>
        <label>主队替补席强度 0-100（可选） <input id="homeBenchStrength" type="number" step="1" value=""></label>
        <label>客队替补席强度 0-100（可选） <input id="awayBenchStrength" type="number" step="1" value=""></label>
        <label>主队点球大战准备度 0-100（淘汰赛可选） <input id="homePenaltyReadiness" type="number" step="1" value=""></label>
        <label>客队点球大战准备度 0-100（淘汰赛可选） <input id="awayPenaltyReadiness" type="number" step="1" value=""></label>
        <label>主队近10场场均进球 <input id="homeGoalsAvg" type="number" step="0.1" value="1.8"></label>
        <label>客队近10场场均进球 <input id="awayGoalsAvg" type="number" step="0.1" value="1.7"></label>
        <label>主队场均失球/xGA <input id="homeXga" type="number" step="0.1" value="0.9"></label>
        <label>客队场均失球/xGA <input id="awayXga" type="number" step="0.1" value="1.0"></label>
        <label>主队定位球依赖度
          <select id="homeSetpiece">
            <option value="0.25" selected>不确定/正常</option>
            <option value="0.12">低：主要靠运动战</option>
            <option value="0.35">较高：经常靠角球/任意球制造威胁</option>
            <option value="0.45">高：明显依赖定位球得分</option>
          </select>
        </label>
        <label>客队定位球依赖度
          <select id="awaySetpiece">
            <option value="0.25" selected>不确定/正常</option>
            <option value="0.12">低：主要靠运动战</option>
            <option value="0.35">较高：经常靠角球/任意球制造威胁</option>
            <option value="0.45">高：明显依赖定位球得分</option>
          </select>
        </label>
        <label>当前主胜欧洲赔率 <input id="homeOdds" type="number" step="0.01" value=""></label>
        <label>当前平局欧洲赔率 <input id="drawOdds" type="number" step="0.01" value=""></label>
        <label>当前客胜欧洲赔率 <input id="awayOdds" type="number" step="0.01" value=""></label>
        <label>开盘主胜赔率（可选） <input id="openingHomeOdds" type="number" step="0.01" value=""></label>
        <label>开盘平局赔率（可选） <input id="openingDrawOdds" type="number" step="0.01" value=""></label>
        <label>开盘客胜赔率（可选） <input id="openingAwayOdds" type="number" step="0.01" value=""></label>
        <label>公众买主胜比例%（可选） <input id="publicHome" type="number" step="1" value=""></label>
        <label>公众买平局比例%（可选） <input id="publicDraw" type="number" step="1" value=""></label>
        <label>公众买客胜比例%（可选） <input id="publicAway" type="number" step="1" value=""></label>
      </div>
      <h2 style="margin-top:22px;">赛前60分钟最终校验（可选）</h2>
      <p style="margin-bottom:12px;">如果临场首发公布了，可以填这里。系统会检查预计首发和实际首发偏差，偏差过大会下调置信度。</p>
      <div class="grid">
        <label>预计主队阵型 <input id="expectedHomeFormation" placeholder="例如 4-3-3"></label>
        <label>实际主队阵型 <input id="actualHomeFormation" placeholder="例如 5-4-1"></label>
        <label>预计客队阵型 <input id="expectedAwayFormation" placeholder="例如 4-2-3-1"></label>
        <label>实际客队阵型 <input id="actualAwayFormation" placeholder="例如 4-4-2"></label>
        <label>预计主队关键球员（每行：姓名|TIER_1|ATTACKER） <textarea id="expectedHomeKeyPlayers" placeholder="H9|TIER_1|ATTACKER&#10;H1|TIER_1|GOALKEEPER"></textarea></label>
        <label>预计客队关键球员（每行：姓名|TIER_1|CENTER_BACK） <textarea id="expectedAwayKeyPlayers" placeholder="A5|TIER_1|CENTER_BACK"></textarea></label>
        <label>预计主队首发（每行或逗号分隔） <textarea id="expectedHomeStarters"></textarea></label>
        <label>实际主队首发（每行或逗号分隔） <textarea id="actualHomeStarters"></textarea></label>
        <label>预计客队首发（每行或逗号分隔） <textarea id="expectedAwayStarters"></textarea></label>
        <label>实际客队首发（每行或逗号分隔） <textarea id="actualAwayStarters"></textarea></label>
      </div>
      <p style="margin:14px 0 0;">不知道的数据先留空即可。赔率可以从任意比分/盘口网站手动复制；不填赔率时，系统只做模型预测，不做市场分歧/EV分析。</p>
      <div style="margin-top:16px;">
        <button class="primary" onclick="runPrediction()">生成预测</button>
      </div>
    </section>

    <section id="predictionResult" class="hidden"></section>

    <section id="calibrationPanel" class="hidden">
      <h2>2022世界杯校准报告</h2>
      <p>这个报告不是为了背历史答案，而是检查模型有没有过度自信、平局偏差、比分偏大等问题。</p>
      <div style="margin-top:16px;">
        <button class="primary" onclick="loadCalibration()">查看校准报告</button>
      </div>
      <div id="calibrationResult"></div>
    </section>
  </main>

  <script>
    function showTab(name) {
      document.getElementById('predictPanel').classList.toggle('hidden', name !== 'predict');
      document.getElementById('predictionResult').classList.toggle('hidden', name !== 'predict');
      document.getElementById('calibrationPanel').classList.toggle('hidden', name !== 'calibration');
      document.getElementById('tabPredict').classList.toggle('active', name === 'predict');
      document.getElementById('tabCalibration').classList.toggle('active', name === 'calibration');
    }

    function num(id) {
      return Number(document.getElementById(id).value);
    }

    function optionalNum(id) {
      const value = document.getElementById(id).value;
      return value === '' ? null : Number(value);
    }

    function textValue(id) {
      return document.getElementById(id).value.trim();
    }

    function splitNames(value) {
      return value.split(/[,\\n]/).map(item => item.trim()).filter(Boolean);
    }

    function splitKeyPlayers(value) {
      return value.split(/\\n/).map(line => {
        const parts = line.split('|').map(item => item.trim()).filter(Boolean);
        if (!parts.length) return null;
        return {
          name: parts[0],
          tier: parts[1] || 'UNKNOWN',
          role: parts[2] || 'UNKNOWN'
        };
      }).filter(Boolean);
    }

    function resultCn(result) {
      return { HOME_WIN: '主队胜', DRAW: '平局', AWAY_WIN: '客队胜' }[result] || result;
    }

    function confidenceCn(value) {
      return { HIGH: '高', MEDIUM: '中', LOW: '低' }[value] || value;
    }

    function demoKickoffTime() {
      return new Date(Date.now() + 60 * 60 * 1000).toISOString();
    }

    async function runPrediction() {
      try {
        const payload = {
          matchId: 'manual-demo',
          match: {
            homeTeam: document.getElementById('homeTeam').value,
            awayTeam: document.getElementById('awayTeam').value,
            stage: document.getElementById('stage').value,
            datetime: demoKickoffTime(),
            venue: document.getElementById('venue').value
          },
          teamData: {
            home: { fifaRank: num('homeRank') },
            away: { fifaRank: num('awayRank') }
          },
          understatCoverage: { home: 0, away: 0 },
          formationData: {
            home: textValue('homeFormation'),
            away: textValue('awayFormation')
          },
          goalkeeperData: {
            home: { score: optionalNum('homeGoalkeeperScore') },
            away: { score: optionalNum('awayGoalkeeperScore') }
          },
          matchContext: {
            homeMotivationScore: optionalNum('homeMotivationScore'),
            awayMotivationScore: optionalNum('awayMotivationScore'),
            homeRotationRisk: optionalNum('homeRotationRisk'),
            awayRotationRisk: optionalNum('awayRotationRisk')
          },
          tacticalData: {
            homeContinuityScore: optionalNum('homeContinuityScore'),
            awayContinuityScore: optionalNum('awayContinuityScore')
          },
          depthData: {
            home: {
              benchStrength: optionalNum('homeBenchStrength'),
              penaltyReadiness: optionalNum('homePenaltyReadiness')
            },
            away: {
              benchStrength: optionalNum('awayBenchStrength'),
              penaltyReadiness: optionalNum('awayPenaltyReadiness')
            }
          },
          goalData: {
            home: { actualGoals_avg: num('homeGoalsAvg'), xGA_avg: num('homeXga'), setpieceRate: num('homeSetpiece') },
            away: { actualGoals_avg: num('awayGoalsAvg'), xGA_avg: num('awayXga'), setpieceRate: num('awaySetpiece') }
          }
        };
        const homeOdds = document.getElementById('homeOdds').value;
        const drawOdds = document.getElementById('drawOdds').value;
        const awayOdds = document.getElementById('awayOdds').value;
        if (homeOdds && drawOdds && awayOdds) {
          payload.decimalOdds = {
            home: Number(homeOdds),
            draw: Number(drawOdds),
            away: Number(awayOdds)
          };
        }
        const openingHomeOdds = document.getElementById('openingHomeOdds').value;
        const openingDrawOdds = document.getElementById('openingDrawOdds').value;
        const openingAwayOdds = document.getElementById('openingAwayOdds').value;
        if (openingHomeOdds && openingDrawOdds && openingAwayOdds) {
          payload.openingDecimalOdds = {
            home: Number(openingHomeOdds),
            draw: Number(openingDrawOdds),
            away: Number(openingAwayOdds)
          };
        }
        const publicHome = optionalNum('publicHome');
        const publicDraw = optionalNum('publicDraw');
        const publicAway = optionalNum('publicAway');
        if (publicHome !== null || publicDraw !== null || publicAway !== null) {
          payload.publicTicketPercent = {
            home: publicHome || 0,
            draw: publicDraw || 0,
            away: publicAway || 0
          };
        }
        const expectedHomeStarters = splitNames(textValue('expectedHomeStarters'));
        const expectedAwayStarters = splitNames(textValue('expectedAwayStarters'));
        const actualHomeStarters = splitNames(textValue('actualHomeStarters'));
        const actualAwayStarters = splitNames(textValue('actualAwayStarters'));
        const expectedHomeKeyPlayers = splitKeyPlayers(textValue('expectedHomeKeyPlayers'));
        const expectedAwayKeyPlayers = splitKeyPlayers(textValue('expectedAwayKeyPlayers'));
        if (expectedHomeStarters.length || expectedAwayStarters.length || expectedHomeKeyPlayers.length || expectedAwayKeyPlayers.length || textValue('expectedHomeFormation') || textValue('expectedAwayFormation')) {
          payload.expectedLineup = {
            homeFormation: textValue('expectedHomeFormation'),
            awayFormation: textValue('expectedAwayFormation'),
            homeStarters: expectedHomeStarters,
            awayStarters: expectedAwayStarters,
            homeKeyPlayers: expectedHomeKeyPlayers,
            awayKeyPlayers: expectedAwayKeyPlayers
          };
        }
        if (actualHomeStarters.length || actualAwayStarters.length || textValue('actualHomeFormation') || textValue('actualAwayFormation')) {
          payload.actualLineup = {
            homeFormation: textValue('actualHomeFormation'),
            awayFormation: textValue('actualAwayFormation'),
            homeStarters: actualHomeStarters,
            awayStarters: actualAwayStarters
          };
        }
        const response = await fetch('/api/predict', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        if (!response.ok) {
          throw new Error(`接口返回 ${response.status}`);
        }
        const data = await response.json();
        renderPrediction(data);
      } catch (error) {
        renderError(error);
      }
    }

    function outcomeCn(key) {
      return { home: '主胜', draw: '平局', away: '客胜' }[key] || key;
    }

    function ratingCn(value) {
      return {
        VALUE: '正EV，存在市场分歧',
        LEAN_VALUE: '轻微正EV，可观察',
        FAIR: '接近合理',
        NO_VALUE: '无价值'
      }[value] || value;
    }

    function reliabilityClass(status) {
      if (status === 'FATAL' || status === 'CRITICAL') return 'bad';
      if (status === 'WARN') return 'warn';
      return 'good';
    }

    function renderDataReliability(data) {
      const reliability = data.dataReliability;
      if (!reliability) return '';
      const events = reliability.auditEvents || [];
      const eventRows = events.length ? events.map(event => `
        <tr><td>${event.level}</td><td>${event.code}</td><td>${event.message}</td></tr>
      `).join('') : '<tr><td colspan="3">暂无数据质量警报</td></tr>';
      return `
        <h2 style="margin-top:20px;">Data Reliability</h2>
        <div class="metrics">
          <div class="metric"><strong class="${reliabilityClass(reliability.status)}">${reliability.status}</strong><span>数据状态</span></div>
          <div class="metric"><strong>${reliability.score}</strong><span>可靠性分</span></div>
          <div class="metric"><strong>${reliability.lineupReliability}</strong><span>首发可靠性</span></div>
          <div class="metric"><strong>${reliability.oddsFreshness}</strong><span>赔率新鲜度</span></div>
        </div>
        <table style="margin-top:10px;">
          <thead><tr><th>级别</th><th>代码</th><th>说明</th></tr></thead>
          <tbody>${eventRows}</tbody>
        </table>
      `;
    }

    function renderCanonicalProbability(data) {
      const canonical = data.canonicalProbability;
      if (!canonical) return '';
      if (canonical.status === 'ABORTED' || canonical.status === 'FALLBACK_STATIC' || !canonical.probabilities && !data.probabilities) {
        return `<p style="margin-top:12px;color:var(--bad);">Canonical Probability 已阻断：${canonical.reason}</p>`;
      }
      const p = canonical.probabilities || data.probabilities;
      return `
        <h2 style="margin-top:20px;">Canonical Probability</h2>
        <p>用户默认应读取这一组概率。来源：${canonical.source}。${canonical.reason}</p>
        <div class="metrics">
          <div class="metric"><strong>${Math.round(p.home * 100)}%</strong><span>主胜</span></div>
          <div class="metric"><strong>${Math.round(p.draw * 100)}%</strong><span>平局</span></div>
          <div class="metric"><strong>${Math.round(p.away * 100)}%</strong><span>客胜</span></div>
          <div class="metric"><strong>${canonical.status}</strong><span>状态</span></div>
        </div>
      `;
    }

    function actionHintCn(action) {
      return {
        READ_WITH_CAUTION: '谨慎解读',
        WAIT_FOR_LINEUP: '等待官方首发',
        DATA_INCOMPLETE: '补齐关键数据',
        MARKET_MOVED: '复核市场变化',
        NO_ACTION: '无需额外动作'
      }[action] || action || '无需额外动作';
    }

    function renderFinalRiskNarrative(data) {
      const narrative = data.finalRiskNarrative;
      if (!narrative) return '';
      const secondary = narrative.secondaryDrivers || [];
      const suppressed = narrative.suppressedSignals || [];
      return `
        <h2 style="margin-top:20px;">风险叙事</h2>
        <div class="metrics">
          <div class="metric"><strong>${narrative.primaryDriver}</strong><span>主因</span></div>
          <div class="metric"><strong>${secondary.length}</strong><span>次因数量</span></div>
          <div class="metric"><strong>${suppressed.length}</strong><span>折叠信号</span></div>
          <div class="metric"><strong>${actionHintCn(narrative.userActionHint)}</strong><span>动作提示</span></div>
        </div>
        <p style="margin-top:10px;">${narrative.finalUserHeadline}</p>
        ${secondary.length ? `<p style="margin-top:8px;">次因：${secondary.join('，')}</p>` : ''}
      `;
    }

    function renderUpsetRisk(data) {
      const risk = data.upsetRisk;
      if (!risk) return '';
      const triggers = risk.triggers || [];
      const triggerRows = triggers.length ? triggers.map(item => `
        <tr><td>${item.code}</td><td>${Math.round((item.weight || 0) * 100)}</td><td>${item.message || ''}</td></tr>
      `).join('') : '<tr><td colspan="3">暂无显著爆冷触发项</td></tr>';
      const levelClass = risk.upsetRiskLevel === 'HIGH' ? 'bad' : risk.upsetRiskLevel === 'MEDIUM' ? 'warn' : 'good';
      return `
        <h2 style="margin-top:20px;">爆冷风险层</h2>
        <div class="metrics">
          <div class="metric"><strong class="${levelClass}">${risk.upsetRiskLevel}</strong><span>风险等级</span></div>
          <div class="metric"><strong>${Math.round((risk.upsetRiskScore || 0) * 100)}</strong><span>风险分</span></div>
          <div class="metric"><strong>${risk.favoriteTeam || '-'}</strong><span>热门方</span></div>
          <div class="metric"><strong>${risk.underdogTeam || '-'}</strong><span>弱势方</span></div>
        </div>
        <p style="margin-top:10px;">${risk.explanation}</p>
        <table style="margin-top:10px;">
          <thead><tr><th>触发项</th><th>权重</th><th>说明</th></tr></thead>
          <tbody>${triggerRows}</tbody>
        </table>
      `;
    }

    function renderBackgroundExecution(data) {
      const execution = data.backgroundExecution;
      const job = data.queuedJob;
      if (!execution && !job) return '';
      return `
        <h2 style="margin-top:20px;">后台任务状态</h2>
        <div id="backgroundJobStatus">
          <div class="metrics">
            <div class="metric"><strong>${execution ? execution.status : '-'}</strong><span>执行状态</span></div>
            <div class="metric"><strong>${job ? job.jobType : '-'}</strong><span>任务类型</span></div>
            <div class="metric"><strong>${job ? job.status : '-'}</strong><span>队列状态</span></div>
            <div class="metric"><strong>${job ? job.jobId : '-'}</strong><span>任务ID</span></div>
          </div>
          ${execution && execution.reason ? `<p style="margin-top:10px;">${execution.reason}</p>` : ''}
          ${job ? '<p style="margin-top:10px;">后台任务已排队；页面会轮询任务状态，worker 完成后自动加载最新快照。</p>' : ''}
        </div>
      `;
    }

    function updateBackgroundJobStatus(job, message) {
      const status = document.getElementById('backgroundJobStatus');
      if (!status || !job) return;
      status.innerHTML = `
        <div class="metrics">
          <div class="metric"><strong>${job.status || '-'}</strong><span>执行状态</span></div>
          <div class="metric"><strong>${job.jobType || '-'}</strong><span>任务类型</span></div>
          <div class="metric"><strong>${job.status || '-'}</strong><span>队列状态</span></div>
          <div class="metric"><strong>${job.jobId || '-'}</strong><span>任务ID</span></div>
        </div>
        <p style="margin-top:10px;">${message}</p>
      `;
    }

    function scheduleBackgroundJobPoll(data, attempt = 0) {
      const job = data.queuedJob;
      if (!job || !job.jobId || attempt >= 30) return;
      window.setTimeout(async () => {
        try {
          const response = await fetch(`/api/jobs/${job.jobId}`);
          const latestJob = await response.json();
          if (!response.ok || latestJob.error) {
            updateBackgroundJobStatus(job, latestJob.error || `任务状态查询失败：${response.status}`);
            return;
          }
          updateBackgroundJobStatus(latestJob, `后台任务状态：${latestJob.status}`);
          if (latestJob.status === 'SUCCEEDED' && latestJob.result && latestJob.result.predictionSnapshotId) {
            const snapshotResponse = await fetch(`/api/snapshots/${latestJob.result.predictionSnapshotId}`);
            const snapshotRecord = await snapshotResponse.json();
            if (snapshotResponse.ok && snapshotRecord.prediction) {
              renderPrediction(snapshotRecord.prediction);
            }
            return;
          }
          if (latestJob.status === 'FAILED') {
            updateBackgroundJobStatus(latestJob, latestJob.error ? JSON.stringify(latestJob.error) : '后台任务失败。');
            return;
          }
          scheduleBackgroundJobPoll({ queuedJob: latestJob }, attempt + 1);
        } catch (error) {
          updateBackgroundJobStatus(job, `任务状态查询失败：${error.message || error}`);
        }
      }, 1500);
    }

    function renderAbortedPrediction(data) {
      const panel = document.getElementById('predictionResult');
      panel.classList.remove('hidden');
      panel.innerHTML = `
        <h2>预测已熔断</h2>
        <p>${data.verdict.executiveSummary}</p>
        ${renderBackgroundExecution(data)}
        ${renderDataReliability(data)}
        ${renderCanonicalProbability(data)}
        ${renderFinalRiskNarrative(data)}
        ${renderUpsetRisk(data)}
      `;
      scheduleBackgroundJobPoll(data);
      window.scrollTo({ top: panel.offsetTop - 12, behavior: 'smooth' });
    }

    function renderMarket(data) {
      const market = data.marketAnalysis;
      if (!market) {
        return '<p style="margin-top:12px;">未填写赔率，因此暂不计算市场概率和EV。</p>';
      }
      const alignment = market.temporalAlignment;
      const alignmentNote = alignment && !alignment.divergenceEnabled
        ? `<p style="margin-top:10px;color:var(--bad);">Market Divergence 已禁用：${alignment.reason}。模型特征与赔率时间轴未对齐，避免产生假分歧。</p>`
        : '';
      const rows = ['home', 'draw', 'away'].map(key => {
        const value = market.valueBets[key];
        const marketProb = market.probabilities[key] || 0;
        const edge = market.edges[key] || 0;
        return `
          <tr>
            <td>${outcomeCn(key)}</td>
            <td>${Math.round(value.modelProbability * 1000) / 10}%</td>
            <td>${Math.round(marketProb * 1000) / 10}%</td>
            <td>${value.odds}</td>
            <td>${edge >= 0 ? '+' : ''}${Math.round(edge * 1000) / 10}%</td>
            <td>${value.evPercent >= 0 ? '+' : ''}${value.evPercent}%</td>
            <td>${ratingCn(value.rating)}</td>
          </tr>
        `;
      }).join('');
      return `
        <h2 style="margin-top:20px;">市场分歧 / EV 分析</h2>
        <p>去水后市场概率已自动计算。EV = 模型概率 × 欧洲赔率 - 1。这里只表示模型与市场的概率差，不构成下注建议。</p>
        <table style="margin-top:10px;">
          <thead><tr><th>结果</th><th>模型概率</th><th>市场概率</th><th>赔率</th><th>概率差</th><th>EV</th><th>判断</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
        ${alignmentNote}
        <p style="margin-top:10px;">最大EV分歧方向：${outcomeCn(market.bestValue.outcome)}，EV ${market.bestValue.evPercent >= 0 ? '+' : ''}${market.bestValue.evPercent}%。市场抽水约 ${Math.round(market.overround * 1000) / 10}%。</p>
        ${renderLineMovement(market)}
      `;
    }

    function renderLineMovement(market) {
      if (!market.lineMovement) {
        return '<p style="margin-top:10px;">未填写开盘赔率，因此暂不计算盘口移动。</p>';
      }
      const rows = ['home', 'draw', 'away'].map(key => {
        const move = market.lineMovement.movement[key];
        return `
          <tr>
            <td>${outcomeCn(key)}</td>
            <td>${move.openingOdds}</td>
            <td>${move.currentOdds}</td>
            <td>${move.probabilityDelta >= 0 ? '+' : ''}${Math.round(move.probabilityDelta * 1000) / 10}%</td>
          </tr>
        `;
      }).join('');
      const rlm = market.reverseLineMovement;
      return `
        <h2 style="margin-top:20px;">盘口走势</h2>
        <table style="margin-top:10px;">
          <thead><tr><th>结果</th><th>开盘赔率</th><th>当前赔率</th><th>市场概率变化</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
        <p style="margin-top:10px;">最大变化方向：${outcomeCn(market.lineMovement.strongestMove.outcome)}，变化 ${market.lineMovement.strongestMove.probabilityDelta >= 0 ? '+' : ''}${Math.round(market.lineMovement.strongestMove.probabilityDelta * 1000) / 10}%。${rlm ? ' RLM判断：' + rlm.reason : ''}</p>
      `;
    }

    function renderLineupCheck(data) {
      const check = data.finalLineupCheck;
      if (!check || !check.available) {
        return '<p style="margin-top:12px;">未填写赛前60分钟首发校验信息。</p>';
      }
      const shock = check.lineupShock || {};
      const absences = shock.absences || [];
      const absenceRows = absences.length ? absences.map(item => `
        <tr>
          <td>${item.teamSide}</td>
          <td>${item.name}</td>
          <td>${item.tier}</td>
          <td>${item.role}</td>
          <td>${item.lambdaMultiplier || '仅降置信度'}</td>
        </tr>
      `).join('') : '<tr><td colspan="5">未发现可量化的 Tier-based Lineup Shock</td></tr>';
      return `
        <h2 style="margin-top:20px;">赛前60分钟最终校验</h2>
        <table>
          <tbody>
            <tr><td>主队首发偏差</td><td>${check.homeChangedPlayers}人，${Math.round(check.homeChangeRate * 1000) / 10}%</td></tr>
            <tr><td>客队首发偏差</td><td>${check.awayChangedPlayers}人，${Math.round(check.awayChangeRate * 1000) / 10}%</td></tr>
            <tr><td>主队阵型变化</td><td>${check.homeFormationChanged ? '是' : '否'}</td></tr>
            <tr><td>客队阵型变化</td><td>${check.awayFormationChanged ? '是' : '否'}</td></tr>
            <tr><td>置信度扣分</td><td>${check.confidencePenalty}</td></tr>
            <tr><td>Lineup Shock</td><td>${shock.applied ? '已触发' : '未触发'}</td></tr>
            <tr><td>主队lambda乘数</td><td>${shock.homeMultiplier || 1}</td></tr>
            <tr><td>客队lambda乘数</td><td>${shock.awayMultiplier || 1}</td></tr>
          </tbody>
        </table>
        <table style="margin-top:10px;">
          <thead><tr><th>球队侧</th><th>球员</th><th>Tier</th><th>角色</th><th>lambda乘数</th></tr></thead>
          <tbody>${absenceRows}</tbody>
        </table>
      `;
    }

    function renderCompetitionRules(data) {
      const rules = data.competitionRules;
      const layers = data.predictionLayers || {};
      const extraTime = layers.extraTime;
      const penalties = layers.penalties;
      const advancement = layers.advancement;
      if (!rules) {
        return '';
      }
      const advancementHtml = advancement ? `
        <table style="margin-top:10px;">
          <thead><tr><th>淘汰赛路径层</th><th>概率</th></tr></thead>
          <tbody>
            <tr><td>进入加时赛</td><td>${Math.round(extraTime.entryProbability * 1000) / 10}%</td></tr>
            <tr><td>进入点球大战</td><td>${Math.round(penalties.entryProbability * 1000) / 10}%</td></tr>
            <tr><td>${data.match.homeTeam} 晋级/夺冠</td><td>${Math.round(advancement.homeAdvances * 1000) / 10}%</td></tr>
            <tr><td>${data.match.awayTeam} 晋级/夺冠</td><td>${Math.round(advancement.awayAdvances * 1000) / 10}%</td></tr>
          </tbody>
        </table>
        <p style="margin-top:8px;">${extraTime.note}</p>
        <p style="margin-top:8px;">${penalties.note}</p>
        <p style="margin-top:8px;">${advancement.method}</p>
      ` : '';
      return `
        <h2 style="margin-top:20px;">赛制与数据口径</h2>
        <p>${rules.stageLabel}：${rules.explanation}</p>
        <p style="margin-top:8px;">数据记录规则：${rules.scoreStorageRule}</p>
        ${advancementHtml}
      `;
    }

    function renderError(error) {
      const panel = document.getElementById('predictionResult');
      panel.classList.remove('hidden');
      panel.innerHTML = `
        <h2>生成失败</h2>
        <p>页面已收到错误：${error.message || error}。请刷新页面后再试；如果仍失败，把这行错误发给我。</p>
      `;
      window.scrollTo({ top: panel.offsetTop - 12, behavior: 'smooth' });
    }

    function renderPrediction(data) {
      if (data.verdict && data.verdict.result === 'ABORTED') {
        renderAbortedPrediction(data);
        return;
      }
      const p = data.probabilities;
      const s = data.scorePrediction;
      const architecture = data.modelArchitecture || { principle: 'probability model + market calibration + risk explanation' };
      const factors = data.factors.map(f => `
        <tr>
          <td>${f.id}</td>
          <td>${f.name}</td>
          <td>${f.role}</td>
          <td>${f.weight}%</td>
          <td>${f.impactScore}</td>
          <td>${f.reasoning}</td>
        </tr>
      `).join('');
      document.getElementById('predictionResult').classList.remove('hidden');
      document.getElementById('predictionResult').innerHTML = `
        <h2>预测结果</h2>
        <div class="result-layout">
          <div>
            <p><span class="pill">${data.weightScheme}</span></p>
            <h2 style="margin-top:12px;">${resultCn(data.verdict.result)} · 预测比分 ${s.predicted.home}-${s.predicted.away}</h2>
            <p>${data.verdict.executiveSummary}</p>
            <div class="metrics">
              <div class="metric"><strong>${Math.round(p.home * 100)}%</strong><span>主胜</span></div>
              <div class="metric"><strong>${Math.round(p.draw * 100)}%</strong><span>平局</span></div>
              <div class="metric"><strong>${Math.round(p.away * 100)}%</strong><span>客胜</span></div>
              <div class="metric"><strong>${confidenceCn(data.verdict.confidence)}</strong><span>置信度</span></div>
            </div>
          </div>
          <div>
            <h2>Top 5 可能比分</h2>
            <table>
              <thead><tr><th>比分</th><th>概率</th><th>说明</th></tr></thead>
              <tbody>${s.topScenarios.map(item => `<tr><td>${item.score}</td><td>${Math.round(item.probability * 1000) / 10}%</td><td>${item.label || ''}</td></tr>`).join('')}</tbody>
            </table>
            <p style="margin-top:10px;">条件众数：${s.modal.home}-${s.modal.away}；λ值：主队 ${s.homeLambda}，客队 ${s.awayLambda}；Lineup前λ：主队 ${s.preLineupHomeLambda || s.homeLambda}，客队 ${s.preLineupAwayLambda || s.awayLambda}；原始λ：主队 ${s.rawHomeLambda}，客队 ${s.rawAwayLambda}</p>
            <p style="margin-top:8px;">${s.note}</p>
          </div>
        </div>
        ${renderDataReliability(data)}
        ${renderCanonicalProbability(data)}
        ${renderFinalRiskNarrative(data)}
        ${renderUpsetRisk(data)}
        ${renderBackgroundExecution(data)}
        ${renderCompetitionRules(data)}
        ${renderMarket(data)}
        ${renderLineupCheck(data)}
        <h2 style="margin-top:20px;">主要因子解释</h2>
        <p style="margin-bottom:10px;">V4-P0 后台逻辑：${architecture.principle}。CORE 参与主预测，CONTEXT 做场景修正，RISK/EXPLAIN 项主要用于解释和置信度，不再堆高权重。</p>
        <table>
          <thead><tr><th>编号</th><th>因子</th><th>角色</th><th>权重</th><th>影响分</th><th>解释</th></tr></thead>
          <tbody>${factors}</tbody>
        </table>
      `;
      scheduleBackgroundJobPoll(data);
      window.scrollTo({ top: document.getElementById('predictionResult').offsetTop - 12, behavior: 'smooth' });
    }

    async function loadCalibration() {
      const response = await fetch('/api/calibration/wc2022');
      const data = await response.json();
      const m = data.summary;
      const metrics = m.probabilityMetrics || {};
      const baseline = m.baselineComparison || {};
      const simple = baseline.simpleFavorite || {};
      const elo = baseline.eloRank || {};
      const buckets = baseline.calibrationBuckets || [];
      document.getElementById('calibrationResult').innerHTML = `
        <div class="metrics">
          <div class="metric"><strong>${m.matches}</strong><span>比赛样本</span></div>
          <div class="metric"><strong>${Math.round(m.resultAccuracy * 1000) / 10}%</strong><span>胜平负命中</span></div>
          <div class="metric"><strong>${Math.round(m.top5ScoreCoverage * 1000) / 10}%</strong><span>Top5比分覆盖</span></div>
          <div class="metric"><strong>${metrics.brierScore || '-'}</strong><span>Brier Score</span></div>
          <div class="metric"><strong>${metrics.logLoss || '-'}</strong><span>Log Loss</span></div>
          <div class="metric"><strong>${m.highConfidenceWrong}</strong><span>高置信错误</span></div>
        </div>
        <section style="margin:16px 0 0;">
          <h2>模型建议</h2>
          <table>
            <tbody>${data.recommendations.map(item => `<tr><td>${item}</td></tr>`).join('')}</tbody>
          </table>
        </section>
        <section>
          <h2>Baseline 对比</h2>
          <table>
            <thead><tr><th>模型</th><th>胜平负命中</th><th>Brier</th><th>Log Loss</th></tr></thead>
            <tbody>
              <tr><td>MatchOracle</td><td>${Math.round(m.resultAccuracy * 1000) / 10}%</td><td>${metrics.brierScore || '-'}</td><td>${metrics.logLoss || '-'}</td></tr>
              <tr><td>Simple Favorite</td><td>${simple.resultAccuracy ? Math.round(simple.resultAccuracy * 1000) / 10 + '%' : '-'}</td><td>${simple.brierScore || '-'}</td><td>${simple.logLoss || '-'}</td></tr>
              <tr><td>Elo Rank Baseline</td><td>${elo.resultAccuracy ? Math.round(elo.resultAccuracy * 1000) / 10 + '%' : '-'}</td><td>${elo.brierScore || '-'}</td><td>${elo.logLoss || '-'}</td></tr>
            </tbody>
          </table>
        </section>
        <section>
          <h2>Calibration Buckets</h2>
          <table>
            <thead><tr><th>置信区间</th><th>场次</th><th>平均置信度</th><th>实际命中率</th><th>误差</th></tr></thead>
            <tbody>${buckets.map(item => `<tr><td>${item.bucket}</td><td>${item.matches}</td><td>${Math.round(item.averageConfidence * 1000) / 10}%</td><td>${Math.round(item.observedAccuracy * 1000) / 10}%</td><td>${Math.round(item.calibrationError * 1000) / 10}%</td></tr>`).join('')}</tbody>
          </table>
        </section>
        <section>
          <h2>说明</h2>
          <p>小组赛真实平局率：${Math.round(m.groupActualDrawRate * 1000) / 10}%；模型平均预测平局率：${Math.round(m.groupPredictedDrawRate * 1000) / 10}%。</p>
          <p style="margin-top:8px;">预测赛果分布：主胜 ${m.predictedResultDistribution.HOME_WIN || 0}，平局 ${m.predictedResultDistribution.DRAW || 0}，客胜 ${m.predictedResultDistribution.AWAY_WIN || 0}。</p>
          <p style="margin-top:8px;">最高单项概率范围：${Math.round(m.maxProbabilityRange.min * 1000) / 10}% 到 ${Math.round(m.maxProbabilityRange.max * 1000) / 10}%。</p>
          <p style="margin-top:8px;">预测比分分布：${Object.entries(m.predictedScoreDistribution).map(([score, count]) => score + '×' + count).join('，')}。</p>
        </section>
      `;
    }
  </script>
</body>
</html>
"""


@app.route("/internal", methods=["GET"])
def internal_test_board():
    return INTERNAL_TEST_BOARD_HTML


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "project": "WorldCup"})


@app.route("/api/readiness", methods=["GET"])
def readiness():
    report = build_readiness_report()
    return jsonify(report), 503 if not report["ok"] else 200


@app.route("/api/featured-matches", methods=["GET"])
def featured_matches():
    limit = request.args.get("limit", "104")
    try:
        limit = max(1, min(104, int(limit)))
    except (TypeError, ValueError):
        limit = 104
    return jsonify(get_featured_feed(limit=limit))


@app.route("/favicon.ico", methods=["GET"])
def favicon():
    return "", 204


@app.route("/api/predict", methods=["POST"])
def predict():
    payload = request.get_json(force=True)
    bound_snapshot_id = requested_prediction_snapshot_id(payload)
    if bound_snapshot_id:
        try:
            bound_record = get_prediction_snapshot(bound_snapshot_id)
        except Exception as error:
            return jsonify(prediction_fallback(payload, "BOUND_SNAPSHOT_LOOKUP_FAILED", detail=str(error)))
        if bound_record:
            return jsonify(prediction_from_snapshot_record(bound_record, "PREDICTION_CARD_BOUND_SNAPSHOT"))
        return jsonify(prediction_fallback(payload, "BOUND_SNAPSHOT_NOT_FOUND", detail=bound_snapshot_id))

    save_requested = payload.get("persistSnapshot") or request.args.get("save") == "1"
    requested_snapshot_type = request.args.get("snapshotType")
    if request.args.get("prematchFinal") == "1":
        requested_snapshot_type = PREMATCH_FINAL
    snapshot_type = snapshot_type_from_request(payload, requested_snapshot_type)
    match_id = payload.get("matchId")
    kickoff_has_passed = is_after_kickoff(match_datetime_from_payload(payload))
    try:
        frozen_record = get_latest_prematch_final(match_id) if match_id and kickoff_has_passed else None
    except Exception as error:
        return jsonify(prediction_fallback(payload, "SNAPSHOT_STORE_UNAVAILABLE", detail=str(error)))
    if frozen_record:
        return jsonify(prediction_from_snapshot_record(frozen_record, "PREMATCH_FINAL_FROZEN_AFTER_KICKOFF"))

    background_job_type = background_job_type_for_prediction_payload(payload)
    if background_job_type:
        if kickoff_has_passed:
            fallback = prediction_fallback(payload, "BACKGROUND_JOB_CUTOFF_PASSED")
            fallback["backgroundExecution"] = {
                "status": "REJECTED",
                "reason": "Prematch recalculation jobs cannot be queued after kickoff without a frozen final snapshot.",
            }
            return jsonify(fallback), 202
        try:
            job = enqueue_prediction_background_job(background_job_type, payload, snapshot_type)
        except Exception as error:
            return jsonify(prediction_fallback(payload, "BACKGROUND_JOB_QUEUE_UNAVAILABLE", detail=str(error)))
        fallback = prediction_fallback(payload, "BACKGROUND_JOB_QUEUED", detail=job.get("jobId"))
        fallback["queuedJob"] = public_job_summary(job)
        fallback["backgroundExecution"] = {
            "status": "QUEUED",
            "reason": "T-60 lineup recalculation is handled by the background worker; this response only serves an existing snapshot or static fallback.",
        }
        return jsonify(fallback), 202

    if save_requested and kickoff_has_passed:
        return jsonify({
            "error": "PREMATCH_SNAPSHOT_CUTOFF_PASSED",
            "message": "Prematch prediction snapshots must be persisted before kickoff.",
            "snapshotType": snapshot_type,
            "matchId": match_id,
        }), 409
    try:
        result = predictor.predict(payload)
    except Exception as error:
        return jsonify(prediction_fallback(payload, "PREDICTION_ENGINE_ERROR", detail=str(error)))
    attach_prediction_view_model(result)
    if save_requested:
        try:
            record = append_prediction_snapshot(result, request_payload=payload, snapshot_type=snapshot_type)
        except SnapshotFreezeError as error:
            return jsonify({"error": error.code, "message": error.message}), 409
        except Exception as error:
            return jsonify(prediction_fallback(payload, "SNAPSHOT_SAVE_FAILED", detail=str(error)))
        if record.get("storageOperation") == "PREMATCH_FINAL_ALREADY_EXISTS":
            return jsonify(prediction_from_snapshot_record(record, "PREMATCH_FINAL_ALREADY_EXISTS"))
        result["savedSnapshot"] = {key: value for key, value in record.items() if key != "prediction"}
    return jsonify(result)


@app.route("/api/snapshots", methods=["GET"])
def snapshots():
    match_id = request.args.get("matchId")
    snapshot_type = snapshot_type_from_request({}, request.args.get("snapshotType")) if request.args.get("snapshotType") else None
    limit = request.args.get("limit", "20")
    try:
        limit = max(1, min(100, int(limit)))
    except ValueError:
        limit = 20
    return jsonify({"snapshots": list_prediction_snapshots(match_id=match_id, snapshot_type=snapshot_type, limit=limit)})


@app.route("/api/snapshots/latest", methods=["GET"])
def latest_snapshot():
    snapshot_type = snapshot_type_from_request({}, request.args.get("snapshotType")) if request.args.get("snapshotType") else None
    record = latest_prediction_snapshot(match_id=request.args.get("matchId"), snapshot_type=snapshot_type)
    if not record:
        return jsonify({"error": "SNAPSHOT_NOT_FOUND"}), 404
    return jsonify(record)


@app.route("/api/snapshots/last-good", methods=["GET"])
def last_good_snapshot():
    record = get_last_good_prediction_snapshot(match_id=request.args.get("matchId"))
    if not record:
        return jsonify({"error": "LAST_GOOD_SNAPSHOT_NOT_FOUND"}), 404
    return jsonify(record)


@app.route("/api/jobs", methods=["GET"])
def jobs():
    limit = request.args.get("limit", "20")
    try:
        limit = max(1, min(100, int(limit)))
    except ValueError:
        limit = 20
    jobs = list_background_jobs(
        status=request.args.get("status"),
        job_type=request.args.get("jobType"),
        limit=limit,
    )
    return jsonify({"jobs": [public_job_summary(job) for job in jobs]})


@app.route("/api/jobs/<job_id>", methods=["GET"])
def job_by_id(job_id):
    job = get_background_job(job_id)
    if not job:
        return jsonify({"error": "BACKGROUND_JOB_NOT_FOUND"}), 404
    include_payload = str(request.args.get("includePayload", "")).lower() in {"1", "true", "yes"}
    if include_payload and not worker_request_authorized():
        return jsonify({
            "error": "JOB_PAYLOAD_AUTH_REQUIRED",
            "message": "Job payload is restricted to authenticated worker/admin requests.",
            "workerAuth": worker_auth_state(),
        }), 403
    return jsonify(public_job_summary(job, include_payload=include_payload))


@app.route("/api/jobs/run-next", methods=["POST"])
def run_next_job():
    if not worker_request_authorized():
        return jsonify({
            "error": "WORKER_AUTH_REQUIRED",
            "message": "Worker endpoint requires token authentication in production or when configured.",
            "workerAuth": worker_auth_state(),
        }), 403
    worker_id = request.headers.get("X-MatchOracle-Worker-Id", "local-worker")
    job = claim_next_background_job(
        worker_id=worker_id,
        concurrency_limit=background_job_concurrency_limit(),
    )
    if not job:
        return jsonify({"job": None, "reason": "NO_RUNNABLE_JOB_OR_CONCURRENCY_LIMIT"})
    try:
        result = run_prediction_background_job(job)
        completed = mark_background_job_succeeded(job["jobId"], result)
        return jsonify({"job": public_job_summary(completed, include_payload=True)})
    except SnapshotFreezeError as error:
        failed = mark_background_job_failed(
            job["jobId"],
            {"code": error.code, "message": error.message},
        )
        return jsonify({"job": public_job_summary(failed, include_payload=True)}), 409
    except BackgroundJobError as error:
        failed = mark_background_job_failed(
            job["jobId"],
            {"code": error.code, "message": error.message, **error.details},
        )
        return jsonify({"job": public_job_summary(failed, include_payload=True)}), 409
    except Exception as error:
        failed = mark_background_job_failed(job["jobId"], {"message": str(error)})
        return jsonify({"job": public_job_summary(failed, include_payload=True)}), 500


@app.route("/api/odds/import", methods=["POST"])
def queue_odds_import():
    payload = request.get_json(force=True) or {}
    if not worker_auth_state()["legacyHeaderAllowed"] and not worker_request_authorized():
        return jsonify({
            "error": "ODDS_IMPORT_AUTH_REQUIRED",
            "message": "Odds import queueing requires authenticated worker/admin access when worker auth is configured.",
            "workerAuth": worker_auth_state(),
        }), 403
    source_path = payload.get("path")
    if source_path:
        if not worker_request_authorized():
            return jsonify({
                "error": "ODDS_IMPORT_PATH_AUTH_REQUIRED",
                "message": "Public odds import requests must provide csvText only; local path imports require worker/admin authentication.",
                "workerAuth": worker_auth_state(),
            }), 403
        try:
            source_path = validate_odds_import_path(source_path)
        except BackgroundJobError as error:
            return jsonify({"error": error.code, "message": error.message, **error.details}), 400
    job_payload = {
        "csvText": payload.get("csvText"),
        "path": source_path,
        "sourceName": payload.get("sourceName"),
        "knownTeams": payload.get("knownTeams"),
        "teamAliases": payload.get("teamAliases"),
    }
    if job_payload["csvText"] is None and not job_payload["path"]:
        return jsonify({
            "error": "ODDS_CSV_MISSING",
            "message": "Provide csvText or path for odds CSV import.",
        }), 400
    try:
        job = enqueue_background_job(JOB_TYPE_ODDS_IMPORT, job_payload, priority=5, max_attempts=1)
    except Exception as error:
        return jsonify({"error": "BACKGROUND_JOB_QUEUE_UNAVAILABLE", "message": str(error)}), 503
    return jsonify({
        "queuedJob": public_job_summary(job),
        "backgroundExecution": {
            "status": "QUEUED",
            "reason": "Odds CSV imports run in the background worker and never mutate market snapshots synchronously.",
        },
    }), 202


@app.route("/api/f05/monte-carlo", methods=["POST"])
def queue_f05_monte_carlo():
    payload = request.get_json(force=True) or {}
    if not worker_auth_state()["legacyHeaderAllowed"] and not worker_request_authorized():
        return jsonify({
            "error": "F05_MONTE_CARLO_AUTH_REQUIRED",
            "message": "F05 Monte Carlo queueing requires authenticated worker/admin access when worker auth is configured.",
            "workerAuth": worker_auth_state(),
        }), 403
    try:
        normalize_job_payload = dict(payload)
        job = enqueue_background_job(JOB_TYPE_F05_MONTE_CARLO, normalize_job_payload, priority=7, max_attempts=1)
    except Exception as error:
        return jsonify({"error": "BACKGROUND_JOB_QUEUE_UNAVAILABLE", "message": str(error)}), 503
    return jsonify({
        "queuedJob": public_job_summary(job),
        "backgroundExecution": {
            "status": "QUEUED",
            "reason": "F05 Monte Carlo runs in the background worker from a locked T-24 dependency snapshot.",
        },
    }), 202


@app.route("/api/structured-facts/sync", methods=["POST"])
def queue_structured_facts_sync():
    if not worker_request_authorized():
        return jsonify({
            "error": "STRUCTURED_FACTS_SYNC_AUTH_REQUIRED",
            "message": "Structured facts provider sync requires authenticated worker/admin access.",
            "workerAuth": worker_auth_state(),
        }), 403
    payload = request.get_json(force=True) or {}
    job_payload = {
        "matchId": payload.get("matchId"),
        "snapshotTime": payload.get("snapshotTime"),
        "dryRun": bool(payload.get("dryRun")),
    }
    try:
        job = enqueue_background_job(JOB_TYPE_STRUCTURED_FACTS_SYNC, job_payload, priority=6, max_attempts=1)
    except Exception as error:
        return jsonify({"error": "BACKGROUND_JOB_QUEUE_UNAVAILABLE", "message": str(error)}), 503
    return jsonify({
        "queuedJob": public_job_summary(job),
        "backgroundExecution": {
            "status": "QUEUED",
            "reason": "Structured facts provider sync runs in the background worker using configured provider env only.",
        },
    }), 202


@app.route("/api/odds/snapshots", methods=["GET"])
def odds_snapshots():
    limit = request.args.get("limit", "20")
    try:
        limit = max(1, min(100, int(limit)))
    except ValueError:
        limit = 20
    return jsonify({
        "snapshots": list_market_odds_snapshots(
            year=request.args.get("year"),
            home_team=request.args.get("homeTeam"),
            away_team=request.args.get("awayTeam"),
            limit=limit,
        )
    })


@app.route("/api/snapshots/<snapshot_id>", methods=["GET"])
def snapshot_by_id(snapshot_id):
    record = get_prediction_snapshot(snapshot_id)
    if not record:
        return jsonify({"error": "SNAPSHOT_NOT_FOUND"}), 404
    return jsonify(record)


@app.route("/api/snapshots/<snapshot_id>/replay", methods=["POST"])
def replay_snapshot(snapshot_id):
    record = get_prediction_snapshot(snapshot_id)
    if not record:
        return jsonify({"error": "SNAPSHOT_NOT_FOUND"}), 404
    request_payload = record.get("requestPayload")
    if not request_payload:
        return jsonify({"error": "REQUEST_PAYLOAD_NOT_AVAILABLE"}), 409
    replayed = predictor.predict(request_payload)
    return jsonify({
        "predictionSnapshotId": snapshot_id,
        "replay": compare_replay(record["prediction"], replayed),
    })


@app.route("/api/calibration/wc2022", methods=["GET"])
def calibration_wc2022():
    return jsonify(run_wc2022_calibration())


@app.route("/api/calibration/split", methods=["GET"])
def calibration_split():
    return jsonify(run_split_backtest())


if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", "5012")))
