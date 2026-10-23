import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_STORE_PATH = os.path.join(PROJECT_ROOT, "data", "worldcup", "prediction_snapshots.sqlite3")
SNAPSHOT_SCHEMA_VERSION = 1
PREMATCH_DRAFT = "PREMATCH_DRAFT"
PREMATCH_FINAL = "PREMATCH_FINAL"
LAST_GOOD_CANONICAL_STATUS = "ACTIVE"


class SnapshotFreezeError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def snapshot_store_path():
    return os.environ.get("MATCHORACLE_SNAPSHOT_STORE", DEFAULT_STORE_PATH)


def current_utc():
    override = os.environ.get("MATCHORACLE_NOW")
    if override:
        return parse_iso_datetime(override)
    return datetime.now(timezone.utc)


def current_utc_iso():
    return current_utc().isoformat()


def parse_iso_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        normalized = str(value).replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_after_kickoff(match_datetime, now=None):
    kickoff = parse_iso_datetime(match_datetime)
    if not kickoff:
        return False
    now = now or current_utc()
    return now >= kickoff


def match_datetime_from_payload(payload):
    return ((payload or {}).get("match") or {}).get("datetime")


def match_datetime_from_prediction(prediction):
    return ((prediction or {}).get("match") or {}).get("datetime")


def snapshot_type_from_request(request_payload=None, explicit_snapshot_type=None):
    requested = explicit_snapshot_type or (request_payload or {}).get("snapshotType")
    if not requested:
        requested = ((request_payload or {}).get("snapshotPolicy") or {}).get("snapshotType")
    if not requested:
        return PREMATCH_DRAFT
    requested = str(requested).upper()
    if requested in {"FINAL", "PREMATCH_FINAL"}:
        return PREMATCH_FINAL
    return PREMATCH_DRAFT


def json_dumps(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def json_loads(payload):
    return json.loads(payload) if payload else None


def build_snapshot_record(prediction, request_payload=None, snapshot_type=None, saved_at=None):
    manifest = prediction.get("predictionManifest") or {}
    saved_at = saved_at or current_utc_iso()
    snapshot_type = snapshot_type_from_request(request_payload, snapshot_type)
    kickoff_at = match_datetime_from_prediction(prediction) or match_datetime_from_payload(request_payload)
    prediction_snapshot_id = prediction.get("predictionSnapshotId") or manifest.get("predictionSnapshotId")
    content_hash = uuid.uuid5(
        uuid.NAMESPACE_URL,
        json_dumps({
            "predictionSnapshotId": prediction_snapshot_id,
            "snapshotType": snapshot_type,
            "requestPayload": request_payload,
            "prediction": prediction,
        }),
    ).hex
    return {
        "schemaVersion": SNAPSHOT_SCHEMA_VERSION,
        "snapshotRecordId": uuid.uuid4().hex,
        "predictionSnapshotId": prediction_snapshot_id,
        "matchId": prediction.get("matchId"),
        "snapshotType": snapshot_type,
        "freezeStatus": "FROZEN" if snapshot_type == PREMATCH_FINAL else "DRAFT",
        "kickoffAt": kickoff_at,
        "frozenAt": saved_at if snapshot_type == PREMATCH_FINAL else None,
        "contentHash": content_hash,
        "savedAt": saved_at,
        "generatedAt": prediction.get("generatedAt"),
        "modelVersion": prediction.get("modelVersion"),
        "configVersion": manifest.get("configVersion"),
        "dataReliabilityStatus": (prediction.get("dataReliability") or {}).get("status"),
        "canonicalStatus": (prediction.get("canonicalProbability") or {}).get("status"),
        "requestPayload": request_payload,
        "prediction": prediction,
    }


def is_jsonl_store(path):
    return str(path).endswith(".jsonl")


def connect_snapshot_db(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    initialize_snapshot_db(connection)
    return connection


def initialize_snapshot_db(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS prediction_snapshots (
            snapshot_record_id TEXT PRIMARY KEY,
            prediction_snapshot_id TEXT NOT NULL,
            match_id TEXT NOT NULL,
            snapshot_type TEXT NOT NULL,
            freeze_status TEXT NOT NULL,
            kickoff_at TEXT,
            frozen_at TEXT,
            saved_at TEXT NOT NULL,
            generated_at TEXT,
            model_version TEXT,
            config_version TEXT,
            data_reliability_status TEXT,
            canonical_status TEXT,
            content_hash TEXT NOT NULL,
            request_payload_json TEXT,
            prediction_json TEXT NOT NULL,
            schema_version INTEGER NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_prediction_snapshots_match_saved ON prediction_snapshots(match_id, saved_at)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_prediction_snapshots_prediction_id ON prediction_snapshots(prediction_snapshot_id)")
    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_prediction_snapshots_content_hash ON prediction_snapshots(content_hash)")
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_prediction_snapshots_prematch_final
        ON prediction_snapshots(match_id, snapshot_type)
        WHERE snapshot_type = 'PREMATCH_FINAL'
        """
    )
    connection.commit()


def row_to_record(row):
    if not row:
        return None
    return {
        "schemaVersion": row["schema_version"],
        "snapshotRecordId": row["snapshot_record_id"],
        "savedAt": row["saved_at"],
        "predictionSnapshotId": row["prediction_snapshot_id"],
        "matchId": row["match_id"],
        "snapshotType": row["snapshot_type"],
        "freezeStatus": row["freeze_status"],
        "kickoffAt": row["kickoff_at"],
        "frozenAt": row["frozen_at"],
        "generatedAt": row["generated_at"],
        "modelVersion": row["model_version"],
        "configVersion": row["config_version"],
        "dataReliabilityStatus": row["data_reliability_status"],
        "canonicalStatus": row["canonical_status"],
        "contentHash": row["content_hash"],
        "requestPayload": json_loads(row["request_payload_json"]),
        "prediction": json_loads(row["prediction_json"]),
    }


def insert_snapshot_record(connection, record):
    connection.execute(
        """
        INSERT INTO prediction_snapshots (
            snapshot_record_id,
            prediction_snapshot_id,
            match_id,
            snapshot_type,
            freeze_status,
            kickoff_at,
            frozen_at,
            saved_at,
            generated_at,
            model_version,
            config_version,
            data_reliability_status,
            canonical_status,
            content_hash,
            request_payload_json,
            prediction_json,
            schema_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["snapshotRecordId"],
            record["predictionSnapshotId"],
            record["matchId"],
            record["snapshotType"],
            record["freezeStatus"],
            record["kickoffAt"],
            record["frozenAt"],
            record["savedAt"],
            record["generatedAt"],
            record["modelVersion"],
            record["configVersion"],
            record["dataReliabilityStatus"],
            record["canonicalStatus"],
            record["contentHash"],
            json_dumps(record["requestPayload"]) if record.get("requestPayload") is not None else None,
            json_dumps(record["prediction"]),
            record["schemaVersion"],
        ),
    )
    connection.commit()


def get_latest_prematch_final(match_id, path=None):
    return latest_prediction_snapshot(match_id=match_id, snapshot_type=PREMATCH_FINAL, path=path)


def record_is_last_good(record):
    if not record:
        return False
    canonical_status = record.get("canonicalStatus")
    if canonical_status is None:
        canonical_status = ((record.get("prediction") or {}).get("canonicalProbability") or {}).get("status")
    data_reliability_status = record.get("dataReliabilityStatus")
    if data_reliability_status is None:
        data_reliability_status = ((record.get("prediction") or {}).get("dataReliability") or {}).get("status")
    return canonical_status == LAST_GOOD_CANONICAL_STATUS and data_reliability_status != "FATAL"


def get_last_good_prediction_snapshot(match_id=None, path=None):
    path = path or snapshot_store_path()
    if os.path.exists(path) and not is_jsonl_store(path):
        where = ["canonical_status = ?", "(data_reliability_status IS NULL OR data_reliability_status != ?)"]
        params = [LAST_GOOD_CANONICAL_STATUS, "FATAL"]
        if match_id is not None:
            where.append("match_id = ?")
            params.append(match_id)
        query = "SELECT * FROM prediction_snapshots WHERE " + " AND ".join(where)
        query += " ORDER BY saved_at DESC, rowid DESC LIMIT 1"
        with connect_snapshot_db(path) as connection:
            return row_to_record(connection.execute(query, params).fetchone())
    for record in reversed(iter_snapshot_records(path)):
        if match_id is not None and record.get("matchId") != match_id:
            continue
        if record_is_last_good(record):
            return record
    return None


def append_prediction_snapshot(prediction, request_payload=None, path=None, snapshot_type=None):
    path = path or snapshot_store_path()
    snapshot_type = snapshot_type_from_request(request_payload, snapshot_type)
    existing_final = get_latest_prematch_final(prediction.get("matchId"), path=path) if prediction.get("matchId") else None
    if snapshot_type == PREMATCH_FINAL and existing_final:
        return {**existing_final, "storageOperation": "PREMATCH_FINAL_ALREADY_EXISTS"}
    if is_after_kickoff(match_datetime_from_prediction(prediction) or match_datetime_from_payload(request_payload)) and snapshot_type == PREMATCH_FINAL:
        raise SnapshotFreezeError(
            "PREMATCH_FINAL_CUTOFF_PASSED",
            "PREMATCH_FINAL snapshots must be persisted before kickoff.",
        )
    record = build_snapshot_record(prediction, request_payload=request_payload, snapshot_type=snapshot_type)
    if is_jsonl_store(path):
        return append_prediction_snapshot_jsonl(record, path)
    with connect_snapshot_db(path) as connection:
        try:
            insert_snapshot_record(connection, record)
        except sqlite3.IntegrityError:
            existing = get_prediction_snapshot(record["snapshotRecordId"], path=path) or get_prediction_snapshot(record["predictionSnapshotId"], path=path)
            if existing:
                return {**existing, "storageOperation": "DUPLICATE_CONTENT"}
            raise
    return {**record, "storageOperation": "INSERTED"}


def append_prediction_snapshot_jsonl(record, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json_dumps(record) + "\n")
    return {**record, "storageOperation": "INSERTED"}


def iter_snapshot_records(path=None):
    path = path or snapshot_store_path()
    if not os.path.exists(path):
        return []
    if not is_jsonl_store(path):
        with connect_snapshot_db(path) as connection:
            rows = connection.execute(
                "SELECT * FROM prediction_snapshots ORDER BY saved_at ASC, rowid ASC"
            ).fetchall()
            return [row_to_record(row) for row in rows]
    records = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def get_prediction_snapshot(snapshot_id, path=None):
    path = path or snapshot_store_path()
    if os.path.exists(path) and not is_jsonl_store(path):
        with connect_snapshot_db(path) as connection:
            row = connection.execute(
                """
                SELECT * FROM prediction_snapshots
                WHERE snapshot_record_id = ? OR prediction_snapshot_id = ?
                ORDER BY saved_at DESC, rowid DESC
                LIMIT 1
                """,
                (snapshot_id, snapshot_id),
            ).fetchone()
            return row_to_record(row)
    for record in reversed(iter_snapshot_records(path)):
        if record.get("predictionSnapshotId") == snapshot_id or record.get("snapshotRecordId") == snapshot_id:
            return record
    return None


def latest_prediction_snapshot(match_id=None, snapshot_type=None, path=None):
    path = path or snapshot_store_path()
    if os.path.exists(path) and not is_jsonl_store(path):
        where = []
        params = []
        if match_id is not None:
            where.append("match_id = ?")
            params.append(match_id)
        if snapshot_type is not None:
            where.append("snapshot_type = ?")
            params.append(snapshot_type)
        query = "SELECT * FROM prediction_snapshots"
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY saved_at DESC, rowid DESC LIMIT 1"
        with connect_snapshot_db(path) as connection:
            return row_to_record(connection.execute(query, params).fetchone())
    for record in reversed(iter_snapshot_records(path)):
        if match_id is not None and record.get("matchId") != match_id:
            continue
        if snapshot_type is not None and record.get("snapshotType") != snapshot_type:
            continue
        if match_id is None or record.get("matchId") == match_id:
            return record
    return None


def list_prediction_snapshots(match_id=None, limit=20, snapshot_type=None, path=None):
    matches = []
    for record in reversed(iter_snapshot_records(path)):
        if match_id is not None and record.get("matchId") != match_id:
            continue
        if snapshot_type is not None and record.get("snapshotType") != snapshot_type:
            continue
        matches.append({
            "schemaVersion": record.get("schemaVersion"),
            "snapshotRecordId": record.get("snapshotRecordId"),
            "savedAt": record.get("savedAt"),
            "predictionSnapshotId": record.get("predictionSnapshotId"),
            "matchId": record.get("matchId"),
            "snapshotType": record.get("snapshotType"),
            "freezeStatus": record.get("freezeStatus"),
            "kickoffAt": record.get("kickoffAt"),
            "frozenAt": record.get("frozenAt"),
            "generatedAt": record.get("generatedAt"),
            "modelVersion": record.get("modelVersion"),
            "configVersion": record.get("configVersion"),
            "dataReliabilityStatus": record.get("dataReliabilityStatus"),
            "canonicalStatus": record.get("canonicalStatus"),
            "contentHash": record.get("contentHash"),
        })
        if len(matches) >= limit:
            break
    return matches


def prediction_replay_summary(prediction):
    score = prediction.get("scorePrediction") or {}
    return {
        "predictionSnapshotId": prediction.get("predictionSnapshotId"),
        "verdictResult": (prediction.get("verdict") or {}).get("result"),
        "probabilities": prediction.get("probabilities"),
        "canonicalProbability": (prediction.get("canonicalProbability") or {}).get("probabilities"),
        "homeLambda": score.get("homeLambda"),
        "awayLambda": score.get("awayLambda"),
    }


def compare_replay(original_prediction, replayed_prediction):
    original = prediction_replay_summary(original_prediction)
    replayed = prediction_replay_summary(replayed_prediction)
    differences = {
        key: {"original": original.get(key), "replayed": replayed.get(key)}
        for key in original
        if original.get(key) != replayed.get(key)
    }
    return {
        "matches": not differences,
        "original": original,
        "replayed": replayed,
        "differences": differences,
    }
