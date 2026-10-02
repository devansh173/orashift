"""Build the unit pool, then filter it by running everything against Oracle."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from orashift.config import Settings
from orashift.db import oracle
from orashift.logging import get_logger
from orashift.units import store
from orashift.units.dedupe import normalize
from orashift.units.execute import DEFAULT_TIMEOUT_MS, run_unit
from orashift.units.templates import render_all, scratch_name
from orashift.units.types import Source, Status, Unit

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class GenerationSummary:
    rendered: int
    inserted: int
    collapsed: int
    """Rendered statements that normalised onto a key already present."""


@dataclass(frozen=True, slots=True)
class VerificationSummary:
    checked: int
    verified: int
    failed: int


def build_units() -> list[Unit]:
    """Render every template against every applicable schema."""
    units: list[Unit] = []
    for template, anchors, sql, combo in render_all():
        normalized, parsed = normalize(sql)
        metadata: dict[str, str] = {
            "sqlglot_parsed": str(parsed).lower(),
            "value_comparable": str(template.value_comparable).lower(),
        }
        for key, value in combo.items():
            metadata[f"param_{key}"] = value

        for index in range(template.needs_object):
            metadata[f"object_{index}"] = scratch_name(template.id, anchors.schema, index)

        resolved = anchors.as_dict()
        for index, anchor_name in enumerate(template.affects):
            metadata[f"affects_{index}"] = resolved[anchor_name]

        units.append(
            Unit(
                unit_key=store_key(normalized),
                schema_name=anchors.schema,
                unit_type=template.unit_type,
                category=template.category,
                sql_text=sql,
                source=Source.TEMPLATE,
                template_id=template.id,
                normalized_sql=normalized,
                metadata=metadata,
            )
        )
    return units


def store_key(normalized_sql: str) -> str:
    """The unit's primary key. Deriving it from the normalised SQL means
    duplicates collapse automatically on insert, rather than needing a
    separate dedupe pass."""
    return hashlib.sha256(normalized_sql.encode("utf-8")).hexdigest()[:16]


def generate(db_path: Path = store.DEFAULT_DB_PATH) -> GenerationSummary:
    """Render templates into the pool. Duplicates collapse on the primary key."""
    units = build_units()
    unique_keys = {u.unit_key for u in units}
    with store.connect(db_path) as conn:
        inserted = store.upsert_units(conn, units)
    return GenerationSummary(
        rendered=len(units),
        inserted=inserted,
        collapsed=len(units) - len(unique_keys),
    )


def verify_on_oracle(
    settings: Settings,
    db_path: Path = store.DEFAULT_DB_PATH,
    *,
    limit: int | None = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> VerificationSummary:
    """Run every pending unit against Oracle. Resumable: only touches pending."""
    checked = verified = failed = 0

    with store.connect(db_path) as conn, oracle.connect(settings) as ora:
        ora.call_timeout = timeout_ms
        pending = store.pending_units(conn, limit=limit)
        log.info("verification_started", pending=len(pending), timeout_ms=timeout_ms)

        for index, unit in enumerate(pending, start=1):
            result = run_unit(ora, unit)
            checked += 1
            if result.ok:
                verified += 1
            else:
                failed += 1
            store.record_result(
                conn,
                unit.unit_key,
                status=Status.VERIFIED if result.ok else Status.FAILED,
                error=result.error,
                duration_ms=result.duration_ms,
                row_count=result.row_count,
            )
            if index % 100 == 0:
                conn.commit()
                log.info("verification_progress", done=index, total=len(pending))

    return VerificationSummary(checked=checked, verified=verified, failed=failed)


def failure_breakdown(db_path: Path = store.DEFAULT_DB_PATH, limit: int = 20) -> list[tuple]:
    """The most common failure messages, for deciding what to fix."""
    with store.connect(db_path) as conn:
        rows: sqlite3.Cursor = conn.execute(
            """
            SELECT SUBSTR(error, 1, 60) AS reason, COUNT(*) AS n,
                   MIN(template_id) AS example_template
              FROM units WHERE status = 'failed'
             GROUP BY SUBSTR(error, 1, 60)
             ORDER BY n DESC
             LIMIT ?
            """,
            (limit,),
        )
        return [tuple(row) for row in rows]
