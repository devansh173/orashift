"""SQLite storage for the unit pool.

SQLite because the pipeline has to be resumable: generation, Oracle
verification and (in phase 3) translation each run over thousands of
statements and must survive being interrupted. A single file is also easy to
inspect with any SQL client while a run is in progress.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from orashift.units.types import Category, Source, Status, Unit, UnitType

DEFAULT_DB_PATH = Path("data/orashift.sqlite")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS units (
    unit_key        TEXT PRIMARY KEY,
    schema_name     TEXT NOT NULL,
    unit_type       TEXT NOT NULL,
    category        TEXT NOT NULL,
    sql_text        TEXT NOT NULL,
    normalized_sql  TEXT,
    source          TEXT NOT NULL,
    template_id     TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    error           TEXT,
    duration_ms     REAL,
    row_count       INTEGER,
    metadata        TEXT NOT NULL DEFAULT '{}',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    checked_at      TEXT
);

CREATE INDEX IF NOT EXISTS units_ix_status   ON units (status);
CREATE INDEX IF NOT EXISTS units_ix_category ON units (category, unit_type);
CREATE INDEX IF NOT EXISTS units_ix_schema   ON units (schema_name);
"""


@contextmanager
def connect(path: Path = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    """Open the unit database, creating it and its schema if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA_SQL)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _to_unit(row: sqlite3.Row) -> Unit:
    return Unit(
        unit_key=row["unit_key"],
        schema_name=row["schema_name"],
        unit_type=UnitType(row["unit_type"]),
        category=Category(row["category"]),
        sql_text=row["sql_text"],
        source=Source(row["source"]),
        template_id=row["template_id"],
        normalized_sql=row["normalized_sql"],
        status=Status(row["status"]),
        error=row["error"],
        duration_ms=row["duration_ms"],
        row_count=row["row_count"],
        metadata=json.loads(row["metadata"]),
    )


def upsert_units(conn: sqlite3.Connection, units: Sequence[Unit]) -> int:
    """Insert units, ignoring any whose key is already present.

    Ignoring rather than replacing is what makes generation resumable: a unit
    that has already been verified keeps its result instead of being reset to
    pending on the next run.
    """
    before = conn.execute("SELECT COUNT(*) FROM units").fetchone()[0]
    conn.executemany(
        """
        INSERT OR IGNORE INTO units
            (unit_key, schema_name, unit_type, category, sql_text,
             normalized_sql, source, template_id, status, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                u.unit_key,
                u.schema_name,
                str(u.unit_type),
                str(u.category),
                u.sql_text,
                u.normalized_sql,
                str(u.source),
                u.template_id,
                str(u.status),
                json.dumps(u.metadata, sort_keys=True),
            )
            for u in units
        ],
    )
    after = conn.execute("SELECT COUNT(*) FROM units").fetchone()[0]
    return after - before


def record_result(
    conn: sqlite3.Connection,
    unit_key: str,
    *,
    status: Status,
    error: str | None = None,
    duration_ms: float | None = None,
    row_count: int | None = None,
) -> None:
    """Store the outcome of running a unit against Oracle."""
    conn.execute(
        """
        UPDATE units
           SET status = ?,
               error = ?,
               duration_ms = ?,
               row_count = ?,
               checked_at = datetime('now')
         WHERE unit_key = ?
        """,
        (str(status), error, duration_ms, row_count, unit_key),
    )


def pending_units(conn: sqlite3.Connection, limit: int | None = None) -> list[Unit]:
    """Units that have not been run against Oracle yet."""
    sql = "SELECT * FROM units WHERE status = 'pending' ORDER BY category, unit_key"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return [_to_unit(row) for row in conn.execute(sql)]


def verified_units(conn: sqlite3.Connection) -> list[Unit]:
    """Units confirmed to run on Oracle."""
    return [
        _to_unit(row)
        for row in conn.execute(
            "SELECT * FROM units WHERE status = 'verified' ORDER BY category, unit_key"
        )
    ]


def all_units(conn: sqlite3.Connection) -> list[Unit]:
    return [_to_unit(row) for row in conn.execute("SELECT * FROM units ORDER BY unit_key")]


def mark_duplicates(conn: sqlite3.Connection, unit_keys: Sequence[str]) -> int:
    """Flag units whose normalised form matches one already kept."""
    conn.executemany(
        "UPDATE units SET status = 'duplicate' WHERE unit_key = ?",
        [(key,) for key in unit_keys],
    )
    return len(unit_keys)


def yield_report(conn: sqlite3.Connection) -> list[dict[str, object]]:
    """Per category and unit type: how many were generated, kept and dropped."""
    rows = conn.execute(
        """
        SELECT unit_type,
               category,
               COUNT(*)                                            AS total,
               SUM(status = 'verified')                            AS verified,
               SUM(status = 'failed')                              AS failed,
               SUM(status = 'duplicate')                           AS duplicate,
               SUM(status = 'pending')                             AS pending
          FROM units
         GROUP BY unit_type, category
         ORDER BY unit_type, category
        """
    ).fetchall()
    return [dict(row) for row in rows]
