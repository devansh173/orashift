"""Vocabulary for the source-unit pool: what a unit is and what it exercises."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class UnitType(StrEnum):
    """What kind of statement a unit is. Each type is verified differently."""

    QUERY = "query"
    """A SELECT. Verified by comparing result sets."""

    DDL = "ddl"
    """CREATE TABLE / INDEX / SEQUENCE / VIEW. Verified by comparing catalogue metadata."""

    DML = "dml"
    """INSERT / UPDATE / DELETE / MERGE. Verified by comparing table state inside a
    transaction that is then rolled back."""


class Category(StrEnum):
    """The Oracle construct a unit is there to exercise.

    Every metric in the final report is broken down by this, so a weak category
    cannot hide inside a good average.
    """

    # --- row limiting ---
    ROWNUM = "rownum"
    FETCH_FIRST = "fetch_first"
    # --- null handling and conditionals ---
    NVL = "nvl"
    DECODE = "decode"
    NULL_CONCAT = "null_concat"
    # --- joins ---
    OUTER_JOIN_PLUS = "outer_join_plus"
    CONNECT_BY = "connect_by"
    # --- dates ---
    SYSDATE = "sysdate"
    TO_CHAR_DATE = "to_char_date"
    ADD_MONTHS = "add_months"
    TRUNC_DATE = "trunc_date"
    # --- oracle idioms ---
    DUAL = "dual"
    MINUS = "minus"
    LISTAGG = "listagg"
    PIVOT = "pivot"
    SEQUENCE = "sequence"
    # --- general SQL ---
    ANALYTIC = "analytic"
    SUBQUERY = "subquery"
    CTE = "cte"
    AGGREGATE = "aggregate"
    STRING_FUNC = "string_func"
    # --- DDL ---
    DDL_TABLE = "ddl_table"
    DDL_CONSTRAINT = "ddl_constraint"
    DDL_INDEX = "ddl_index"
    DDL_SEQUENCE = "ddl_sequence"
    DDL_IDENTITY = "ddl_identity"
    DDL_VIEW = "ddl_view"
    # --- DML ---
    MERGE = "merge"
    DML_INSERT = "dml_insert"
    DML_UPDATE = "dml_update"
    DML_DELETE = "dml_delete"


class Source(StrEnum):
    """Where a unit came from."""

    TEMPLATE = "template"
    LLM = "llm"


class Status(StrEnum):
    """How far a unit has got through the Oracle execution filter."""

    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class Unit:
    """One candidate Oracle statement."""

    unit_key: str
    schema_name: str
    unit_type: UnitType
    category: Category
    sql_text: str
    source: Source
    template_id: str | None = None
    normalized_sql: str | None = None
    status: Status = Status.PENDING
    error: str | None = None
    duration_ms: float | None = None
    row_count: int | None = None
    metadata: dict[str, str] = field(default_factory=dict)
