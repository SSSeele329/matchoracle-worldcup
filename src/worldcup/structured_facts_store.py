import hashlib
import json
import os
import sqlite3

from .provider_contracts import (
    STRUCTURED_FACTS_CATEGORY,
    STRUCTURED_FACT_AUDIT_KEYS,
    STRUCTURED_FACT_OUTPUTS,
    StructuredFactsPayloadError,
    parse_iso_timestamp,
    structured_fact_snapshot_time,
    validate_structured_facts_payload,
)
from .snapshot_store import current_utc_iso, json_dumps, json_loads


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_STRUCTURED_FACTS_STORE_PATH = os.path.join(PROJECT_ROOT, "data", "worldcup", "structured_facts.sqlite3")
STRUCTURED_FACTS_SCHEMA_VERSION = 1
STRUCTURED_FACTS_STORE_ENV = "MATCHORACLE_STRUCTURED_FACTS_STORE"


class StructuredFactsReadModelError(ValueError):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}


def structured_facts_store_path():
    return os.environ.get(STRUCTURED_FACTS_STORE_ENV, DEFAULT_STRUCTURED_FACTS_STORE_PATH)


def canonical_payload_json(payload):
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)


def structured_facts_payload_hash(payload):
    encoded = canonical_payload_json(payload).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def connect_structured_facts_db(path=None):
    path = path or structured_facts_store_path()
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    initialize_structured_facts_db(connection)
    return connection


def initialize_structured_facts_db(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS structured_fact_ingestions (
            ingestion_id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            snapshot_time TEXT NOT NULL,
            provider_id TEXT,
            provider_category TEXT NOT NULL,
            payload_hash TEXT NOT NULL UNIQUE,
            fact_keys_json TEXT NOT NULL,
            fact_counts_json TEXT NOT NULL,
            audit_metadata_json TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            ingested_at TEXT NOT NULL,
            created_by TEXT,
            schema_version INTEGER NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS structured_fact_items (
            fact_item_id TEXT PRIMARY KEY,
            ingestion_id TEXT NOT NULL,
            fact_key TEXT NOT NULL,
            item_index INTEGER NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (ingestion_id) REFERENCES structured_fact_ingestions(ingestion_id)
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_structured_fact_ingestions_source ON structured_fact_ingestions(source, snapshot_time)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_structured_fact_ingestions_hash ON structured_fact_ingestions(payload_hash)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_structured_fact_items_key ON structured_fact_items(fact_key, created_at)")
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_structured_fact_items_ingestion_key_index
        ON structured_fact_items(ingestion_id, fact_key, item_index)
        """
    )
    connection.commit()


def row_to_ingestion(row, include_payload=False):
    if not row:
        return None
    record = {
        "schemaVersion": row["schema_version"],
        "ingestionId": row["ingestion_id"],
        "source": row["source"],
        "snapshotTime": row["snapshot_time"],
        "providerId": row["provider_id"],
        "providerCategory": row["provider_category"],
        "payloadHash": row["payload_hash"],
        "factKeys": json_loads(row["fact_keys_json"]) or [],
        "factCounts": json_loads(row["fact_counts_json"]) or {},
        "auditMetadata": json_loads(row["audit_metadata_json"]) or {},
        "ingestedAt": row["ingested_at"],
        "createdBy": row["created_by"],
    }
    if include_payload:
        record["payload"] = json_loads(row["payload_json"])
    return record


def row_to_fact_item(row):
    if not row:
        return None
    return {
        "factItemId": row["fact_item_id"],
        "ingestionId": row["ingestion_id"],
        "factKey": row["fact_key"],
        "itemIndex": row["item_index"],
        "payload": json_loads(row["payload_json"]),
        "createdAt": row["created_at"],
    }


def fact_match_id(payload):
    if not isinstance(payload, dict):
        return None
    value = payload.get("matchId") or payload.get("match_id")
    if value is None:
        return None
    return str(value)


def normalize_read_model_snapshot_time(snapshot_time):
    if snapshot_time is None:
        return None
    parsed = parse_iso_timestamp(snapshot_time)
    if not parsed:
        raise StructuredFactsReadModelError(
            "STRUCTURED_FACTS_READ_SNAPSHOT_TIME_INVALID",
            "snapshotTime must be a timezone-aware ISO timestamp.",
            details={"field": "snapshotTime"},
        )
    return parsed


def validate_read_model_fact_key(fact_key):
    if fact_key is None:
        return None
    normalized = str(fact_key).strip()
    if normalized not in STRUCTURED_FACT_OUTPUTS:
        raise StructuredFactsReadModelError(
            "STRUCTURED_FACTS_READ_FACT_KEY_INVALID",
            "factKey is not an allowed structured fact key.",
            details={"factKey": normalized, "allowedFactKeys": list(STRUCTURED_FACT_OUTPUTS)},
        )
    return normalized


def validate_structured_facts_ingestion_payload(payload):
    validate_structured_facts_payload(payload)
    provider = payload.get("provider")
    if not isinstance(provider, dict) or provider.get("category") != STRUCTURED_FACTS_CATEGORY:
        raise StructuredFactsPayloadError(
            "STRUCTURED_FACTS_INGESTION_PROVIDER_INVALID",
            "Structured facts ingestion requires provider.category to be STRUCTURED_FACT_DATA_SOURCE.",
            details={"errors": ["provider.category must be STRUCTURED_FACT_DATA_SOURCE for ingestion."]},
        )
    return {"status": "PASS", "category": STRUCTURED_FACTS_CATEGORY}


def normalized_snapshot_time(payload):
    parsed = parse_iso_timestamp(structured_fact_snapshot_time(payload))
    if parsed:
        return parsed.isoformat()
    return structured_fact_snapshot_time(payload)


def audit_metadata_from_payload(payload):
    return {
        key: payload[key]
        for key in sorted(STRUCTURED_FACT_AUDIT_KEYS)
        if key in payload
    }


def fact_keys_in_payload(payload):
    facts = payload.get("facts") or {}
    return [key for key in STRUCTURED_FACT_OUTPUTS if key in facts]


def build_structured_fact_ingestion_record(payload, created_by=None, ingested_at=None):
    validate_structured_facts_ingestion_payload(payload)
    provider = payload.get("provider") or {}
    facts = payload.get("facts") or {}
    fact_keys = fact_keys_in_payload(payload)
    fact_counts = {key: len(facts.get(key) or []) for key in fact_keys}
    payload_hash = structured_facts_payload_hash(payload)
    return {
        "schemaVersion": STRUCTURED_FACTS_SCHEMA_VERSION,
        "ingestionId": "structured-facts-" + payload_hash.split(":", 1)[1][:16],
        "source": payload["source"].strip(),
        "snapshotTime": normalized_snapshot_time(payload),
        "providerId": provider.get("providerId") or provider.get("provider_id"),
        "providerCategory": provider["category"],
        "payloadHash": payload_hash,
        "factKeys": fact_keys,
        "factCounts": fact_counts,
        "auditMetadata": audit_metadata_from_payload(payload),
        "payload": payload,
        "ingestedAt": ingested_at or current_utc_iso(),
        "createdBy": created_by,
    }


def build_structured_fact_items(record):
    facts = (record.get("payload") or {}).get("facts") or {}
    items = []
    for fact_key in record.get("factKeys") or []:
        for index, payload in enumerate(facts.get(fact_key) or []):
            item_hash = structured_facts_payload_hash({
                "ingestionId": record["ingestionId"],
                "factKey": fact_key,
                "itemIndex": index,
                "payload": payload,
            }).split(":", 1)[1][:16]
            items.append({
                "factItemId": f"{record['ingestionId']}-{fact_key}-{index}-{item_hash}",
                "ingestionId": record["ingestionId"],
                "factKey": fact_key,
                "itemIndex": index,
                "payload": payload,
                "createdAt": record["ingestedAt"],
            })
    return items


def insert_structured_fact_ingestion(connection, record):
    connection.execute(
        """
        INSERT INTO structured_fact_ingestions (
            ingestion_id,
            source,
            snapshot_time,
            provider_id,
            provider_category,
            payload_hash,
            fact_keys_json,
            fact_counts_json,
            audit_metadata_json,
            payload_json,
            ingested_at,
            created_by,
            schema_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["ingestionId"],
            record["source"],
            record["snapshotTime"],
            record["providerId"],
            record["providerCategory"],
            record["payloadHash"],
            json_dumps(record["factKeys"]),
            json_dumps(record["factCounts"]),
            json_dumps(record["auditMetadata"]),
            json_dumps(record["payload"]),
            record["ingestedAt"],
            record["createdBy"],
            record["schemaVersion"],
        ),
    )
    for item in build_structured_fact_items(record):
        connection.execute(
            """
            INSERT INTO structured_fact_items (
                fact_item_id,
                ingestion_id,
                fact_key,
                item_index,
                payload_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                item["factItemId"],
                item["ingestionId"],
                item["factKey"],
                item["itemIndex"],
                json_dumps(item["payload"]),
                item["createdAt"],
            ),
        )


def get_structured_fact_ingestion_by_hash(payload_hash, path=None, include_payload=False):
    path = path or structured_facts_store_path()
    if not os.path.exists(path):
        return None
    with connect_structured_facts_db(path) as connection:
        row = connection.execute(
            """
            SELECT * FROM structured_fact_ingestions
            WHERE payload_hash = ?
            ORDER BY ingested_at DESC, rowid DESC
            LIMIT 1
            """,
            (payload_hash,),
        ).fetchone()
        return row_to_ingestion(row, include_payload=include_payload)


def get_structured_fact_ingestion(ingestion_id, path=None, include_payload=False):
    path = path or structured_facts_store_path()
    if not os.path.exists(path):
        return None
    with connect_structured_facts_db(path) as connection:
        row = connection.execute(
            """
            SELECT * FROM structured_fact_ingestions
            WHERE ingestion_id = ?
            LIMIT 1
            """,
            (ingestion_id,),
        ).fetchone()
        return row_to_ingestion(row, include_payload=include_payload)


def ingest_structured_facts_payload(payload, path=None, created_by=None):
    record = build_structured_fact_ingestion_record(payload, created_by=created_by)
    existing = get_structured_fact_ingestion_by_hash(record["payloadHash"], path=path)
    if existing:
        return {**existing, "storageOperation": "DUPLICATE_PAYLOAD"}

    with connect_structured_facts_db(path) as connection:
        connection.execute("BEGIN")
        try:
            insert_structured_fact_ingestion(connection, record)
            connection.commit()
        except sqlite3.IntegrityError:
            connection.rollback()
            existing = get_structured_fact_ingestion_by_hash(record["payloadHash"], path=path)
            if existing:
                return {**existing, "storageOperation": "DUPLICATE_PAYLOAD"}
            raise
        except Exception:
            connection.rollback()
            raise
    return {**row_to_ingestion_record(record), "storageOperation": "INSERTED"}


def row_to_ingestion_record(record):
    return {
        "schemaVersion": record["schemaVersion"],
        "ingestionId": record["ingestionId"],
        "source": record["source"],
        "snapshotTime": record["snapshotTime"],
        "providerId": record["providerId"],
        "providerCategory": record["providerCategory"],
        "payloadHash": record["payloadHash"],
        "factKeys": list(record["factKeys"]),
        "factCounts": dict(record["factCounts"]),
        "auditMetadata": dict(record["auditMetadata"]),
        "ingestedAt": record["ingestedAt"],
        "createdBy": record["createdBy"],
    }


def list_structured_fact_ingestions(source=None, limit=20, path=None):
    path = path or structured_facts_store_path()
    if not os.path.exists(path):
        return []
    where = []
    params = []
    if source:
        where.append("source = ?")
        params.append(source)
    query = "SELECT * FROM structured_fact_ingestions"
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY ingested_at DESC, rowid DESC LIMIT ?"
    params.append(int(limit))
    with connect_structured_facts_db(path) as connection:
        rows = connection.execute(query, params).fetchall()
        return [row_to_ingestion(row) for row in rows]


def list_structured_fact_items(ingestion_id=None, fact_key=None, limit=100, path=None):
    path = path or structured_facts_store_path()
    if not os.path.exists(path):
        return []
    where = []
    params = []
    if ingestion_id:
        where.append("ingestion_id = ?")
        params.append(ingestion_id)
    if fact_key:
        where.append("fact_key = ?")
        params.append(fact_key)
    query = "SELECT * FROM structured_fact_items"
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
    params.append(int(limit))
    with connect_structured_facts_db(path) as connection:
        rows = connection.execute(query, params).fetchall()
        return [row_to_fact_item(row) for row in rows]


def row_to_fact_read_model(row):
    fact = json_loads(row["payload_json"]) or {}
    return {
        "factItemId": row["fact_item_id"],
        "ingestionId": row["ingestion_id"],
        "factKey": row["fact_key"],
        "itemIndex": row["item_index"],
        "matchId": fact_match_id(fact),
        "snapshotTime": row["snapshot_time"],
        "source": row["source"],
        "providerId": row["provider_id"],
        "providerCategory": row["provider_category"],
        "ingestedAt": row["ingested_at"],
        "createdAt": row["created_at"],
        "fact": fact,
    }


def structured_fact_read_sort_key(record):
    snapshot_time = parse_iso_timestamp(record["snapshotTime"])
    ingested_at = parse_iso_timestamp(record["ingestedAt"])
    return (
        snapshot_time,
        ingested_at,
        record["factKey"],
        -record["itemIndex"],
    )


def list_structured_fact_read_rows(fact_key=None, path=None):
    path = path or structured_facts_store_path()
    if not os.path.exists(path):
        return []
    where = []
    params = []
    if fact_key:
        where.append("items.fact_key = ?")
        params.append(fact_key)
    query = """
        SELECT
            items.fact_item_id,
            items.ingestion_id,
            items.fact_key,
            items.item_index,
            items.payload_json,
            items.created_at,
            ingestions.source,
            ingestions.snapshot_time,
            ingestions.provider_id,
            ingestions.provider_category,
            ingestions.ingested_at
        FROM structured_fact_items AS items
        JOIN structured_fact_ingestions AS ingestions
          ON items.ingestion_id = ingestions.ingestion_id
    """
    if where:
        query += " WHERE " + " AND ".join(where)
    with connect_structured_facts_db(path) as connection:
        rows = connection.execute(query, params).fetchall()
        return [row_to_fact_read_model(row) for row in rows]


def get_latest_structured_facts(match_id=None, fact_key=None, snapshot_time=None, limit=100, path=None):
    """
    Return fact rows from the latest structured-facts snapshot.

    When snapshot_time is provided it is treated as an as-of upper bound:
    only facts from snapshots at or before that timezone-aware timestamp are eligible.
    The read model intentionally returns fact item payloads plus audit metadata, not the
    original ingestion payload JSON.
    """
    normalized_fact_key = validate_read_model_fact_key(fact_key)
    as_of = normalize_read_model_snapshot_time(snapshot_time)
    normalized_match_id = str(match_id) if match_id is not None else None
    rows = []
    for row in list_structured_fact_read_rows(fact_key=normalized_fact_key, path=path):
        row_snapshot_time = parse_iso_timestamp(row["snapshotTime"])
        if not row_snapshot_time:
            continue
        if as_of and row_snapshot_time > as_of:
            continue
        if normalized_match_id is not None and row["matchId"] != normalized_match_id:
            continue
        rows.append(row)

    latest_by_key = {}
    for row in rows:
        key = row["factKey"]
        row_latest_key = (
            parse_iso_timestamp(row["snapshotTime"]),
            parse_iso_timestamp(row["ingestedAt"]),
        )
        current = latest_by_key.get(key)
        if current is None or row_latest_key > current:
            latest_by_key[key] = row_latest_key

    latest_rows = [
        row
        for row in rows
        if latest_by_key.get(row["factKey"]) == (
            parse_iso_timestamp(row["snapshotTime"]),
            parse_iso_timestamp(row["ingestedAt"]),
        )
    ]
    latest_rows.sort(key=structured_fact_read_sort_key, reverse=True)
    limited_rows = latest_rows[:max(1, int(limit))]
    latest_snapshot_times = sorted(
        {row["snapshotTime"] for row in limited_rows},
        key=lambda value: parse_iso_timestamp(value),
        reverse=True,
    )
    return {
        "status": "FOUND" if limited_rows else "NOT_FOUND",
        "matchId": normalized_match_id,
        "factKey": normalized_fact_key,
        "asOfSnapshotTime": as_of.isoformat() if as_of else None,
        "latestSnapshotTime": latest_snapshot_times[0] if latest_snapshot_times else None,
        "factCount": len(limited_rows),
        "facts": limited_rows,
    }
