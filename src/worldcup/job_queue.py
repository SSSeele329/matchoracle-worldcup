import json
import os
import sqlite3
import uuid
from datetime import timedelta

from .snapshot import stable_hash
from .snapshot_store import current_utc, current_utc_iso


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_QUEUE_PATH = os.path.join(PROJECT_ROOT, "data", "worldcup", "background_jobs.sqlite3")

JOB_TYPE_T60_LINEUP_RECALC = "T60_LINEUP_RECALC"
JOB_TYPE_ODDS_IMPORT = "ODDS_IMPORT"
JOB_TYPE_F05_MONTE_CARLO = "F05_MONTE_CARLO"
JOB_TYPE_STRUCTURED_FACTS_SYNC = "STRUCTURED_FACTS_SYNC"
ALLOWED_JOB_TYPES = {
    JOB_TYPE_T60_LINEUP_RECALC,
    JOB_TYPE_ODDS_IMPORT,
    JOB_TYPE_F05_MONTE_CARLO,
    JOB_TYPE_STRUCTURED_FACTS_SYNC,
}

JOB_QUEUED = "QUEUED"
JOB_RUNNING = "RUNNING"
JOB_SUCCEEDED = "SUCCEEDED"
JOB_FAILED = "FAILED"
TERMINAL_STATUSES = {JOB_SUCCEEDED, JOB_FAILED}
DEFAULT_CONCURRENCY_LIMIT = 1
DEFAULT_JOB_LEASE_TIMEOUT_SECONDS = 15 * 60
JOB_LEASE_TIMEOUT_ENV = "MATCHORACLE_JOB_LEASE_TIMEOUT_SECONDS"


class BackgroundJobError(Exception):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def job_queue_path():
    return os.environ.get("MATCHORACLE_JOB_QUEUE_STORE", DEFAULT_QUEUE_PATH)


def background_job_concurrency_limit():
    raw_value = os.environ.get("MATCHORACLE_WORKER_CONCURRENCY", str(DEFAULT_CONCURRENCY_LIMIT))
    try:
        return max(1, int(raw_value))
    except ValueError:
        return DEFAULT_CONCURRENCY_LIMIT


def background_job_lease_timeout_seconds():
    raw_value = os.environ.get(JOB_LEASE_TIMEOUT_ENV, str(DEFAULT_JOB_LEASE_TIMEOUT_SECONDS))
    try:
        return max(1, int(raw_value))
    except ValueError:
        return DEFAULT_JOB_LEASE_TIMEOUT_SECONDS


def json_dumps(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def json_loads(payload):
    return json.loads(payload) if payload else None


def connect_job_db(path=None):
    path = path or job_queue_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    initialize_job_db(connection)
    return connection


def initialize_job_db(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS background_jobs (
            job_id TEXT PRIMARY KEY,
            job_type TEXT NOT NULL,
            status TEXT NOT NULL,
            priority INTEGER NOT NULL,
            dedupe_key TEXT NOT NULL UNIQUE,
            payload_json TEXT NOT NULL,
            result_json TEXT,
            error_json TEXT,
            attempts INTEGER NOT NULL,
            max_attempts INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            not_before_at TEXT,
            started_at TEXT,
            finished_at TEXT,
            locked_by TEXT,
            locked_at TEXT
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_background_jobs_status_created ON background_jobs(status, created_at)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_background_jobs_type_status ON background_jobs(job_type, status)")
    connection.commit()


def validate_job_type(job_type):
    if job_type not in ALLOWED_JOB_TYPES:
        raise BackgroundJobError("UNKNOWN_BACKGROUND_JOB_TYPE", f"Unknown background job type: {job_type}")


def row_to_job(row):
    if not row:
        return None
    return {
        "jobId": row["job_id"],
        "jobType": row["job_type"],
        "status": row["status"],
        "priority": row["priority"],
        "dedupeKey": row["dedupe_key"],
        "payload": json_loads(row["payload_json"]),
        "result": json_loads(row["result_json"]),
        "error": json_loads(row["error_json"]),
        "attempts": row["attempts"],
        "maxAttempts": row["max_attempts"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "notBeforeAt": row["not_before_at"],
        "startedAt": row["started_at"],
        "finishedAt": row["finished_at"],
        "lockedBy": row["locked_by"],
        "lockedAt": row["locked_at"],
    }


def build_job_dedupe_key(job_type, payload):
    return f"{job_type}:{stable_hash({'jobType': job_type, 'payload': payload})}"


def get_background_job(job_id, path=None):
    with connect_job_db(path) as connection:
        row = connection.execute(
            "SELECT * FROM background_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        return row_to_job(row)


def get_background_job_by_dedupe_key(dedupe_key, path=None):
    with connect_job_db(path) as connection:
        row = connection.execute(
            "SELECT * FROM background_jobs WHERE dedupe_key = ?",
            (dedupe_key,),
        ).fetchone()
        return row_to_job(row)


def enqueue_background_job(
    job_type,
    payload,
    priority=0,
    dedupe_key=None,
    max_attempts=1,
    not_before_at=None,
    path=None,
):
    validate_job_type(job_type)
    payload = payload or {}
    dedupe_key = dedupe_key or build_job_dedupe_key(job_type, payload)
    now = current_utc_iso()
    job_id = uuid.uuid4().hex
    with connect_job_db(path) as connection:
        try:
            connection.execute(
                """
                INSERT INTO background_jobs (
                    job_id,
                    job_type,
                    status,
                    priority,
                    dedupe_key,
                    payload_json,
                    attempts,
                    max_attempts,
                    created_at,
                    updated_at,
                    not_before_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    job_type,
                    JOB_QUEUED,
                    priority,
                    dedupe_key,
                    json_dumps(payload),
                    0,
                    max(1, int(max_attempts)),
                    now,
                    now,
                    not_before_at,
                ),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM background_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            job = row_to_job(row)
            job["queueOperation"] = "INSERTED"
            return job
        except sqlite3.IntegrityError:
            connection.rollback()
            row = connection.execute(
                "SELECT * FROM background_jobs WHERE dedupe_key = ?",
                (dedupe_key,),
            ).fetchone()
            existing = row_to_job(row)
            if existing:
                existing["queueOperation"] = "EXISTING"
                return existing
            raise


def running_job_count(path=None):
    with connect_job_db(path) as connection:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM background_jobs WHERE status = ?",
            (JOB_RUNNING,),
        ).fetchone()
        return row["count"]


def _reap_stale_running_jobs(connection, now, timeout_seconds):
    cutoff = (now - timedelta(seconds=timeout_seconds)).isoformat()
    now_iso = now.isoformat()
    stale_rows = connection.execute(
        """
        SELECT * FROM background_jobs
        WHERE status = ?
          AND (locked_at IS NULL OR locked_at <= ?)
        ORDER BY locked_at ASC, updated_at ASC, rowid ASC
        """,
        (JOB_RUNNING, cutoff),
    ).fetchall()
    reaped_job_ids = []
    for row in stale_rows:
        retry = row["attempts"] < row["max_attempts"]
        status = JOB_QUEUED if retry else JOB_FAILED
        error = {
            "code": "BACKGROUND_JOB_LEASE_TIMEOUT",
            "message": "Background job lease expired before the worker marked it complete.",
            "leaseTimeoutSeconds": timeout_seconds,
            "timedOutAt": now_iso,
            "previousLockedBy": row["locked_by"],
            "previousLockedAt": row["locked_at"],
            "requeued": retry,
        }
        connection.execute(
            """
            UPDATE background_jobs
            SET status = ?,
                result_json = NULL,
                error_json = ?,
                updated_at = ?,
                started_at = ?,
                finished_at = ?,
                locked_by = NULL,
                locked_at = NULL
            WHERE job_id = ?
            """,
            (
                status,
                json_dumps(error),
                now_iso,
                None if retry else row["started_at"],
                None if retry else now_iso,
                row["job_id"],
            ),
        )
        reaped_job_ids.append(row["job_id"])
    return reaped_job_ids


def reap_stale_running_jobs(timeout_seconds=None, path=None):
    timeout_seconds = timeout_seconds or background_job_lease_timeout_seconds()
    now = current_utc()
    with connect_job_db(path) as connection:
        connection.isolation_level = None
        connection.execute("BEGIN IMMEDIATE")
        try:
            reaped_job_ids = _reap_stale_running_jobs(connection, now, timeout_seconds)
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
    return [get_background_job(job_id, path=path) for job_id in reaped_job_ids]


def claim_next_background_job(worker_id, concurrency_limit=None, job_types=None, path=None):
    concurrency_limit = concurrency_limit or background_job_concurrency_limit()
    now = current_utc()
    now_iso = now.isoformat()
    with connect_job_db(path) as connection:
        connection.isolation_level = None
        connection.execute("BEGIN IMMEDIATE")
        try:
            _reap_stale_running_jobs(
                connection,
                now,
                background_job_lease_timeout_seconds(),
            )
            running = connection.execute(
                "SELECT COUNT(*) AS count FROM background_jobs WHERE status = ?",
                (JOB_RUNNING,),
            ).fetchone()["count"]
            if running >= concurrency_limit:
                connection.execute("COMMIT")
                return None

            where = ["status = ?", "(not_before_at IS NULL OR not_before_at <= ?)"]
            params = [JOB_QUEUED, now_iso]
            if job_types:
                placeholders = ", ".join("?" for _ in job_types)
                where.append(f"job_type IN ({placeholders})")
                params.extend(job_types)
            row = connection.execute(
                "SELECT * FROM background_jobs WHERE "
                + " AND ".join(where)
                + " ORDER BY priority DESC, created_at ASC, rowid ASC LIMIT 1",
                params,
            ).fetchone()
            if not row:
                connection.execute("COMMIT")
                return None

            connection.execute(
                """
                UPDATE background_jobs
                SET status = ?,
                    attempts = attempts + 1,
                    updated_at = ?,
                    started_at = ?,
                    locked_by = ?,
                    locked_at = ?
                WHERE job_id = ?
                """,
                (JOB_RUNNING, now_iso, now_iso, worker_id, now_iso, row["job_id"]),
            )
            connection.execute("COMMIT")
        except Exception:
            connection.execute("ROLLBACK")
            raise
    return get_background_job(row["job_id"], path=path)


def mark_background_job_succeeded(job_id, result=None, path=None):
    now = current_utc_iso()
    with connect_job_db(path) as connection:
        connection.execute(
            """
            UPDATE background_jobs
            SET status = ?,
                result_json = ?,
                error_json = NULL,
                updated_at = ?,
                finished_at = ?,
                locked_by = NULL,
                locked_at = NULL
            WHERE job_id = ?
            """,
            (JOB_SUCCEEDED, json_dumps(result or {}), now, now, job_id),
        )
        connection.commit()
    return get_background_job(job_id, path=path)


def mark_background_job_failed(job_id, error, path=None):
    now = current_utc_iso()
    job = get_background_job(job_id, path=path)
    if not job:
        return None
    retry = job["attempts"] < job["maxAttempts"]
    status = JOB_QUEUED if retry else JOB_FAILED
    finished_at = None if retry else now
    with connect_job_db(path) as connection:
        connection.execute(
            """
            UPDATE background_jobs
            SET status = ?,
                error_json = ?,
                updated_at = ?,
                finished_at = ?,
                locked_by = NULL,
                locked_at = NULL
            WHERE job_id = ?
            """,
            (
                status,
                json_dumps(error if isinstance(error, dict) else {"message": str(error)}),
                now,
                finished_at,
                job_id,
            ),
        )
        connection.commit()
    return get_background_job(job_id, path=path)


def list_background_jobs(status=None, job_type=None, limit=20, path=None):
    where = []
    params = []
    if status:
        where.append("status = ?")
        params.append(status)
    if job_type:
        validate_job_type(job_type)
        where.append("job_type = ?")
        params.append(job_type)
    query = "SELECT * FROM background_jobs"
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
    params.append(max(1, min(100, int(limit))))
    with connect_job_db(path) as connection:
        rows = connection.execute(query, params).fetchall()
        return [row_to_job(row) for row in rows]


def public_job_summary(job, include_payload=False):
    if not job:
        return None
    summary = {
        "jobId": job.get("jobId"),
        "jobType": job.get("jobType"),
        "status": job.get("status"),
        "queueOperation": job.get("queueOperation"),
        "attempts": job.get("attempts"),
        "maxAttempts": job.get("maxAttempts"),
        "createdAt": job.get("createdAt"),
        "updatedAt": job.get("updatedAt"),
        "startedAt": job.get("startedAt"),
        "finishedAt": job.get("finishedAt"),
        "result": job.get("result"),
        "error": job.get("error"),
    }
    if include_payload:
        summary["payload"] = job.get("payload")
        summary["notBeforeAt"] = job.get("notBeforeAt")
        summary["lockedBy"] = job.get("lockedBy")
        summary["lockedAt"] = job.get("lockedAt")
    return summary
