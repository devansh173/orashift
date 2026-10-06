"""The template library: parameterised Oracle statements, tagged by construct.

Each template is written once against the anchor names in ``anchors.py`` and is
instantiated against every schema that has the anchors it needs. Parameters
multiply that further, so a few dozen templates produce several hundred
statements across four different vocabularies.

Nothing here is trusted. Every rendered statement is run against Oracle and
thrown away if it does not execute, so a template with a syntax error costs
yield, not correctness.

A note on non-determinism: ``SYSDATE`` and sequence values change between runs.
They are still worth covering, so they are used only in ways whose *result* is
stable (``WHERE date_col < SYSDATE``, ``TRUNC(SYSDATE)``), and statements whose
value genuinely cannot match across two engines are tagged
``value_comparable=false`` for verification to handle.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from dataclasses import dataclass, field, replace

from orashift.units.anchors import ANCHORS, Anchors
from orashift.units.types import Category, UnitType


@dataclass(frozen=True, slots=True)
class Template:
    """One parameterised statement."""

    id: str
    category: Category
    sql: str
    unit_type: UnitType = UnitType.QUERY
    requires: tuple[str, ...] = ()
    """Anchor names that must exist, or the template is skipped for that schema."""
    params: dict[str, tuple[str, ...]] = field(default_factory=dict)
    affects: tuple[str, ...] = ()
    """For DML: anchor names of the tables whose state must be snapshotted."""
    value_comparable: bool = True
    """False when the result cannot be equal across engines (sequence values)."""
    needs_object: int = 0
    """How many unique scratch object names this template needs."""


def _t(
    id: str,
    category: Category,
    sql: str,
    *,
    requires: tuple[str, ...] = (),
    params: dict[str, tuple[str, ...]] | None = None,
    unit_type: UnitType = UnitType.QUERY,
    affects: tuple[str, ...] = (),
    value_comparable: bool = True,
    needs_object: int = 0,
) -> Template:
    return Template(
        id=id,
        category=category,
        sql=" ".join(sql.split()),
        unit_type=unit_type,
        requires=requires,
        params=params or {},
        affects=affects,
        value_comparable=value_comparable,
        needs_object=needs_object,
    )


C = Category

# --------------------------------------------------------------------------- #
# Row limiting
# --------------------------------------------------------------------------- #

ROW_LIMIT = [
    _t(
        "rownum_inline",
        C.ROWNUM,
        "SELECT {fact_pk} FROM {fact} WHERE ROWNUM <= {n}",
        params={"n": ("3", "10", "25")},
        value_comparable=False,
    ),
    _t(
        "rownum_ordered_subquery",
        C.ROWNUM,
        """SELECT * FROM (SELECT {dim_pk}, {dim_text} FROM {dim} ORDER BY {dim_pk})
          WHERE ROWNUM <= {n}""",
        requires=("dim", "dim_pk", "dim_text"),
        params={"n": ("5", "20")},
    ),
    _t(
        "rownum_as_column",
        C.ROWNUM,
        "SELECT ROWNUM AS rn, {fact_pk} FROM {fact} WHERE ROWNUM <= {n}",
        params={"n": ("8",)},
        value_comparable=False,
    ),
    _t(
        "rownum_pagination",
        C.ROWNUM,
        """SELECT rn, {fact_pk} FROM
            (SELECT a.{fact_pk}, ROWNUM AS rn FROM
               (SELECT {fact_pk} FROM {fact} ORDER BY {fact_pk}) a
             WHERE ROWNUM <= 20)
          WHERE rn > 10""",
    ),
    _t(
        "rownum_with_filter",
        C.ROWNUM,
        """SELECT {fact_pk}, {fact_date} FROM {fact}
          WHERE {fact_date} IS NOT NULL AND ROWNUM <= {n}""",
        params={"n": ("6",)},
        value_comparable=False,
    ),
    _t(
        "fetch_first_basic",
        C.FETCH_FIRST,
        "SELECT {dim_pk}, {dim_text} FROM {dim} ORDER BY {dim_pk} FETCH FIRST {n} ROWS ONLY",
        requires=("dim", "dim_pk", "dim_text"),
        params={"n": ("5", "15")},
    ),
    _t(
        "fetch_first_desc",
        C.FETCH_FIRST,
        "SELECT {fact_pk} FROM {fact} ORDER BY {fact_date} DESC FETCH FIRST {n} ROWS ONLY",
        params={"n": ("3", "12")},
    ),
    _t(
        "fetch_offset",
        C.FETCH_FIRST,
        """SELECT {fact_pk} FROM {fact} ORDER BY {fact_pk}
          OFFSET {k} ROWS FETCH NEXT {n} ROWS ONLY""",
        params={"k": ("5", "20"), "n": ("5",)},
    ),
    _t(
        "fetch_with_ties",
        C.FETCH_FIRST,
        """SELECT {fact_pk}, {fact_date} FROM {fact}
          ORDER BY {fact_date} FETCH FIRST {n} ROWS WITH TIES""",
        params={"n": ("4",)},
    ),
    _t(
        "fetch_percent",
        C.FETCH_FIRST,
        "SELECT {fact_pk} FROM {fact} ORDER BY {fact_pk} FETCH FIRST 5 PERCENT ROWS ONLY",
    ),
]

# --------------------------------------------------------------------------- #
# NULL handling and conditionals
# --------------------------------------------------------------------------- #

NULL_HANDLING = [
    _t(
        "nvl_numeric",
        C.NVL,
        "SELECT {fact_pk}, NVL({fact_num_nullable}, 0) AS v FROM {fact} ORDER BY {fact_pk}",
        requires=("fact_num_nullable",),
    ),
    _t(
        "nvl_dim_numeric",
        C.NVL,
        "SELECT {dim_pk}, NVL({dim_num_nullable}, {d}) AS v FROM {dim} ORDER BY {dim_pk}",
        requires=("dim", "dim_pk", "dim_num_nullable"),
        params={"d": ("0", "-1")},
    ),
    _t(
        "nvl_text",
        C.NVL,
        "SELECT {dim_pk}, NVL({dim_text_nullable}, 'UNKNOWN') AS v FROM {dim} ORDER BY {dim_pk}",
        requires=("dim", "dim_pk", "dim_text_nullable"),
    ),
    _t(
        "nvl_in_where",
        C.NVL,
        "SELECT COUNT(*) FROM {fact} WHERE NVL({fact_num_nullable}, 0) > 0",
        requires=("fact_num_nullable",),
    ),
    _t(
        "nvl_in_aggregate",
        C.NVL,
        "SELECT SUM(NVL({fact_num_nullable}, 0)) AS total FROM {fact}",
        requires=("fact_num_nullable",),
    ),
    _t(
        "nvl2_numeric",
        C.NVL,
        """SELECT {fact_pk}, NVL2({fact_num_nullable}, 'has_value', 'missing') AS v
          FROM {fact} ORDER BY {fact_pk}""",
        requires=("fact_num_nullable",),
    ),
    _t(
        "nvl2_date",
        C.NVL,
        """SELECT {fact_pk}, NVL2({fact_date2}, 'closed', 'open') AS state
          FROM {fact} ORDER BY {fact_pk}""",
        requires=("fact_date2",),
    ),
    _t(
        "coalesce_two",
        C.NVL,
        "SELECT {fact_pk}, COALESCE({fact_num_nullable}, 0) AS v FROM {fact} ORDER BY {fact_pk}",
        requires=("fact_num_nullable",),
    ),
    _t(
        "nullif_basic",
        C.NVL,
        "SELECT {fact_pk}, NULLIF({fact_num_nullable}, 0) AS v FROM {fact} ORDER BY {fact_pk}",
        requires=("fact_num_nullable",),
    ),
    _t(
        "decode_two_branch",
        C.DECODE,
        """SELECT {fact_pk}, DECODE({fact_status}, '{fact_status_value}', 1, 0) AS flag
          FROM {fact} ORDER BY {fact_pk}""",
        requires=("fact_status", "fact_status_value"),
    ),
    _t(
        "decode_with_default",
        C.DECODE,
        """SELECT {fact_pk},
                 DECODE({fact_status}, '{fact_status_value}', 'match', 'other') AS label
          FROM {fact} ORDER BY {fact_pk}""",
        requires=("fact_status", "fact_status_value"),
    ),
    _t(
        "decode_aggregate",
        C.DECODE,
        """SELECT SUM(DECODE({fact_status}, '{fact_status_value}', 1, 0)) AS matched,
                 COUNT(*) AS total
          FROM {fact}""",
        requires=("fact_status", "fact_status_value"),
    ),
    _t(
        "decode_dim",
        C.DECODE,
        """SELECT {dim_pk}, DECODE({dim_status}, '{dim_status_value}', 'Y', 'N') AS flag
          FROM {dim} ORDER BY {dim_pk}""",
        requires=("dim", "dim_pk", "dim_status", "dim_status_value"),
    ),
    _t(
        "case_equivalent",
        C.DECODE,
        """SELECT {fact_pk},
                 CASE WHEN {fact_status} = '{fact_status_value}' THEN 1 ELSE 0 END AS flag
          FROM {fact} ORDER BY {fact_pk}""",
        requires=("fact_status", "fact_status_value"),
    ),
    _t(
        "concat_nullable_text",
        C.NULL_CONCAT,
        """SELECT {dim_pk}, {dim_text} || '-' || {dim_text_nullable} AS v
           FROM {dim} ORDER BY {dim_pk}""",
        requires=("dim", "dim_pk", "dim_text", "dim_text_nullable"),
    ),
    _t(
        "concat_fact_nullable",
        C.NULL_CONCAT,
        "SELECT {fact_pk}, {fact_text_nullable} || '!' AS v FROM {fact} ORDER BY {fact_pk}",
        requires=("fact_text_nullable",),
    ),
    _t(
        "concat_guarded",
        C.NULL_CONCAT,
        """SELECT {dim_pk}, {dim_text} || NVL({dim_text_nullable}, '') AS v
          FROM {dim} ORDER BY {dim_pk}""",
        requires=("dim", "dim_pk", "dim_text", "dim_text_nullable"),
    ),
    _t(
        "null_text_count",
        C.NULL_CONCAT,
        "SELECT COUNT(*) AS n FROM {dim} WHERE {dim_text_nullable} IS NULL",
        requires=("dim", "dim_text_nullable"),
    ),
    _t(
        "concat_function",
        C.NULL_CONCAT,
        "SELECT {dim_pk}, CONCAT({dim_text}, '_x') AS v FROM {dim} ORDER BY {dim_pk}",
        requires=("dim", "dim_pk", "dim_text"),
    ),
]

# --------------------------------------------------------------------------- #
# Joins
# --------------------------------------------------------------------------- #

JOINS = [
    _t(
        "plus_left_outer",
        C.OUTER_JOIN_PLUS,
        """SELECT d.{dim_pk}, f.{fact_pk}
          FROM {dim} d, {fact} f
          WHERE d.{dim_pk} = f.{fact_fk}(+)
          ORDER BY d.{dim_pk}, f.{fact_pk}""",
        requires=("dim", "dim_pk"),
    ),
    _t(
        "plus_right_outer",
        C.OUTER_JOIN_PLUS,
        """SELECT f.{fact_pk}, d.{dim_pk}
          FROM {fact} f, {dim} d
          WHERE f.{fact_fk} = d.{dim_pk}(+)
          ORDER BY f.{fact_pk}""",
        requires=("dim", "dim_pk"),
    ),
    _t(
        "plus_with_filter",
        C.OUTER_JOIN_PLUS,
        """SELECT d.{dim_pk}, COUNT(f.{fact_pk}) AS n
          FROM {dim} d, {fact} f
          WHERE d.{dim_pk} = f.{fact_fk}(+)
          GROUP BY d.{dim_pk}
          ORDER BY d.{dim_pk}""",
        requires=("dim", "dim_pk"),
    ),
    _t(
        "ansi_left_join",
        C.OUTER_JOIN_PLUS,
        """SELECT d.{dim_pk}, COUNT(f.{fact_pk}) AS n
          FROM {dim} d LEFT JOIN {fact} f ON d.{dim_pk} = f.{fact_fk}
          GROUP BY d.{dim_pk} ORDER BY d.{dim_pk}""",
        requires=("dim", "dim_pk"),
    ),
    _t(
        "connect_by_level",
        C.CONNECT_BY,
        """SELECT {hier_pk}, {hier_label}, LEVEL AS lvl
          FROM {hier}
          START WITH {hier_parent} IS NULL
          CONNECT BY PRIOR {hier_pk} = {hier_parent}
          ORDER BY {hier_pk}""",
        requires=("hier", "hier_pk", "hier_parent", "hier_label"),
    ),
    _t(
        "connect_by_path",
        C.CONNECT_BY,
        """SELECT {hier_pk}, SYS_CONNECT_BY_PATH({hier_label}, '/') AS path
          FROM {hier}
          START WITH {hier_parent} IS NULL
          CONNECT BY PRIOR {hier_pk} = {hier_parent}
          ORDER BY {hier_pk}""",
        requires=("hier", "hier_pk", "hier_parent", "hier_label"),
    ),
    _t(
        "connect_by_root",
        C.CONNECT_BY,
        """SELECT {hier_pk}, CONNECT_BY_ROOT {hier_label} AS root_label
          FROM {hier}
          START WITH {hier_parent} IS NULL
          CONNECT BY PRIOR {hier_pk} = {hier_parent}
          ORDER BY {hier_pk}""",
        requires=("hier", "hier_pk", "hier_parent", "hier_label"),
    ),
    _t(
        "connect_by_isleaf",
        C.CONNECT_BY,
        """SELECT {hier_pk}, CONNECT_BY_ISLEAF AS is_leaf
          FROM {hier}
          START WITH {hier_parent} IS NULL
          CONNECT BY PRIOR {hier_pk} = {hier_parent}
          ORDER BY {hier_pk}""",
        requires=("hier", "hier_pk", "hier_parent"),
    ),
    _t(
        "connect_by_depth_filter",
        C.CONNECT_BY,
        """SELECT {hier_pk}, LEVEL AS lvl
          FROM {hier}
          START WITH {hier_parent} IS NULL
          CONNECT BY PRIOR {hier_pk} = {hier_parent}
          AND LEVEL <= 2
          ORDER BY {hier_pk}""",
        requires=("hier", "hier_pk", "hier_parent"),
    ),
    _t(
        "connect_by_order_siblings",
        C.CONNECT_BY,
        """SELECT {hier_pk}, LEVEL AS lvl
          FROM {hier}
          START WITH {hier_parent} IS NULL
          CONNECT BY PRIOR {hier_pk} = {hier_parent}
          ORDER SIBLINGS BY {hier_pk}""",
        requires=("hier", "hier_pk", "hier_parent"),
    ),
]

# --------------------------------------------------------------------------- #
# Dates
# --------------------------------------------------------------------------- #

DATES = [
    _t(
        "sysdate_filter_count",
        C.SYSDATE,
        "SELECT COUNT(*) AS n FROM {fact} WHERE {fact_date} < SYSDATE",
    ),
    _t(
        "sysdate_trunc",
        C.SYSDATE,
        "SELECT TRUNC(SYSDATE) AS today FROM dual",
        # Shape-only: the two engines are queried a few milliseconds apart, so a
        # run that straddles midnight legitimately gets different answers. This
        # was the residual risk recorded in decisions.md D25, and a verification
        # run crossing midnight duly hit it.
        value_comparable=False,
    ),
    _t(
        "sysdate_window",
        C.SYSDATE,
        """SELECT COUNT(*) AS n FROM {fact}
          WHERE {fact_date} BETWEEN ADD_MONTHS(SYSDATE, -{m}) AND SYSDATE""",
        params={"m": ("6", "24")},
    ),
    _t(
        "sysdate_comparison_flag",
        C.SYSDATE,
        """SELECT {fact_pk}, CASE WHEN {fact_date} > SYSDATE THEN 1 ELSE 0 END AS future
          FROM {fact} ORDER BY {fact_pk}""",
    ),
    _t(
        "to_char_date_iso",
        C.TO_CHAR_DATE,
        "SELECT {fact_pk}, TO_CHAR({fact_date}, '{mask}') AS d FROM {fact} ORDER BY {fact_pk}",
        params={"mask": ("YYYY-MM-DD", "DD/MM/YYYY", "YYYY-MM-DD HH24:MI:SS", "YYYYMM")},
    ),
    _t(
        "to_char_date_part",
        C.TO_CHAR_DATE,
        """SELECT TO_CHAR({fact_date}, '{part}') AS p, COUNT(*) AS n FROM {fact}
           GROUP BY TO_CHAR({fact_date}, '{part}') ORDER BY p""",
        params={"part": ("YYYY", "MM", "Q", "IW")},
    ),
    _t(
        "to_date_literal",
        C.TO_CHAR_DATE,
        "SELECT TO_DATE('{d}', 'YYYY-MM-DD') AS parsed FROM dual",
        params={"d": ("2024-03-07", "2026-01-31")},
    ),
    _t(
        "to_date_filter",
        C.TO_CHAR_DATE,
        """SELECT COUNT(*) AS n FROM {fact}
          WHERE {fact_date} >= TO_DATE('2025-01-01', 'YYYY-MM-DD')""",
    ),
    _t(
        "extract_from_date",
        C.TO_CHAR_DATE,
        """SELECT EXTRACT(YEAR FROM {fact_date}) AS y, COUNT(*) AS n
          FROM {fact} GROUP BY EXTRACT(YEAR FROM {fact_date}) ORDER BY y""",
    ),
    _t(
        "add_months_basic",
        C.ADD_MONTHS,
        "SELECT {fact_pk}, ADD_MONTHS({fact_date}, {m}) AS shifted FROM {fact} ORDER BY {fact_pk}",
        params={"m": ("1", "-3", "12")},
    ),
    _t(
        "months_between_cols",
        C.ADD_MONTHS,
        """SELECT {fact_pk}, MONTHS_BETWEEN({fact_date2}, {fact_date}) AS gap
          FROM {fact} ORDER BY {fact_pk}""",
        requires=("fact_date2",),
    ),
    _t(
        "months_between_rounded",
        C.ADD_MONTHS,
        """SELECT {fact_pk}, ROUND(MONTHS_BETWEEN({fact_date2}, {fact_date}), 2) AS gap
          FROM {fact} WHERE {fact_date2} IS NOT NULL ORDER BY {fact_pk}""",
        requires=("fact_date2",),
    ),
    _t(
        "last_day_basic",
        C.ADD_MONTHS,
        "SELECT {fact_pk}, LAST_DAY({fact_date}) AS eom FROM {fact} ORDER BY {fact_pk}",
    ),
    _t(
        "add_months_filter",
        C.ADD_MONTHS,
        """SELECT COUNT(*) AS n FROM {fact}
          WHERE {fact_date} < ADD_MONTHS(TO_DATE('2026-01-01','YYYY-MM-DD'), -{m})""",
        params={"m": ("6",)},
    ),
    _t(
        "trunc_date_day",
        C.TRUNC_DATE,
        "SELECT {fact_pk}, TRUNC({fact_date}) AS d FROM {fact} ORDER BY {fact_pk}",
    ),
    _t(
        "trunc_date_unit",
        C.TRUNC_DATE,
        "SELECT {fact_pk}, TRUNC({fact_date}, '{unit}') AS d FROM {fact} ORDER BY {fact_pk}",
        params={"unit": ("MM", "YYYY", "IW", "HH")},
    ),
    _t(
        "trunc_date_group",
        C.TRUNC_DATE,
        """SELECT TRUNC({fact_date}, 'MM') AS month, COUNT(*) AS n
          FROM {fact} GROUP BY TRUNC({fact_date}, 'MM') ORDER BY month""",
    ),
    _t(
        "date_difference_days",
        C.TRUNC_DATE,
        """SELECT {fact_pk}, TRUNC({fact_date2}) - TRUNC({fact_date}) AS days
          FROM {fact} WHERE {fact_date2} IS NOT NULL ORDER BY {fact_pk}""",
        requires=("fact_date2",),
    ),
]

# --------------------------------------------------------------------------- #
# Oracle idioms
# --------------------------------------------------------------------------- #

IDIOMS = [
    _t(
        "dual_literal",
        C.DUAL,
        "SELECT {v} AS v FROM dual",
        params={"v": ("1", "'hello'", "42 * 2")},
    ),
    _t("dual_integer_division", C.DUAL, "SELECT 7/2 AS v FROM dual"),
    _t("dual_string_length", C.DUAL, "SELECT LENGTH('abcdef') AS v FROM dual"),
    _t("dual_null_concat", C.DUAL, "SELECT 'a' || NULL AS v FROM dual"),
    _t("dual_arithmetic", C.DUAL, "SELECT MOD(17, 5) AS m, ABS(-3) AS a, CEIL(2.1) AS c FROM dual"),
    _t("dual_greatest", C.DUAL, "SELECT GREATEST(1, 7, 3) AS g, LEAST(1, 7, 3) AS l FROM dual"),
    _t(
        "minus_basic",
        C.MINUS,
        """SELECT {dim_pk} FROM {dim}
          MINUS
          SELECT {fact_fk} FROM {fact}""",
        requires=("dim", "dim_pk"),
    ),
    _t(
        "minus_reversed",
        C.MINUS,
        """SELECT {fact_fk} FROM {fact} WHERE {fact_fk} IS NOT NULL
          MINUS
          SELECT {dim_pk} FROM {dim} WHERE {dim_pk} > 0""",
        requires=("dim", "dim_pk"),
    ),
    _t(
        "intersect_basic",
        C.MINUS,
        """SELECT {fact_fk} FROM {fact} WHERE {fact_fk} IS NOT NULL
          INTERSECT
          SELECT {dim_pk} FROM {dim}""",
        requires=("dim", "dim_pk"),
    ),
    _t(
        "union_all_basic",
        C.MINUS,
        """SELECT {fact_pk} AS k FROM {fact} WHERE ROWNUM <= 5
          UNION ALL
          SELECT {dim_pk} AS k FROM {dim} WHERE ROWNUM <= 5""",
        requires=("dim", "dim_pk"),
        value_comparable=False,
    ),
    _t(
        "listagg_basic",
        C.LISTAGG,
        """SELECT {sum_fk},
                 LISTAGG(TO_CHAR({sum_num}), ',') WITHIN GROUP (ORDER BY {sum_num}) AS vals
          FROM {sum_table} GROUP BY {sum_fk} ORDER BY {sum_fk}""",
        requires=("sum_table", "sum_num", "sum_fk"),
    ),
    _t(
        "listagg_distinct",
        C.LISTAGG,
        """SELECT {fact_status},
                 LISTAGG(DISTINCT TO_CHAR({fact_pk}), ';')
                     WITHIN GROUP (ORDER BY TO_CHAR({fact_pk})) AS ids
          FROM {fact} GROUP BY {fact_status} ORDER BY {fact_status}""",
        requires=("fact_status",),
    ),
    _t(
        "listagg_over_all",
        C.LISTAGG,
        """SELECT LISTAGG(TO_CHAR({dim_pk}), '|') WITHIN GROUP (ORDER BY {dim_pk}) AS all_ids
          FROM (SELECT {dim_pk} FROM {dim} WHERE ROWNUM <= 10)""",
        requires=("dim", "dim_pk"),
        value_comparable=False,
    ),
    _t(
        "pivot_status_counts",
        C.PIVOT,
        """SELECT * FROM (SELECT {fact_status}, {fact_pk} FROM {fact})
          PIVOT (COUNT({fact_pk}) FOR {fact_status} IN ({pivot_in}))""",
        requires=("fact_status", "pivot_in"),
    ),
    _t(
        "unpivot_basic",
        C.PIVOT,
        """SELECT * FROM
            (SELECT {fact_pk}, {fact_date} AS d1, {fact_date} AS d2 FROM {fact} WHERE ROWNUM <= 5)
          UNPIVOT (val FOR which IN (d1, d2))""",
        value_comparable=False,
    ),
    _t(
        "sequence_nextval",
        C.SEQUENCE,
        "SELECT {seq}.NEXTVAL AS v FROM dual",
        requires=("seq",),
        value_comparable=False,
    ),
    _t(
        "sequence_nextval_expr",
        C.SEQUENCE,
        "SELECT {seq}.NEXTVAL + 0 AS v FROM dual",
        requires=("seq",),
        value_comparable=False,
    ),
]

# --------------------------------------------------------------------------- #
# General SQL
# --------------------------------------------------------------------------- #

GENERAL = [
    _t(
        "analytic_row_number",
        C.ANALYTIC,
        """SELECT {fact_pk}, {fact_fk},
                 ROW_NUMBER() OVER (PARTITION BY {fact_fk} ORDER BY {fact_pk}) AS rn
          FROM {fact} ORDER BY {fact_pk}""",
    ),
    _t(
        "analytic_rank",
        C.ANALYTIC,
        """SELECT {fact_pk}, RANK() OVER (ORDER BY {fact_date}) AS rnk,
                 DENSE_RANK() OVER (ORDER BY {fact_date}) AS drnk
          FROM {fact} ORDER BY {fact_pk}""",
    ),
    _t(
        "analytic_lag_lead",
        C.ANALYTIC,
        """SELECT {fact_pk},
                 LAG({fact_date}) OVER (ORDER BY {fact_pk}) AS prev_d,
                 LEAD({fact_date}) OVER (ORDER BY {fact_pk}) AS next_d
          FROM {fact} ORDER BY {fact_pk}""",
    ),
    _t(
        "analytic_running_sum",
        C.ANALYTIC,
        """SELECT {sum_fk}, {sum_num},
                 SUM({sum_num}) OVER (PARTITION BY {sum_fk} ORDER BY {sum_num}
                                      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running
          FROM {sum_table} ORDER BY {sum_fk}, {sum_num}""",
        requires=("sum_table", "sum_num", "sum_fk"),
    ),
    _t(
        "analytic_ntile",
        C.ANALYTIC,
        """SELECT {fact_pk}, NTILE(4) OVER (ORDER BY {fact_pk}) AS quartile
           FROM {fact} ORDER BY {fact_pk}""",
    ),
    _t(
        "analytic_first_last_value",
        C.ANALYTIC,
        """SELECT {sum_fk},
                 FIRST_VALUE({sum_num}) OVER (PARTITION BY {sum_fk} ORDER BY {sum_num}) AS lo,
                 LAST_VALUE({sum_num}) OVER (PARTITION BY {sum_fk} ORDER BY {sum_num}
                     ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS hi
          FROM {sum_table} ORDER BY {sum_fk}, {sum_num}""",
        requires=("sum_table", "sum_num", "sum_fk"),
    ),
    _t(
        "analytic_count_over",
        C.ANALYTIC,
        """SELECT {fact_pk}, COUNT(*) OVER (PARTITION BY {fact_fk}) AS peers
          FROM {fact} ORDER BY {fact_pk}""",
    ),
    _t(
        "subquery_in",
        C.SUBQUERY,
        """SELECT {fact_pk} FROM {fact}
          WHERE {fact_fk} IN (SELECT {dim_pk} FROM {dim} WHERE {dim_pk} > 0)
          ORDER BY {fact_pk}""",
        requires=("dim", "dim_pk"),
    ),
    _t(
        "subquery_exists",
        C.SUBQUERY,
        """SELECT d.{dim_pk} FROM {dim} d
          WHERE EXISTS (SELECT 1 FROM {fact} f WHERE f.{fact_fk} = d.{dim_pk})
          ORDER BY d.{dim_pk}""",
        requires=("dim", "dim_pk"),
    ),
    _t(
        "subquery_not_exists",
        C.SUBQUERY,
        """SELECT d.{dim_pk} FROM {dim} d
          WHERE NOT EXISTS (SELECT 1 FROM {fact} f WHERE f.{fact_fk} = d.{dim_pk})
          ORDER BY d.{dim_pk}""",
        requires=("dim", "dim_pk"),
    ),
    _t(
        "subquery_scalar",
        C.SUBQUERY,
        """SELECT d.{dim_pk},
                 (SELECT COUNT(*) FROM {fact} f WHERE f.{fact_fk} = d.{dim_pk}) AS n
          FROM {dim} d ORDER BY d.{dim_pk}""",
        requires=("dim", "dim_pk"),
    ),
    _t(
        "subquery_inline_view",
        C.SUBQUERY,
        """SELECT x.{fact_fk}, x.n FROM
            (SELECT {fact_fk}, COUNT(*) AS n FROM {fact} GROUP BY {fact_fk}) x
          WHERE x.n > 1 ORDER BY x.{fact_fk}""",
    ),
    _t(
        "cte_single",
        C.CTE,
        """WITH counts AS (SELECT {fact_fk} AS k, COUNT(*) AS n FROM {fact} GROUP BY {fact_fk})
          SELECT k, n FROM counts WHERE n > 1 ORDER BY k""",
    ),
    _t(
        "cte_two",
        C.CTE,
        """WITH a AS (SELECT {fact_fk} AS k, COUNT(*) AS n FROM {fact} GROUP BY {fact_fk}),
               b AS (SELECT k, n FROM a WHERE n >= 2)
          SELECT k, n FROM b ORDER BY k""",
    ),
    _t(
        "cte_joined",
        C.CTE,
        """WITH agg AS (SELECT {fact_fk} AS k, COUNT(*) AS n FROM {fact} GROUP BY {fact_fk})
          SELECT d.{dim_pk}, NVL(agg.n, 0) AS n
          FROM {dim} d LEFT JOIN agg ON agg.k = d.{dim_pk}
          ORDER BY d.{dim_pk}""",
        requires=("dim", "dim_pk"),
    ),
    _t(
        "aggregate_group_by",
        C.AGGREGATE,
        """SELECT {sum_fk}, COUNT(*) AS n, SUM({sum_num}) AS total, AVG({sum_num}) AS mean
          FROM {sum_table} GROUP BY {sum_fk} ORDER BY {sum_fk}""",
        requires=("sum_table", "sum_num", "sum_fk"),
    ),
    _t(
        "aggregate_having",
        C.AGGREGATE,
        """SELECT {sum_fk}, COUNT(*) AS n FROM {sum_table}
          GROUP BY {sum_fk} HAVING COUNT(*) > {n} ORDER BY {sum_fk}""",
        requires=("sum_table", "sum_fk"),
        params={"n": ("1", "3")},
    ),
    _t(
        "aggregate_count_distinct", C.AGGREGATE, "SELECT COUNT(DISTINCT {fact_fk}) AS n FROM {fact}"
    ),
    _t(
        "aggregate_minmax",
        C.AGGREGATE,
        "SELECT MIN({fact_date}) AS lo, MAX({fact_date}) AS hi FROM {fact}",
    ),
    _t(
        "aggregate_rollup",
        C.AGGREGATE,
        """SELECT {fact_status}, COUNT(*) AS n FROM {fact}
          GROUP BY ROLLUP({fact_status}) ORDER BY {fact_status}""",
        requires=("fact_status",),
    ),
    _t(
        "aggregate_grouping_sets",
        C.AGGREGATE,
        """SELECT {fact_status}, {fact_fk}, COUNT(*) AS n FROM {fact}
          GROUP BY GROUPING SETS (({fact_status}), ({fact_fk}))
          ORDER BY {fact_status}, {fact_fk}""",
        requires=("fact_status",),
    ),
    _t(
        "string_substr_instr",
        C.STRING_FUNC,
        """SELECT {dim_pk}, SUBSTR({dim_text}, 1, 3) AS s, INSTR({dim_text}, 'a') AS i
          FROM {dim} ORDER BY {dim_pk}""",
        requires=("dim", "dim_pk", "dim_text"),
    ),
    _t(
        "string_case_funcs",
        C.STRING_FUNC,
        """SELECT {dim_pk}, UPPER({dim_text}) AS u, LOWER({dim_text}) AS l,
                 INITCAP({dim_text}) AS c
          FROM {dim} ORDER BY {dim_pk}""",
        requires=("dim", "dim_pk", "dim_text"),
    ),
    _t(
        "string_pad_trim",
        C.STRING_FUNC,
        """SELECT {dim_pk}, LPAD({dim_text}, 20, '.') AS p, TRIM({dim_text}) AS t
          FROM {dim} ORDER BY {dim_pk}""",
        requires=("dim", "dim_pk", "dim_text"),
    ),
    _t(
        "string_replace",
        C.STRING_FUNC,
        "SELECT {dim_pk}, REPLACE({dim_text}, 'a', 'A') AS r FROM {dim} ORDER BY {dim_pk}",
        requires=("dim", "dim_pk", "dim_text"),
    ),
    _t(
        "string_regexp",
        C.STRING_FUNC,
        """SELECT {dim_pk}, REGEXP_SUBSTR({dim_text}, '[A-Za-z]+') AS word
          FROM {dim} WHERE REGEXP_LIKE({dim_text}, '^[A-Z]') ORDER BY {dim_pk}""",
        requires=("dim", "dim_pk", "dim_text"),
    ),
    _t(
        "string_length_funcs",
        C.STRING_FUNC,
        """SELECT {dim_pk}, LENGTH({dim_text}) AS n FROM {dim}
          WHERE LENGTH({dim_text}) > {n} ORDER BY {dim_pk}""",
        requires=("dim", "dim_pk", "dim_text"),
        params={"n": ("5", "10")},
    ),
]

# --------------------------------------------------------------------------- #
# DDL. Each creates a uniquely named scratch object, which the runner drops.
# --------------------------------------------------------------------------- #

DDL = [
    _t(
        "ddl_table_basic",
        C.DDL_TABLE,
        """CREATE TABLE {obj0} (
            id          NUMBER(10)      NOT NULL,
            label       VARCHAR2(60)    NOT NULL,
            amount      NUMBER(12,2),
            created_at  DATE            DEFAULT SYSDATE NOT NULL
          )""",
        unit_type=UnitType.DDL,
        needs_object=1,
    ),
    _t(
        "ddl_table_all_types",
        C.DDL_TABLE,
        """CREATE TABLE {obj0} (
            n_small     NUMBER(4),
            n_int       NUMBER(9),
            n_big       NUMBER(18),
            n_dec       NUMBER(12,4),
            v_short     VARCHAR2(10),
            v_long      VARCHAR2(4000),
            c_fixed     CHAR(3),
            d_date      DATE,
            t_stamp     TIMESTAMP(6),
            big_text    CLOB
          )""",
        unit_type=UnitType.DDL,
        needs_object=1,
    ),
    _t(
        "ddl_table_constraints",
        C.DDL_CONSTRAINT,
        """CREATE TABLE {obj0} (
            id      NUMBER(10)      NOT NULL,
            code    VARCHAR2(20)    NOT NULL,
            state   VARCHAR2(10)    DEFAULT 'NEW' NOT NULL,
            qty     NUMBER(6)       NOT NULL,
            CONSTRAINT {obj0}_pk PRIMARY KEY (id),
            CONSTRAINT {obj0}_uq UNIQUE (code),
            CONSTRAINT {obj0}_ck CHECK (qty > 0),
            CONSTRAINT {obj0}_ck2 CHECK (state IN ('NEW', 'DONE'))
          )""",
        unit_type=UnitType.DDL,
        needs_object=1,
    ),
    _t(
        "ddl_table_composite_pk",
        C.DDL_CONSTRAINT,
        """CREATE TABLE {obj0} (
            parent_id   NUMBER(10)  NOT NULL,
            line_no     NUMBER(4)   NOT NULL,
            note        VARCHAR2(80),
            CONSTRAINT {obj0}_pk PRIMARY KEY (parent_id, line_no)
          )""",
        unit_type=UnitType.DDL,
        needs_object=1,
    ),
    _t(
        "ddl_table_fk",
        C.DDL_CONSTRAINT,
        """CREATE TABLE {obj0} (
            id          NUMBER(10)  NOT NULL,
            ref_id      NUMBER(10),
            CONSTRAINT {obj0}_pk PRIMARY KEY (id),
            CONSTRAINT {obj0}_fk FOREIGN KEY (ref_id) REFERENCES {obj0} (id)
          )""",
        unit_type=UnitType.DDL,
        needs_object=1,
    ),
    _t(
        "ddl_index_single",
        C.DDL_INDEX,
        """CREATE TABLE {obj0} (id NUMBER(10), label VARCHAR2(40));
          CREATE INDEX {obj1} ON {obj0} (label)""",
        unit_type=UnitType.DDL,
        needs_object=2,
    ),
    _t(
        "ddl_index_composite",
        C.DDL_INDEX,
        """CREATE TABLE {obj0} (a NUMBER(10), b NUMBER(10), c DATE);
          CREATE INDEX {obj1} ON {obj0} (a, b DESC)""",
        unit_type=UnitType.DDL,
        needs_object=2,
    ),
    _t(
        "ddl_sequence_basic",
        C.DDL_SEQUENCE,
        "CREATE SEQUENCE {obj0} START WITH 1 INCREMENT BY 1 NOCACHE NOCYCLE",
        unit_type=UnitType.DDL,
        needs_object=1,
    ),
    _t(
        "ddl_sequence_options",
        C.DDL_SEQUENCE,
        "CREATE SEQUENCE {obj0} START WITH 500 INCREMENT BY 10 MAXVALUE 100000 CACHE 20 CYCLE",
        unit_type=UnitType.DDL,
        needs_object=1,
    ),
    _t(
        "ddl_identity_always",
        C.DDL_IDENTITY,
        """CREATE TABLE {obj0} (
            id      NUMBER GENERATED ALWAYS AS IDENTITY,
            label   VARCHAR2(40) NOT NULL,
            CONSTRAINT {obj0}_pk PRIMARY KEY (id)
          )""",
        unit_type=UnitType.DDL,
        needs_object=1,
    ),
    _t(
        "ddl_identity_by_default",
        C.DDL_IDENTITY,
        """CREATE TABLE {obj0} (
            id      NUMBER GENERATED BY DEFAULT AS IDENTITY START WITH 100 INCREMENT BY 5,
            label   VARCHAR2(40)
          )""",
        unit_type=UnitType.DDL,
        needs_object=1,
    ),
    _t(
        "ddl_view_simple",
        C.DDL_VIEW,
        "CREATE VIEW {obj0} AS SELECT {fact_pk}, {fact_date} FROM {fact}",
        unit_type=UnitType.DDL,
        needs_object=1,
    ),
    _t(
        "ddl_view_aggregate",
        C.DDL_VIEW,
        """CREATE VIEW {obj0} AS
          SELECT {fact_fk} AS k, COUNT(*) AS n FROM {fact} GROUP BY {fact_fk}""",
        unit_type=UnitType.DDL,
        needs_object=1,
    ),
    _t(
        "ddl_view_with_nvl",
        C.DDL_VIEW,
        """CREATE VIEW {obj0} AS
          SELECT {fact_pk}, NVL({fact_num_nullable}, 0) AS v FROM {fact}""",
        unit_type=UnitType.DDL,
        requires=("fact_num_nullable",),
        needs_object=1,
    ),
]

# --------------------------------------------------------------------------- #
# DML. Verified inside a transaction that is rolled back, so the seed data is
# never permanently changed.
# --------------------------------------------------------------------------- #

DML = [
    _t(
        "dml_update_numeric",
        C.DML_UPDATE,
        """UPDATE {fact} SET {fact_num_nullable} = NVL({fact_num_nullable}, 0) + 1
           WHERE {fact_pk} <= 0""",
        unit_type=UnitType.DML,
        requires=("fact_num_nullable",),
        affects=("fact",),
    ),
    _t(
        "dml_update_all_matching",
        C.DML_UPDATE,
        """UPDATE {fact} SET {fact_status} = '{fact_status_value}'
          WHERE {fact_status} <> '{fact_status_value}'""",
        unit_type=UnitType.DML,
        requires=("fact_status", "fact_status_value"),
        affects=("fact",),
    ),
    _t(
        "dml_update_from_subquery",
        C.DML_UPDATE,
        """UPDATE {fact} SET {fact_date} = {fact_date} + 1
          WHERE {fact_fk} IN (SELECT {dim_pk} FROM {dim} WHERE ROWNUM <= 3)""",
        unit_type=UnitType.DML,
        requires=("dim", "dim_pk"),
        affects=("fact",),
        value_comparable=False,
    ),
    _t(
        "dml_delete_filtered",
        C.DML_DELETE,
        "DELETE FROM {fact} WHERE {fact_pk} < 0",
        unit_type=UnitType.DML,
        affects=("fact",),
    ),
    _t(
        "dml_delete_subquery",
        C.DML_DELETE,
        """DELETE FROM {fact}
          WHERE {fact_fk} NOT IN (SELECT {dim_pk} FROM {dim})""",
        unit_type=UnitType.DML,
        requires=("dim", "dim_pk"),
        affects=("fact",),
    ),
    _t(
        "dml_insert_select",
        C.DML_INSERT,
        """INSERT INTO {fact} ({fact_pk}, {fact_fk}, {fact_date})
          SELECT {fact_pk} + 900000, {fact_fk}, {fact_date} FROM {fact} WHERE 1 = 0""",
        unit_type=UnitType.DML,
        affects=("fact",),
    ),
    _t(
        "merge_update_only",
        C.MERGE,
        """MERGE INTO {fact} t
          USING (SELECT {fact_pk} AS k FROM {fact} WHERE ROWNUM <= 5) s
          ON (t.{fact_pk} = s.k)
          WHEN MATCHED THEN UPDATE SET t.{fact_date} = t.{fact_date}""",
        unit_type=UnitType.DML,
        affects=("fact",),
    ),
    _t(
        "merge_with_condition",
        C.MERGE,
        """MERGE INTO {fact} t
          USING (SELECT {dim_pk} AS k FROM {dim}) s
          ON (t.{fact_fk} = s.k)
          WHEN MATCHED THEN UPDATE SET t.{fact_date} = t.{fact_date}
          WHERE t.{fact_pk} < 0""",
        unit_type=UnitType.DML,
        requires=("dim", "dim_pk"),
        affects=("fact",),
    ),
]

ALL_TEMPLATES: list[Template] = [
    *ROW_LIMIT,
    *NULL_HANDLING,
    *JOINS,
    *DATES,
    *IDIOMS,
    *GENERAL,
    *DDL,
    *DML,
]


def _param_combinations(template: Template) -> Iterator[dict[str, str]]:
    if not template.params:
        yield {}
        return
    keys = sorted(template.params)
    for values in itertools.product(*(template.params[k] for k in keys)):
        yield dict(zip(keys, values, strict=True))


def scratch_name(template_id: str, schema: str, index: int) -> str:
    """A unique, short, droppable name for a DDL scratch object."""
    stem = f"tmp_{template_id}_{schema}".replace("-", "_")
    return f"{stem[:24]}_{index}"


def render(template: Template, anchors: Anchors) -> list[tuple[str, dict[str, str]]]:
    """Instantiate one template for one schema. Empty if anchors are missing."""
    if not anchors.has(*template.requires):
        return []

    base = anchors.as_dict()
    objects = {
        f"obj{i}": scratch_name(template.id, anchors.schema, i)
        for i in range(template.needs_object)
    }

    rendered: list[tuple[str, dict[str, str]]] = []
    for combo in _param_combinations(template):
        try:
            sql = template.sql.format(**base, **objects, **combo)
        except KeyError:
            # The template references an anchor this schema does not declare.
            # requires= should prevent it, but skipping is safer than emitting
            # a statement with a literal brace in it.
            continue
        rendered.append((sql, combo))
    return rendered


def render_all() -> Iterator[tuple[Template, Anchors, str, dict[str, str]]]:
    """Every template against every schema it applies to."""
    for template in ALL_TEMPLATES:
        for anchors in ANCHORS.values():
            for sql, combo in render(template, anchors):
                yield template, anchors, sql, combo


# --------------------------------------------------------------------------- #
# Parameter expansion
#
# Widening the value lists on templates that already take parameters multiplies
# the pool without needing a single new translation, because translations are
# keyed by template rather than by rendered statement. That is the cheapest way
# to reach a defensible training-set size: the alternative, writing more
# templates, costs a hand-written PostgreSQL counterpart each time.
#
# Kept separate from the template definitions so the two concerns stay legible:
# above is what each construct looks like, here is how widely it is sampled.
# --------------------------------------------------------------------------- #

_PARAM_EXPANSIONS: dict[str, dict[str, tuple[str, ...]]] = {
    "rownum_inline": {"n": ("1", "2", "3", "5", "10", "15", "25", "50")},
    "rownum_ordered_subquery": {"n": ("1", "5", "10", "20", "40")},
    "rownum_as_column": {"n": ("3", "8", "15", "30")},
    "rownum_with_filter": {"n": ("2", "6", "12", "20")},
    "fetch_first_basic": {"n": ("1", "5", "10", "15", "30")},
    "fetch_first_desc": {"n": ("1", "3", "7", "12", "25")},
    "fetch_offset": {"k": ("0", "5", "10", "20", "50"), "n": ("1", "3", "5")},
    "fetch_with_ties": {"n": ("2", "4", "6", "8")},
    "nvl_dim_numeric": {"d": ("0", "-1", "1", "999")},
    "sysdate_window": {"m": ("1", "3", "6", "12", "24", "36")},
    "to_char_date_iso": {
        "mask": (
            "YYYY-MM-DD",
            "DD/MM/YYYY",
            "YYYY-MM-DD HH24:MI:SS",
            "YYYYMM",
            "YYYY",
            "MM-DD",
            "DD-MM-YYYY HH24:MI",
            "YYYY/MM/DD",
            "HH24:MI:SS",
            "YYYYMMDD",
        )
    },
    "to_char_date_part": {"part": ("YYYY", "MM", "DD", "Q", "IW", "WW", "HH24")},
    "to_date_literal": {
        "d": ("2024-03-07", "2026-01-31", "1999-12-31", "2020-02-29", "2025-07-04", "2000-01-01")
    },
    "add_months_basic": {"m": ("1", "-1", "2", "3", "-3", "6", "-6", "12", "-12", "24")},
    "add_months_filter": {"m": ("1", "3", "6", "12", "24")},
    # New TRUNC units need a matching entry in the translation's param_translate.
    "trunc_date_unit": {"unit": ("MM", "YYYY", "IW", "HH", "DD", "Q", "MI")},
    "dual_literal": {
        "v": ("1", "0", "-7", "'hello'", "'world'", "42 * 2", "2 + 3", "100 - 1", "'orashift'")
    },
    "aggregate_having": {"n": ("0", "1", "2", "3", "5", "10")},
    "string_length_funcs": {"n": ("3", "4", "5", "8", "10", "15")},
}


def _expanded(templates: list[Template]) -> list[Template]:
    """Apply the wider parameter lists, leaving everything else untouched."""
    out: list[Template] = []
    for template in templates:
        extra = _PARAM_EXPANSIONS.get(template.id)
        if extra is None:
            out.append(template)
            continue
        unknown = set(extra) - set(template.params)
        if unknown:
            raise ValueError(f"{template.id}: expansion names unknown parameters {unknown}")
        out.append(replace(template, params={**template.params, **extra}))
    return out


ALL_TEMPLATES = _expanded(ALL_TEMPLATES)


HELD_OUT_TEMPLATES: frozenset[str] = frozenset(
    {
        # Row limiting
        "rownum_pagination",
        "fetch_with_ties",
        # Null handling
        "nvl2_date",
        "decode_dim",
        "concat_guarded",
        # Joins
        "plus_right_outer",
        "connect_by_isleaf",
        # Dates
        "sysdate_window",
        "to_char_date_part",
        "months_between_rounded",
        "trunc_date_group",
        # Idioms
        "dual_greatest",
        "intersect_basic",
        "listagg_distinct",
        "unpivot_basic",
        # General SQL
        "analytic_ntile",
        "subquery_scalar",
        "cte_two",
        "aggregate_grouping_sets",
        "string_replace",
        # DDL
        "ddl_table_composite_pk",
        "ddl_sequence_options",
        "ddl_view_aggregate",
        # DML
        "dml_delete_subquery",
        "merge_with_condition",
    }
)
"""Templates withheld from training entirely, as a second generalisation axis.

Holding out a schema alone measures less than it appears to: if the same
template is seen during training as `retail` and tested as `logistics`, the
model has already met that exact translation pattern and only the table names
are new. Withholding whole templates as well gives three honest test buckets --
unseen schema, unseen template, and unseen both.

Every one of these is a secondary variant of its category, so each category is
still represented in training. A test enforces that.
"""


def training_templates() -> list[Template]:
    return [t for t in ALL_TEMPLATES if t.id not in HELD_OUT_TEMPLATES]


def held_out_templates() -> list[Template]:
    return [t for t in ALL_TEMPLATES if t.id in HELD_OUT_TEMPLATES]
