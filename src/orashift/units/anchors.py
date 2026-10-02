"""Named anchor points into each schema.

A template is written once against abstract names like ``{fact}`` and
``{dim_text}``, and these tables say what those mean in each schema. One
template therefore produces up to four different statements, over four
different vocabularies, which is where most of the pool's variety comes from
without writing four times as many templates.

Anchors that a schema genuinely does not have are left as ``None``; the
renderer skips any template requiring them rather than emitting something that
would not run. ``library`` has no self-referencing table, for example, so it
contributes no ``CONNECT BY`` units.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class Anchors:
    """Where the interesting columns live in one schema."""

    schema: str

    # The "many" side: the table most statements select from.
    fact: str
    fact_pk: str
    fact_date: str
    fact_fk: str
    fact_date2: str | None = None
    """A nullable date, for NVL2 and MONTHS_BETWEEN."""
    fact_status: str | None = None
    fact_status_value: str | None = None
    fact_num: str | None = None
    """A NOT NULL numeric."""
    fact_num_nullable: str | None = None
    fact_text: str | None = None
    fact_text_nullable: str | None = None

    # The "one" side: a lookup table joined to via fact_fk.
    dim: str | None = None
    dim_pk: str | None = None
    dim_text: str | None = None
    dim_status: str | None = None
    dim_status_value: str | None = None
    dim_num_nullable: str | None = None
    dim_text_nullable: str | None = None
    dim_date: str | None = None

    # Whatever can sensibly be summed and grouped.
    sum_table: str | None = None
    sum_num: str | None = None
    sum_fk: str | None = None
    sum_qty: str | None = None

    # A self-referencing parent pointer, for CONNECT BY.
    hier: str | None = None
    hier_pk: str | None = None
    hier_parent: str | None = None
    hier_label: str | None = None

    # For PIVOT, which needs the list of values spelled out.
    pivot_in: str | None = None
    pivot_agg: str | None = None
    """PostgreSQL has no PIVOT, so the same result is produced by conditional
    aggregation. Spelled out here because the column list is schema-specific."""

    seq: str | None = None

    def as_dict(self) -> dict[str, str]:
        """Only the anchors this schema actually has."""
        return {k: v for k, v in asdict(self).items() if v is not None}

    def has(self, *names: str) -> bool:
        available = self.as_dict()
        return all(name in available for name in names)


RETAIL = Anchors(
    schema="retail",
    fact="retail_orders",
    fact_pk="order_id",
    fact_date="order_date",
    fact_fk="customer_id",
    fact_status="status",
    fact_status_value="PAID",
    fact_num_nullable="discount_pct",
    fact_text_nullable="notes",
    dim="retail_customers",
    dim_pk="customer_id",
    dim_text="full_name",
    dim_status="loyalty_tier",
    dim_status_value="GOLD",
    dim_num_nullable="credit_limit",
    dim_date="signup_date",
    sum_table="retail_order_items",
    sum_num="unit_price",
    sum_fk="order_id",
    sum_qty="quantity",
    hier="retail_categories",
    hier_pk="category_id",
    hier_parent="parent_category_id",
    hier_label="category_name",
    pivot_in="'NEW' AS c_new, 'PAID' AS c_paid, 'SHIPPED' AS c_shipped, 'CANCELLED' AS c_cancelled",
    pivot_agg=(
        "COUNT(CASE WHEN status = 'NEW' THEN order_id END) AS c_new, "
        "COUNT(CASE WHEN status = 'PAID' THEN order_id END) AS c_paid, "
        "COUNT(CASE WHEN status = 'SHIPPED' THEN order_id END) AS c_shipped, "
        "COUNT(CASE WHEN status = 'CANCELLED' THEN order_id END) AS c_cancelled"
    ),
    seq="retail_order_seq",
)

HR = Anchors(
    schema="hr",
    fact="hr_employees",
    fact_pk="employee_id",
    fact_date="hire_date",
    fact_fk="department_id",
    fact_status="job_id",
    fact_status_value="IT_PROG",
    fact_num="salary",
    fact_num_nullable="commission_pct",
    fact_text="last_name",
    dim="hr_departments",
    dim_pk="department_id",
    dim_text="department_name",
    dim_text_nullable="location",
    sum_table="hr_employees",
    sum_num="salary",
    sum_fk="department_id",
    hier="hr_employees",
    hier_pk="employee_id",
    hier_parent="manager_id",
    hier_label="last_name",
    pivot_in="'IT_PROG' AS c_prog, 'SA_REP' AS c_rep, 'FI_ACCT' AS c_acct, 'AD_VP' AS c_vp",
    pivot_agg=(
        "COUNT(CASE WHEN job_id = 'IT_PROG' THEN employee_id END) AS c_prog, "
        "COUNT(CASE WHEN job_id = 'SA_REP' THEN employee_id END) AS c_rep, "
        "COUNT(CASE WHEN job_id = 'FI_ACCT' THEN employee_id END) AS c_acct, "
        "COUNT(CASE WHEN job_id = 'AD_VP' THEN employee_id END) AS c_vp"
    ),
    seq="hr_employee_seq",
)

LIBRARY = Anchors(
    schema="library",
    fact="library_loans",
    fact_pk="loan_id",
    fact_date="borrowed_at",
    fact_fk="member_id",
    fact_date2="returned_at",
    fact_num="late_fee",
    dim="library_members",
    dim_pk="member_id",
    dim_text="member_name",
    dim_status="membership_type",
    dim_status_value="ADULT",
    dim_text_nullable="email",
    dim_date="joined_on",
    sum_table="library_loans",
    sum_num="late_fee",
    sum_fk="member_id",
    # library has no self-referencing table, so it contributes no CONNECT BY units.
    seq="library_loan_seq",
)

LOGISTICS = Anchors(
    schema="logistics",
    fact="logistics_shipments",
    fact_pk="shipment_id",
    fact_date="dispatched_at",
    fact_fk="carrier_id",
    fact_date2="delivered_at",
    fact_status="status",
    fact_status_value="DELIVERED",
    fact_num_nullable="gross_weight_kg",
    fact_text="tracking_ref",
    dim="logistics_carriers",
    dim_pk="carrier_id",
    dim_text="carrier_name",
    dim_text_nullable="scac_code",
    sum_table="logistics_shipments",
    sum_num="gross_weight_kg",
    sum_fk="carrier_id",
    hier="logistics_shipment_legs",
    hier_pk="leg_id",
    hier_parent="parent_leg_id",
    hier_label="leg_seq",
    pivot_in=(
        "'BOOKED' AS c_booked, 'IN_TRANSIT' AS c_transit, "
        "'DELIVERED' AS c_delivered, 'EXCEPTION' AS c_exception"
    ),
    pivot_agg=(
        "COUNT(CASE WHEN status = 'BOOKED' THEN shipment_id END) AS c_booked, "
        "COUNT(CASE WHEN status = 'IN_TRANSIT' THEN shipment_id END) AS c_transit, "
        "COUNT(CASE WHEN status = 'DELIVERED' THEN shipment_id END) AS c_delivered, "
        "COUNT(CASE WHEN status = 'EXCEPTION' THEN shipment_id END) AS c_exception"
    ),
    seq="logistics_shipment_seq",
)

ANCHORS: dict[str, Anchors] = {a.schema: a for a in (RETAIL, HR, LIBRARY, LOGISTICS)}
