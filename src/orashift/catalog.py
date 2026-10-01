"""The catalogue of synthetic schemas.

This module is the single Python-side description of the seed data's shape. It
exists so the CSV loader knows how to coerce each column and in what order to
insert tables without tripping a foreign key.

The DDL files under ``sql/schemas/`` remain the source of truth for the
databases themselves. Drift between the two is caught automatically by the
``db``-marked tests, which introspect both live catalogues and compare them
against this module.

Table names are prefixed with their domain because in Oracle a schema *is* a
user: four real schemas would mean four accounts and broader grants. See
docs/decisions.md D14.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ValueKind(StrEnum):
    """How a CSV field should be coerced before it is bound to a parameter."""

    INT = "int"
    NUMERIC = "numeric"
    TEXT = "text"
    TIMESTAMP = "timestamp"


@dataclass(frozen=True, slots=True)
class Column:
    name: str
    kind: ValueKind
    nullable: bool = True


@dataclass(frozen=True, slots=True)
class Table:
    name: str
    columns: tuple[Column, ...]

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)


@dataclass(frozen=True, slots=True)
class Schema:
    name: str
    description: str
    tables: tuple[Table, ...]
    """Ordered so that inserting front to back never violates a foreign key."""
    sequences: tuple[str, ...] = ()
    views: tuple[str, ...] = ()

    @property
    def table_names(self) -> tuple[str, ...]:
        return tuple(t.name for t in self.tables)


def _c(name: str, kind: ValueKind, *, null: bool = True) -> Column:
    return Column(name=name, kind=kind, nullable=null)


INT, NUM, TXT, TS = ValueKind.INT, ValueKind.NUMERIC, ValueKind.TEXT, ValueKind.TIMESTAMP

RETAIL = Schema(
    name="retail",
    description="Online storefront: a category tree, products, orders and order lines.",
    sequences=("retail_customer_seq", "retail_order_seq"),
    views=("retail_order_totals",),
    tables=(
        Table(
            "retail_categories",
            (
                _c("category_id", INT, null=False),
                _c("category_name", TXT, null=False),
                _c("parent_category_id", INT),
                _c("sort_order", INT, null=False),
            ),
        ),
        Table(
            "retail_customers",
            (
                _c("customer_id", INT, null=False),
                _c("email", TXT, null=False),
                _c("full_name", TXT, null=False),
                _c("signup_date", TS, null=False),
                _c("loyalty_tier", TXT, null=False),
                _c("credit_limit", NUM),
                _c("is_active", INT, null=False),
            ),
        ),
        Table(
            "retail_products",
            (
                _c("product_id", INT, null=False),
                _c("sku", TXT, null=False),
                _c("product_name", TXT, null=False),
                _c("category_id", INT, null=False),
                _c("unit_price", NUM, null=False),
                _c("description", TXT),
                _c("launched_on", TS),
            ),
        ),
        Table(
            "retail_orders",
            (
                _c("order_id", INT, null=False),
                _c("customer_id", INT, null=False),
                _c("order_date", TS, null=False),
                _c("status", TXT, null=False),
                _c("discount_pct", NUM),
                _c("notes", TXT),
            ),
        ),
        Table(
            "retail_order_items",
            (
                _c("order_id", INT, null=False),
                _c("line_no", INT, null=False),
                _c("product_id", INT, null=False),
                _c("quantity", INT, null=False),
                _c("unit_price", NUM, null=False),
            ),
        ),
    ),
)

HR = Schema(
    name="hr",
    description="Employees, jobs and a management hierarchy.",
    sequences=("hr_employee_seq",),
    views=("hr_employee_directory",),
    tables=(
        Table(
            "hr_departments",
            (
                _c("department_id", INT, null=False),
                _c("department_name", TXT, null=False),
                _c("location", TXT),
            ),
        ),
        Table(
            "hr_jobs",
            (
                _c("job_id", TXT, null=False),
                _c("job_title", TXT, null=False),
                _c("min_salary", NUM, null=False),
                _c("max_salary", NUM, null=False),
            ),
        ),
        Table(
            "hr_pay_grades",
            (
                _c("grade_code", TXT, null=False),
                _c("min_salary", NUM, null=False),
                _c("max_salary", NUM, null=False),
            ),
        ),
        Table(
            "hr_employees",
            (
                _c("employee_id", INT, null=False),
                _c("first_name", TXT, null=False),
                _c("last_name", TXT, null=False),
                _c("email", TXT, null=False),
                _c("hire_date", TS, null=False),
                _c("job_id", TXT, null=False),
                _c("salary", NUM, null=False),
                _c("commission_pct", NUM),
                _c("manager_id", INT),
                _c("department_id", INT),
            ),
        ),
        Table(
            "hr_job_history",
            (
                _c("employee_id", INT, null=False),
                _c("start_date", TS, null=False),
                _c("end_date", TS),
                _c("job_id", TXT, null=False),
                _c("department_id", INT),
            ),
        ),
    ),
)

LIBRARY = Schema(
    name="library",
    description="Lending library: authors, titles, physical copies, members and loans.",
    sequences=("library_loan_seq",),
    views=("library_active_loans",),
    tables=(
        Table(
            "library_authors",
            (
                _c("author_id", INT, null=False),
                _c("full_name", TXT, null=False),
                _c("birth_year", INT),
                _c("country_code", TXT),
            ),
        ),
        Table(
            "library_books",
            (
                _c("book_id", INT, null=False),
                _c("isbn13", TXT, null=False),
                _c("title", TXT, null=False),
                _c("author_id", INT, null=False),
                _c("published_on", TS),
                _c("page_count", INT),
                _c("summary", TXT),
            ),
        ),
        Table(
            "library_copies",
            (
                _c("copy_id", INT, null=False),
                _c("book_id", INT, null=False),
                _c("acquired_on", TS, null=False),
                _c("shelf_code", TXT, null=False),
                _c("condition_rating", INT),
            ),
        ),
        Table(
            "library_members",
            (
                _c("member_id", INT, null=False),
                _c("member_name", TXT, null=False),
                _c("joined_on", TS, null=False),
                _c("email", TXT),
                _c("membership_type", TXT, null=False),
            ),
        ),
        Table(
            "library_loans",
            (
                _c("loan_id", INT, null=False),
                _c("copy_id", INT, null=False),
                _c("member_id", INT, null=False),
                _c("borrowed_at", TS, null=False),
                _c("due_date", TS, null=False),
                _c("returned_at", TS),
                _c("late_fee", NUM, null=False),
            ),
        ),
    ),
)

LOGISTICS = Schema(
    name="logistics",
    description="Freight movement: warehouses, carriers, shipments, legs and tracking events.",
    sequences=("logistics_shipment_seq",),
    views=("logistics_shipment_summary",),
    tables=(
        Table(
            "logistics_warehouses",
            (
                _c("warehouse_id", INT, null=False),
                _c("warehouse_code", TXT, null=False),
                _c("city", TXT, null=False),
                _c("country_code", TXT, null=False),
                _c("capacity_pallets", INT),
            ),
        ),
        Table(
            "logistics_carriers",
            (
                _c("carrier_id", INT, null=False),
                _c("carrier_name", TXT, null=False),
                _c("scac_code", TXT),
                _c("is_bonded", INT, null=False),
            ),
        ),
        Table(
            "logistics_shipments",
            (
                _c("shipment_id", INT, null=False),
                _c("tracking_ref", TXT, null=False),
                _c("origin_warehouse_id", INT, null=False),
                _c("dest_warehouse_id", INT, null=False),
                _c("carrier_id", INT),
                _c("dispatched_at", TS, null=False),
                _c("delivered_at", TS),
                _c("gross_weight_kg", NUM),
                _c("status", TXT, null=False),
            ),
        ),
        Table(
            "logistics_shipment_legs",
            (
                _c("leg_id", INT, null=False),
                _c("shipment_id", INT, null=False),
                _c("leg_seq", INT, null=False),
                _c("parent_leg_id", INT),
                _c("from_warehouse_id", INT, null=False),
                _c("to_warehouse_id", INT, null=False),
                _c("departed_at", TS, null=False),
                _c("arrived_at", TS),
            ),
        ),
        Table(
            "logistics_tracking_events",
            (
                _c("event_id", INT, null=False),
                _c("shipment_id", INT, null=False),
                _c("event_at", TS, null=False),
                _c("event_code", TXT, null=False),
                _c("location_city", TXT),
                _c("remarks", TXT),
            ),
        ),
    ),
)

SCHEMAS: dict[str, Schema] = {s.name: s for s in (RETAIL, HR, LIBRARY, LOGISTICS)}

HELD_OUT_SCHEMA = "logistics"
"""Fully held out of training in phase 4, to measure generalisation to unseen tables."""

SCHEMA_NAMES = tuple(SCHEMAS)


def get_schema(name: str) -> Schema:
    """Look up a schema by name, with a helpful error for a typo."""
    try:
        return SCHEMAS[name]
    except KeyError:
        raise KeyError(
            f"unknown schema {name!r}; expected one of {', '.join(SCHEMA_NAMES)}"
        ) from None


def iter_tables() -> list[tuple[Schema, Table]]:
    """Every table in every schema, in a foreign-key-safe order."""
    return [(schema, table) for schema in SCHEMAS.values() for table in schema.tables]


def find_table(table_name: str) -> tuple[Schema, Table]:
    """Resolve a prefixed table name back to its schema and definition."""
    for schema, table in iter_tables():
        if table.name == table_name:
            return schema, table
    raise KeyError(f"unknown table {table_name!r}")
