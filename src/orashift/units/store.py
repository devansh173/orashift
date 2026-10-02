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

-- One row per (unit, candidate source). Making that pair the primary key is
-- what makes verification resumable: an attempt already recorded is skipped.
CREATE TABLE IF NOT EXISTS attempts (
    unit_key        TEXT NOT NULL,
    candidate_source TEXT NOT NULL,
    translated_sql  TEXT,
    status          TEXT NOT NULL,
    reason          TEXT,
    detail          TEXT,
    ran_on_postgres INTEGER NOT NULL DEFAULT 0,
    oracle_rows     INTEGER,
    postgres_rows   INTEGER,
    duration_ms     REAL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (unit_key, candidate_source)
);

CREATE INDEX IF NOT EXISTS attempts_ix_source ON attempts (candidate_source, status);
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
        INSERT INTO units
            (unit_key, schema_name, unit_type, category, sql_text,
             normalized_sql, source, template_id, status, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (unit_key) DO UPDATE SET
            -- Template metadata is refreshed so that changing a flag on a
            -- template (for instance marking it shape-comparable only) reaches
            -- units that already exist. Verification columns are deliberately
            -- left alone, which is what keeps a rerun resumable.
            metadata = excluded.metadata,
            template_id = excluded.template_id,
            category = excluded.category,
            normalized_sql = excluded.normalized_sql
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


# --------------------------------------------------------------------------- #
# Translation attempts
# --------------------------------------------------------------------------- #


def record_attempt(
    conn: sqlite3.Connection,
    unit_key: str,
    source: str,
    *,
    translated_sql: str | None,
    ok: bool,
    reason: str | None = None,
    detail: str | None = None,
    ran_on_postgres: bool = False,
    oracle_rows: int | None = None,
    postgres_rows: int | None = None,
    duration_ms: float | None = None,
) -> None:
    """Store one verification attempt, replacing any earlier result for that pair."""
    conn.execute(
        """
        INSERT INTO attempts
            (unit_key, candidate_source, translated_sql, status, reason, detail,
             ran_on_postgres, oracle_rows, postgres_rows, duration_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (unit_key, candidate_source) DO UPDATE SET
            translated_sql = excluded.translated_sql,
            status = excluded.status,
            reason = excluded.reason,
            detail = excluded.detail,
            ran_on_postgres = excluded.ran_on_postgres,
            oracle_rows = excluded.oracle_rows,
            postgres_rows = excluded.postgres_rows,
            duration_ms = excluded.duration_ms,
            created_at = datetime('now')
        """,
        (
            unit_key,
            source,
            translated_sql,
            "verified" if ok else "failed",
            reason,
            detail,
            int(ran_on_postgres),
            oracle_rows,
            postgres_rows,
            duration_ms,
        ),
    )


def attempted_keys(conn: sqlite3.Connection, source: str) -> set[str]:
    """Unit keys already attempted for this source, so a rerun can skip them."""
    return {
        row[0]
        for row in conn.execute(
            "SELECT unit_key FROM attempts WHERE candidate_source = ?", (source,)
        )
    }


def attempt_report(conn: sqlite3.Connection) -> list[dict[str, object]]:
    """Execution accuracy per source, unit type and category."""
    rows = conn.execute(
        """
        SELECT a.candidate_source                       AS source,
               u.unit_type                              AS unit_type,
               u.category                               AS category,
               COUNT(*)                                 AS attempted,
               SUM(a.status = 'verified')               AS verified,
               SUM(a.ran_on_postgres)                   AS ran
          FROM attempts a JOIN units u ON u.unit_key = a.unit_key
         GROUP BY a.candidate_source, u.unit_type, u.category
         ORDER BY a.candidate_source, u.unit_type, u.category
        """
    ).fetchall()
    return [dict(row) for row in rows]


def source_totals(conn: sqlite3.Connection) -> list[dict[str, object]]:
    """Headline numbers per candidate source."""
    rows = conn.execute(
        """
        SELECT candidate_source                 AS source,
               COUNT(*)                         AS attempted,
               SUM(status = 'verified')         AS verified,
               SUM(ran_on_postgres)             AS ran
          FROM attempts
         GROUP BY candidate_source
         ORDER BY verified DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def verified_pairs(conn: sqlite3.Connection, source: str = "gold") -> list[dict[str, object]]:
    """The execution-verified Oracle/PostgreSQL pairs, for phase 4."""
    rows = conn.execute(
        """
        SELECT u.unit_key, u.schema_name, u.unit_type, u.category, u.template_id,
               u.sql_text AS oracle_sql, a.translated_sql AS postgres_sql
          FROM attempts a JOIN units u ON u.unit_key = a.unit_key
         WHERE a.candidate_source = ? AND a.status = 'verified'
         ORDER BY u.schema_name, u.category, u.unit_key
        """,
        (source,),
    ).fetchall()
    return [dict(row) for row in rows]
