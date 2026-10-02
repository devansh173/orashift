"""Run every candidate translation through the verifier and record the result."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from orashift.config import Settings
from orashift.db import oracle, postgres
from orashift.logging import get_logger
from orashift.units import store
from orashift.units.execute import split_ddl
from orashift.units.types import Unit, UnitType
from orashift.verify import ora2pg as ora2pg_tool
from orashift.verify.candidates import RENDERERS, CandidateSource
from orashift.verify.engine import (
    VerificationOutcome,
    verify_ddl,
    verify_dml,
    verify_query,
)

log = get_logger(__name__)

DEFAULT_TIMEOUT_MS = 20_000
POSTGRES_TIMEOUT_MS = 20_000


@dataclass(frozen=True, slots=True)
class RunSummary:
    source: str
    attempted: int
    verified: int
    ran: int

    @property
    def execution_accuracy(self) -> float:
        return self.verified / self.attempted if self.attempted else 0.0

    @property
    def runs_without_error(self) -> float:
        return self.ran / self.attempted if self.attempted else 0.0


def _metadata_list(unit: Unit, prefix: str) -> list[str]:
    return [v for k, v in sorted(unit.metadata.items()) if k.startswith(prefix)]


def _compare_values(unit: Unit) -> bool:
    return unit.metadata.get("value_comparable", "true") != "false"


def verify_one(
    ora_conn: object, pg_conn: object, unit: Unit, translated_sql: str
) -> VerificationOutcome:
    """Dispatch to the verifier for this unit's type."""
    compare_values = _compare_values(unit)

    if unit.unit_type is UnitType.QUERY:
        return verify_query(
            ora_conn, pg_conn, unit.sql_text, translated_sql, compare_values=compare_values
        )
    if unit.unit_type is UnitType.DDL:
        return verify_ddl(
            ora_conn, pg_conn, unit.sql_text, translated_sql, _metadata_list(unit, "object_")
        )
    return verify_dml(
        ora_conn,
        pg_conn,
        unit.sql_text,
        translated_sql,
        _metadata_list(unit, "affects_"),
        compare_values=compare_values,
    )


def run_source(
    settings: Settings,
    source: CandidateSource,
    *,
    db_path: Path = store.DEFAULT_DB_PATH,
    limit: int | None = None,
    resume: bool = True,
) -> RunSummary:
    """Verify every verified unit's translation from one candidate source."""
    renderer = RENDERERS[source]
    attempted = verified = ran = 0

    with store.connect(db_path) as conn:
        units = store.verified_units(conn)
        already = store.attempted_keys(conn, str(source)) if resume else set()
        todo = [u for u in units if u.unit_key not in already]
        if limit is not None:
            todo = todo[:limit]

        log.info(
            "verification_run_started",
            source=str(source),
            units=len(todo),
            skipped=len(units) - len(todo),
        )

        if not todo:
            return _summary_from_store(conn, source)

        with (
            oracle.connect(settings) as ora_conn,
            postgres.connect(settings, autocommit=False) as pg_conn,
        ):
            ora_conn.call_timeout = DEFAULT_TIMEOUT_MS
            with pg_conn.cursor() as cursor:
                cursor.execute(f"SET statement_timeout = {POSTGRES_TIMEOUT_MS}")
            pg_conn.commit()

            for index, unit in enumerate(todo, start=1):
                translated = renderer(unit)
                attempted += 1

                if translated is None:
                    store.record_attempt(
                        conn,
                        unit.unit_key,
                        str(source),
                        translated_sql=None,
                        ok=False,
                        reason="no candidate produced",
                        detail=f"{source} could not translate this statement",
                    )
                    continue

                outcome = verify_one(ora_conn, pg_conn, unit, translated)
                if outcome.ok:
                    verified += 1
                if outcome.ran_on_postgres:
                    ran += 1

                store.record_attempt(
                    conn,
                    unit.unit_key,
                    str(source),
                    translated_sql=translated,
                    ok=outcome.ok,
                    reason=outcome.reason,
                    detail=outcome.detail,
                    ran_on_postgres=outcome.ran_on_postgres,
                    oracle_rows=outcome.oracle_rows,
                    postgres_rows=outcome.postgres_rows,
                    duration_ms=outcome.duration_ms,
                )

                if index % 50 == 0:
                    conn.commit()
                    log.info(
                        "verification_progress",
                        source=str(source),
                        done=index,
                        total=len(todo),
                        verified=verified,
                    )

        return _summary_from_store(conn, source)


def _summary_from_store(conn: object, source: CandidateSource) -> RunSummary:
    totals = {row["source"]: row for row in store.source_totals(conn)}  # type: ignore[arg-type]
    row = totals.get(str(source))
    if row is None:
        return RunSummary(str(source), 0, 0, 0)
    return RunSummary(
        source=str(source),
        attempted=int(row["attempted"]),
        verified=int(row["verified"] or 0),
        ran=int(row["ran"] or 0),
    )


def failure_reasons(
    source: CandidateSource, db_path: Path = store.DEFAULT_DB_PATH, limit: int = 15
) -> list[tuple]:
    with store.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT a.reason, COUNT(*) AS n, MIN(u.category) AS example_category,
                   MIN(a.detail) AS example_detail
              FROM attempts a JOIN units u ON u.unit_key = a.unit_key
             WHERE a.candidate_source = ? AND a.status = 'failed'
             GROUP BY a.reason ORDER BY n DESC LIMIT ?
            """,
            (str(source), limit),
        )
        return [tuple(row) for row in rows]


def run_ora2pg(
    settings: Settings,
    *,
    db_path: Path = store.DEFAULT_DB_PATH,
    resume: bool = True,
) -> RunSummary:
    """Measure ora2pg on the DDL units.

    ora2pg exports a live Oracle schema rather than translating statements, so
    the flow differs from the other sources: every DDL unit's object is created
    on Oracle first, ora2pg is run once over all of them, and the generated
    statements are then attributed back to the unit that owns each object.

    Only DDL units are attempted. ora2pg does not translate queries or DML, so
    recording failures for those would misrepresent what the tool is for; its
    reported accuracy is over DDL only.
    """
    source = CandidateSource.ORA2PG

    with store.connect(db_path) as conn:
        ddl_units = [u for u in store.verified_units(conn) if u.unit_type is UnitType.DDL]
        already = store.attempted_keys(conn, str(source)) if resume else set()
        todo = [u for u in ddl_units if u.unit_key not in already]

        if not todo:
            log.info("ora2pg_nothing_to_do", ddl_units=len(ddl_units))
            return _summary_from_store(conn, source)

        objects_by_unit = {u.unit_key: _metadata_list(u, "object_") for u in todo}
        all_objects = sorted({name for names in objects_by_unit.values() for name in names})

        # Create every scratch object on Oracle so the export can see it.
        with oracle.connect(settings) as ora_conn:
            ora_conn.call_timeout = DEFAULT_TIMEOUT_MS
            with ora_conn.cursor() as cursor:
                for unit in todo:
                    try:
                        for statement in split_ddl(unit.sql_text):
                            cursor.execute(statement)
                    except Exception as exc:
                        log.warning("ora2pg_setup_failed", unit=unit.unit_key, error=str(exc))
                ora_conn.commit()

        try:
            raw = ora2pg_tool.export(settings, all_objects)
            statements = ora2pg_tool.split_output(raw)
            log.info("ora2pg_statements", count=len(statements))
        except ora2pg_tool.Ora2pgUnavailable as exc:
            _drop_all_oracle(settings, all_objects)
            log.error("ora2pg_unavailable", error=str(exc))
            raise

        try:
            with (
                oracle.connect(settings) as ora_conn,
                postgres.connect(settings, autocommit=False) as pg_conn,
            ):
                ora_conn.call_timeout = DEFAULT_TIMEOUT_MS
                for unit in todo:
                    owned = ora2pg_tool.statements_for(statements, objects_by_unit[unit.unit_key])
                    if not owned:
                        store.record_attempt(
                            conn,
                            unit.unit_key,
                            str(source),
                            translated_sql=None,
                            ok=False,
                            reason="no candidate produced",
                            detail="ora2pg emitted nothing for this object",
                        )
                        continue

                    candidate = "; ".join(owned)
                    outcome = verify_ddl(
                        ora_conn,
                        pg_conn,
                        unit.sql_text,
                        candidate,
                        objects_by_unit[unit.unit_key],
                    )
                    store.record_attempt(
                        conn,
                        unit.unit_key,
                        str(source),
                        translated_sql=candidate,
                        ok=outcome.ok,
                        reason=outcome.reason,
                        detail=outcome.detail,
                        ran_on_postgres=outcome.ran_on_postgres,
                        duration_ms=outcome.duration_ms,
                    )
                conn.commit()
        finally:
            _drop_all_oracle(settings, all_objects)

        return _summary_from_store(conn, source)


def _drop_all_oracle(settings: Settings, objects: list[str]) -> None:
    """Remove every scratch object created for the export."""
    from orashift.verify.engine import drop_oracle_objects

    with oracle.connect(settings) as ora_conn, ora_conn.cursor() as cursor:
        drop_oracle_objects(cursor, objects)
        ora_conn.commit()
