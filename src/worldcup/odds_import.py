import csv
import io
import os
import sqlite3
import uuid

from .market import devig_decimal_odds, safe_decimal
from .snapshot import stable_hash
from .snapshot_store import current_utc_iso, json_dumps, json_loads, parse_iso_datetime


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEFAULT_ODDS_STORE_PATH = os.path.join(PROJECT_ROOT, "data", "worldcup", "market_odds.sqlite3")

REQUIRED_COLUMNS = {
    "year",
    "date",
    "home_team",
    "away_team",
    "home_odds",
    "draw_odds",
    "away_odds",
    "snapshot_time",
    "source",
}
OPTIONAL_COLUMNS = {"odds_type"}
ALLOWED_COLUMNS = REQUIRED_COLUMNS | OPTIONAL_COLUMNS
ALLOWED_ODDS_TYPES = {"OPENING", "PREMATCH", "CLOSING"}


def odds_store_path():
    return os.environ.get("MATCHORACLE_ODDS_STORE", DEFAULT_ODDS_STORE_PATH)


def connect_odds_db(path=None):
    path = path or odds_store_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    initialize_odds_db(connection)
    return connection


def initialize_odds_db(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS market_odds_snapshots (
            odds_snapshot_id TEXT PRIMARY KEY,
            import_id TEXT NOT NULL,
            row_number INTEGER NOT NULL,
            year INTEGER NOT NULL,
            kickoff_at TEXT NOT NULL,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            odds_type TEXT NOT NULL,
            home_odds REAL NOT NULL,
            draw_odds REAL NOT NULL,
            away_odds REAL NOT NULL,
            snapshot_time TEXT NOT NULL,
            source TEXT NOT NULL,
            market_probabilities_json TEXT NOT NULL,
            overround REAL NOT NULL,
            content_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_market_odds_match ON market_odds_snapshots(year, home_team, away_team, kickoff_at)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_market_odds_snapshot_time ON market_odds_snapshots(snapshot_time)")
    connection.commit()


def row_to_market_snapshot(row):
    if not row:
        return None
    return {
        "oddsSnapshotId": row["odds_snapshot_id"],
        "importId": row["import_id"],
        "rowNumber": row["row_number"],
        "year": row["year"],
        "kickoffAt": row["kickoff_at"],
        "homeTeam": row["home_team"],
        "awayTeam": row["away_team"],
        "oddsType": row["odds_type"],
        "decimalOdds": {
            "home": row["home_odds"],
            "draw": row["draw_odds"],
            "away": row["away_odds"],
        },
        "snapshotTime": row["snapshot_time"],
        "source": row["source"],
        "marketProbabilities": json_loads(row["market_probabilities_json"]),
        "overround": row["overround"],
        "contentHash": row["content_hash"],
        "createdAt": row["created_at"],
    }


def normalize_team_name(value):
    return " ".join(str(value or "").strip().split())


def build_team_mapper(known_teams=None, team_aliases=None):
    mapping = {}
    for team in known_teams or []:
        canonical = normalize_team_name(team)
        if canonical:
            mapping[canonical.lower()] = canonical
    for alias, canonical in (team_aliases or {}).items():
        canonical_name = normalize_team_name(canonical)
        alias_name = normalize_team_name(alias)
        if canonical_name and alias_name:
            mapping[alias_name.lower()] = canonical_name
            mapping.setdefault(canonical_name.lower(), canonical_name)
    return mapping


def map_team(value, mapping):
    team = normalize_team_name(value)
    if not team:
        return None
    if not mapping:
        return team
    return mapping.get(team.lower())


def row_error(row_number, field, code, message):
    return {
        "row": row_number,
        "field": field,
        "code": code,
        "message": message,
    }


def validate_schema(fieldnames):
    fieldnames = [field.strip() for field in (fieldnames or [])]
    present = set(fieldnames)
    missing = sorted(REQUIRED_COLUMNS - present)
    unknown = sorted(present - ALLOWED_COLUMNS)
    errors = []
    for field in missing:
        errors.append({"field": field, "code": "MISSING_REQUIRED_COLUMN", "message": f"Missing required column: {field}"})
    for field in unknown:
        errors.append({"field": field, "code": "UNKNOWN_COLUMN", "message": f"Unknown column: {field}"})
    return errors


def parse_year(value):
    try:
        year = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return year if 1900 <= year <= 2100 else None


def validate_odds_csv(csv_text, known_teams=None, team_aliases=None):
    csv_text = csv_text or ""
    reader = csv.DictReader(io.StringIO(csv_text))
    global_errors = validate_schema(reader.fieldnames)
    if global_errors:
        return {"valid": False, "globalErrors": global_errors, "rowErrors": [], "rows": []}

    mapping = build_team_mapper(known_teams=known_teams, team_aliases=team_aliases)
    rows = []
    row_errors = []
    seen_keys = set()

    for row_number, raw_row in enumerate(reader, start=2):
        row = {key: (value.strip() if isinstance(value, str) else value) for key, value in raw_row.items()}
        year = parse_year(row.get("year"))
        if year is None:
            row_errors.append(row_error(row_number, "year", "INVALID_YEAR", "Year must be a four-digit number."))

        kickoff = parse_iso_datetime(row.get("date"))
        if kickoff is None:
            row_errors.append(row_error(row_number, "date", "INVALID_KICKOFF_TIME", "date must be an ISO kickoff datetime."))

        snapshot_time = parse_iso_datetime(row.get("snapshot_time"))
        if snapshot_time is None:
            row_errors.append(row_error(row_number, "snapshot_time", "INVALID_SNAPSHOT_TIME", "snapshot_time is required and must be ISO datetime."))
        elif kickoff and snapshot_time >= kickoff:
            row_errors.append(row_error(row_number, "snapshot_time", "SNAPSHOT_NOT_PREMATCH", "snapshot_time must be earlier than kickoff date."))

        home_team = map_team(row.get("home_team"), mapping)
        away_team = map_team(row.get("away_team"), mapping)
        if not home_team:
            row_errors.append(row_error(row_number, "home_team", "TEAM_MAPPING_FAILED", "home_team is blank or cannot be mapped."))
        if not away_team:
            row_errors.append(row_error(row_number, "away_team", "TEAM_MAPPING_FAILED", "away_team is blank or cannot be mapped."))
        if home_team and away_team and home_team == away_team:
            row_errors.append(row_error(row_number, "away_team", "DUPLICATE_TEAMS", "home_team and away_team map to the same team."))

        decimal_odds = {
            "home": safe_decimal(row.get("home_odds")),
            "draw": safe_decimal(row.get("draw_odds")),
            "away": safe_decimal(row.get("away_odds")),
        }
        for field, key in (("home_odds", "home"), ("draw_odds", "draw"), ("away_odds", "away")):
            if decimal_odds[key] is None:
                row_errors.append(row_error(row_number, field, "INVALID_DECIMAL_ODDS", f"{field} must be a decimal odds number greater than 1."))

        odds_type = str(row.get("odds_type") or "PREMATCH").strip().upper()
        if odds_type not in ALLOWED_ODDS_TYPES:
            row_errors.append(row_error(row_number, "odds_type", "INVALID_ODDS_TYPE", "odds_type must be OPENING, PREMATCH, or CLOSING."))

        source = normalize_team_name(row.get("source"))
        if not source:
            row_errors.append(row_error(row_number, "source", "SOURCE_REQUIRED", "source is required."))

        if year and kickoff and snapshot_time and home_team and away_team and all(decimal_odds.values()) and source:
            duplicate_key = (
                year,
                kickoff.isoformat(),
                home_team.lower(),
                away_team.lower(),
                odds_type,
                snapshot_time.isoformat(),
                source.lower(),
            )
            if duplicate_key in seen_keys:
                row_errors.append(row_error(row_number, "date", "DUPLICATE_ROW", "Duplicate odds row in CSV import."))
            seen_keys.add(duplicate_key)
            market = devig_decimal_odds(decimal_odds)
            rows.append({
                "rowNumber": row_number,
                "year": year,
                "kickoffAt": kickoff.isoformat(),
                "homeTeam": home_team,
                "awayTeam": away_team,
                "oddsType": odds_type,
                "decimalOdds": decimal_odds,
                "snapshotTime": snapshot_time.isoformat(),
                "source": source,
                "marketProbabilities": market["probabilities"],
                "overround": market["overround"],
            })

    return {
        "valid": not row_errors,
        "globalErrors": [],
        "rowErrors": row_errors,
        "rows": rows if not row_errors else [],
    }


def build_market_snapshot_record(row, import_id, created_at):
    content_hash = stable_hash({
        "year": row["year"],
        "kickoffAt": row["kickoffAt"],
        "homeTeam": row["homeTeam"],
        "awayTeam": row["awayTeam"],
        "oddsType": row["oddsType"],
        "decimalOdds": row["decimalOdds"],
        "snapshotTime": row["snapshotTime"],
        "source": row["source"],
    })
    return {
        **row,
        "oddsSnapshotId": "odds-" + content_hash,
        "importId": import_id,
        "contentHash": content_hash,
        "createdAt": created_at,
    }


def insert_market_snapshot(connection, record):
    connection.execute(
        """
        INSERT INTO market_odds_snapshots (
            odds_snapshot_id,
            import_id,
            row_number,
            year,
            kickoff_at,
            home_team,
            away_team,
            odds_type,
            home_odds,
            draw_odds,
            away_odds,
            snapshot_time,
            source,
            market_probabilities_json,
            overround,
            content_hash,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["oddsSnapshotId"],
            record["importId"],
            record["rowNumber"],
            record["year"],
            record["kickoffAt"],
            record["homeTeam"],
            record["awayTeam"],
            record["oddsType"],
            record["decimalOdds"]["home"],
            record["decimalOdds"]["draw"],
            record["decimalOdds"]["away"],
            record["snapshotTime"],
            record["source"],
            json_dumps(record["marketProbabilities"]),
            record["overround"],
            record["contentHash"],
            record["createdAt"],
        ),
    )


def import_odds_csv(csv_text, source_name=None, known_teams=None, team_aliases=None, path=None):
    validation = validate_odds_csv(csv_text, known_teams=known_teams, team_aliases=team_aliases)
    import_id = uuid.uuid4().hex
    if not validation["valid"]:
        return {
            "status": "REJECTED",
            "importId": import_id,
            "sourceName": source_name,
            "importedCount": 0,
            "skippedExistingCount": 0,
            "globalErrors": validation["globalErrors"],
            "rowErrors": validation["rowErrors"],
        }

    created_at = current_utc_iso()
    records = [build_market_snapshot_record(row, import_id, created_at) for row in validation["rows"]]
    inserted = []
    skipped = []
    with connect_odds_db(path) as connection:
        connection.execute("BEGIN")
        try:
            for record in records:
                try:
                    insert_market_snapshot(connection, record)
                    inserted.append(record)
                except sqlite3.IntegrityError:
                    skipped.append(record)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {
        "status": "IMPORTED",
        "importId": import_id,
        "sourceName": source_name,
        "importedCount": len(inserted),
        "skippedExistingCount": len(skipped),
        "globalErrors": [],
        "rowErrors": [],
        "oddsSnapshotIds": [record["oddsSnapshotId"] for record in inserted],
    }


def live_odds_snapshot_row(snapshot, source_name=None, odds_type="PREMATCH"):
    snapshot = snapshot or {}
    kickoff = parse_iso_datetime(snapshot.get("kickoffAt"))
    snapshot_time = parse_iso_datetime(snapshot.get("snapshotTime"))
    if kickoff is None or snapshot_time is None or snapshot_time >= kickoff:
        return None

    home_team = normalize_team_name(snapshot.get("homeTeam"))
    away_team = normalize_team_name(snapshot.get("awayTeam"))
    decimal_odds = {
        "home": safe_decimal((snapshot.get("decimalOdds") or {}).get("home")),
        "draw": safe_decimal((snapshot.get("decimalOdds") or {}).get("draw")),
        "away": safe_decimal((snapshot.get("decimalOdds") or {}).get("away")),
    }
    if not home_team or not away_team or home_team == away_team or not all(decimal_odds.values()):
        return None

    market = devig_decimal_odds(decimal_odds)
    source = normalize_team_name(source_name or snapshot.get("source") or snapshot.get("provider") or "live-odds-api")
    return {
        "rowNumber": 0,
        "year": kickoff.year,
        "kickoffAt": kickoff.isoformat(),
        "homeTeam": home_team,
        "awayTeam": away_team,
        "oddsType": odds_type if odds_type in ALLOWED_ODDS_TYPES else "PREMATCH",
        "decimalOdds": decimal_odds,
        "snapshotTime": snapshot_time.isoformat(),
        "source": source,
        "marketProbabilities": market["probabilities"],
        "overround": market["overround"],
    }


def import_live_odds_snapshots(snapshots, source_name=None, path=None):
    import_id = uuid.uuid4().hex
    created_at = current_utc_iso()
    rows = []
    rejected_count = 0
    for index, snapshot in enumerate(snapshots or [], start=1):
        row = live_odds_snapshot_row(snapshot, source_name=source_name)
        if row:
            row["rowNumber"] = index
            rows.append(row)
        else:
            rejected_count += 1

    records = [build_market_snapshot_record(row, import_id, created_at) for row in rows]
    inserted = []
    skipped = []
    with connect_odds_db(path) as connection:
        connection.execute("BEGIN")
        try:
            for record in records:
                try:
                    insert_market_snapshot(connection, record)
                    inserted.append(record)
                except sqlite3.IntegrityError:
                    skipped.append(record)
            connection.commit()
        except Exception:
            connection.rollback()
            raise

    return {
        "status": "IMPORTED",
        "importId": import_id,
        "sourceName": source_name,
        "importedCount": len(inserted),
        "skippedExistingCount": len(skipped),
        "rejectedCount": rejected_count,
        "oddsSnapshotIds": [record["oddsSnapshotId"] for record in inserted],
    }


def list_market_odds_snapshots(year=None, home_team=None, away_team=None, limit=20, path=None):
    where = []
    params = []
    if year is not None:
        where.append("year = ?")
        params.append(int(year))
    if home_team:
        where.append("home_team = ?")
        params.append(normalize_team_name(home_team))
    if away_team:
        where.append("away_team = ?")
        params.append(normalize_team_name(away_team))
    query = "SELECT * FROM market_odds_snapshots"
    if where:
        query += " WHERE " + " AND ".join(where)
    query += " ORDER BY snapshot_time DESC, rowid DESC LIMIT ?"
    params.append(max(1, min(100, int(limit))))
    with connect_odds_db(path) as connection:
        rows = connection.execute(query, params).fetchall()
        return [row_to_market_snapshot(row) for row in rows]
