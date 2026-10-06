"""Deterministic generation of the seed data.

Run once; the resulting CSVs are committed and become the single source of truth
for what gets loaded into *both* engines. Defining the rows once rather than
writing INSERT statements per dialect is what makes "identical data on both
sides" true by construction instead of true by inspection.

Two rules the generated data obeys, both load-bearing:

1. **No empty strings, anywhere.** Oracle cannot store one: ``''`` becomes NULL
   on the way in. If the data contained an empty string the two engines could
   never hold identical values, so the ``'' = NULL`` difference is exercised as
   a *query* construct in the source-unit templates instead of as stored data.
2. **Self-referencing foreign keys always point backwards.** Both engines check
   a foreign key per row as it is inserted, so a parent must already exist.
   Generated parents therefore always have a lower key than their children.
"""

from __future__ import annotations

import csv
import datetime as dt
import random
from decimal import Decimal
from pathlib import Path

from orashift.catalog import SCHEMAS, Schema, ValueKind

SEED = 20260101
"""Fixed so regeneration is byte-identical. Changing it invalidates the dataset."""

DEFAULT_OUT_DIR = Path("data/seed")

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

Row = tuple[object, ...]
Rows = dict[str, list[Row]]

_FIRST_NAMES = (
    "Asha",
    "Bruno",
    "Clara",
    "Dmitri",
    "Elena",
    "Farid",
    "Greta",
    "Hugo",
    "Ines",
    "Jonas",
    "Kiran",
    "Lena",
    "Mateo",
    "Nadia",
    "Omar",
    "Petra",
    "Quentin",
    "Rosa",
    "Samir",
    "Tove",
    "Ursula",
    "Viktor",
    "Wen",
    "Xiomara",
    "Yusuf",
    "Zara",
)
_LAST_NAMES = (
    "Abioye",
    "Baranov",
    "Costa",
    "Dubois",
    "Eriksen",
    "Ferrari",
    "Gupta",
    "Haddad",
    "Ivanov",
    "Jansen",
    "Kowalski",
    "Larsen",
    "Mwangi",
    "Nakamura",
    "Okafor",
    "Pereira",
    "Quiroga",
    "Rossi",
    "Silva",
    "Tanaka",
    "Ueda",
    "Vasquez",
    "Weber",
    "Xu",
    "Yilmaz",
    "Zielinski",
)
_CITIES = (
    "Rotterdam",
    "Hamburg",
    "Valencia",
    "Gdansk",
    "Trieste",
    "Antwerp",
    "Gothenburg",
    "Bilbao",
    "Piraeus",
    "Constanta",
    "Riga",
    "Bremerhaven",
)
_COUNTRIES = ("NL", "DE", "ES", "PL", "IT", "BE", "SE", "GR", "RO", "LV")


def _dt_between(rng: random.Random, start: dt.date, end: dt.date) -> dt.datetime:
    """A timestamp with a non-midnight time, so the Oracle DATE time part matters."""
    days = (end - start).days
    base = start + dt.timedelta(days=rng.randrange(days + 1))
    return dt.datetime(
        base.year,
        base.month,
        base.day,
        rng.randrange(6, 23),
        rng.randrange(60),
        rng.randrange(60),
    )


def _money(rng: random.Random, low: int, high: int, places: str = "0.01") -> Decimal:
    """A Decimal in [low, high] with the given number of decimal places."""
    scale = Decimal(places)
    cents = rng.randrange(int(low / float(scale)), int(high / float(scale)) + 1)
    return (Decimal(cents) * scale).quantize(scale)


def _fraction(rng: random.Random, low_units: int, high_units: int, places: int) -> Decimal:
    """A Decimal fraction with exactly `places` decimals, e.g. 0.0137 for places=4.

    Kept separate from _money because dividing a Decimal after the fact produces
    more decimal places than the target column declares.
    """
    quantum = Decimal(1).scaleb(-places)
    return (Decimal(rng.randrange(low_units, high_units + 1)) * quantum).quantize(quantum)


def _maybe(rng: random.Random, probability_null: float, value: object) -> object:
    """Return None with the given probability, otherwise the value."""
    return None if rng.random() < probability_null else value


# --------------------------------------------------------------------------- #
# retail
# --------------------------------------------------------------------------- #

_CATEGORIES: tuple[tuple[int, str, int | None, int], ...] = (
    (1, "Electronics", None, 1),
    (2, "Home & Garden", None, 2),
    (3, "Books", None, 3),
    (4, "Laptops", 1, 1),
    (5, "Phones", 1, 2),
    (6, "Audio", 1, 3),
    (7, "Kitchen", 2, 1),
    (8, "Furniture", 2, 2),
    (9, "Fiction", 3, 1),
    (10, "Non-fiction", 3, 2),
    (11, "Headphones", 6, 1),
    (12, "Laptop Bags", 4, 2),
)
_LEAF_CATEGORIES = (4, 5, 7, 8, 9, 10, 11, 12)

_PRODUCT_WORDS = (
    "Nimbus",
    "Harbour",
    "Kestrel",
    "Vellum",
    "Orchard",
    "Lumen",
    "Basalt",
    "Clove",
    "Drift",
    "Ember",
    "Fathom",
    "Glint",
    "Hollow",
    "Ironwood",
)
_PRODUCT_NOUNS = ("Laptop", "Handset", "Speaker", "Kettle", "Armchair", "Novel", "Guide", "Headset")

_DESCRIPTIONS = (
    "Lightweight, durable, and quiet in use.",
    "Ships in recyclable packaging, no plastic inserts.",
    'Customer favourite: "it just works", as one reviewer put it.',
    "O'Brien & Sons have manufactured this line since 1987.",
    "Specifications:\nweight 1.2 kg\nwarranty 24 months",
    "Compatible with most third-party accessories, including older models.",
)
_ORDER_NOTES = (
    "Leave with the neighbour if nobody answers.",
    "Gift wrap requested, no invoice in the box.",
    "Customer called to confirm the delivery window.",
    "Second attempt; first delivery failed.",
)


def _rows_retail(rng: random.Random) -> Rows:
    rows: Rows = {}

    rows["retail_categories"] = [
        (cid, name, parent, order) for cid, name, parent, order in _CATEGORIES
    ]

    customers: list[Row] = []
    for i in range(60):
        cid = 1000 + i
        first = _FIRST_NAMES[rng.randrange(len(_FIRST_NAMES))]
        last = _LAST_NAMES[rng.randrange(len(_LAST_NAMES))]
        customers.append(
            (
                cid,
                f"{first.lower()}.{last.lower()}{i}@example.com",
                f"{first} {last}",
                _dt_between(rng, dt.date(2022, 1, 1), dt.date(2025, 12, 31)),
                ("BRONZE", "SILVER", "GOLD")[rng.randrange(3)],
                _maybe(rng, 0.25, _money(rng, 500, 10000)),
                0 if rng.random() < 0.15 else 1,
            )
        )
    rows["retail_customers"] = customers

    products: list[Row] = []
    for i in range(1, 81):
        word = _PRODUCT_WORDS[rng.randrange(len(_PRODUCT_WORDS))]
        noun = _PRODUCT_NOUNS[rng.randrange(len(_PRODUCT_NOUNS))]
        products.append(
            (
                i,
                f"SKU-{i:05d}",
                f"{word} {noun}",
                _LEAF_CATEGORIES[rng.randrange(len(_LEAF_CATEGORIES))],
                _money(rng, 1, 2500),
                _maybe(rng, 0.20, _DESCRIPTIONS[rng.randrange(len(_DESCRIPTIONS))]),
                _maybe(rng, 0.15, _dt_between(rng, dt.date(2021, 1, 1), dt.date(2025, 6, 30))),
            )
        )
    rows["retail_products"] = products

    product_prices = {p[0]: p[4] for p in products}
    customer_ids = [c[0] for c in customers]

    orders: list[Row] = []
    items: list[Row] = []
    for i in range(150):
        order_id = 500000 + i
        orders.append(
            (
                order_id,
                customer_ids[rng.randrange(len(customer_ids))],
                _dt_between(rng, dt.date(2024, 1, 1), dt.date(2026, 6, 30)),
                ("NEW", "PAID", "SHIPPED", "CANCELLED")[rng.randrange(4)],
                _maybe(rng, 0.60, _fraction(rng, 0, 2500, 4)),
                _maybe(rng, 0.50, _ORDER_NOTES[rng.randrange(len(_ORDER_NOTES))]),
            )
        )
        for line_no in range(1, rng.randrange(1, 6) + 1):
            product_id = rng.randrange(1, 81)
            items.append(
                (
                    order_id,
                    line_no,
                    product_id,
                    rng.randrange(1, 13),
                    product_prices[product_id],
                )
            )
    rows["retail_orders"] = orders
    rows["retail_order_items"] = items
    return rows


# --------------------------------------------------------------------------- #
# hr
# --------------------------------------------------------------------------- #

_DEPARTMENTS = (
    (10, "Executive", "Rotterdam"),
    (20, "Engineering", "Hamburg"),
    (30, "Finance", "Valencia"),
    (40, "Operations", None),
    (50, "Sales", "Gdansk"),
    (60, "Support", "Trieste"),
    (70, "Legal", None),
    (80, "People", "Antwerp"),
)

_JOBS = (
    ("AD_PRES", "President", 20000, 40000),
    ("AD_VP", "Vice President", 15000, 30000),
    ("IT_PROG", "Programmer", 4000, 10000),
    ("IT_LEAD", "Engineering Lead", 8000, 16000),
    ("FI_ACCT", "Accountant", 4200, 9000),
    ("FI_MGR", "Finance Manager", 8200, 16000),
    ("SA_REP", "Sales Representative", 6000, 12000),
    ("SA_MAN", "Sales Manager", 10000, 20000),
    ("OP_CLERK", "Operations Clerk", 2500, 5500),
    ("SU_AGENT", "Support Agent", 2800, 6000),
    ("LG_COUNSEL", "Legal Counsel", 9000, 18000),
    ("HR_PART", "People Partner", 5000, 11000),
)
_COMMISSION_JOBS = ("SA_REP", "SA_MAN")


def _rows_hr(rng: random.Random) -> Rows:
    rows: Rows = {}
    rows["hr_departments"] = list(_DEPARTMENTS)
    rows["hr_jobs"] = [
        (jid, title, Decimal(lo).quantize(Decimal("0.01")), Decimal(hi).quantize(Decimal("0.01")))
        for jid, title, lo, hi in _JOBS
    ]
    rows["hr_pay_grades"] = [
        ("G1", Decimal("2000.00"), Decimal("4999.99")),
        ("G2", Decimal("5000.00"), Decimal("7999.99")),
        ("G3", Decimal("8000.00"), Decimal("11999.99")),
        ("G4", Decimal("12000.00"), Decimal("17999.99")),
        ("G5", Decimal("18000.00"), Decimal("27999.99")),
        ("G6", Decimal("28000.00"), Decimal("49999.99")),
    ]

    job_by_id = {jid: (lo, hi) for jid, _t, lo, hi in _JOBS}
    employees: list[Row] = []
    emails: set[str] = set()

    for i in range(70):
        employee_id = 200 + i
        if i == 0:
            job_id, manager_id, department_id = "AD_PRES", None, 10
        elif i <= 5:
            job_id, manager_id, department_id = "AD_VP", 200, _DEPARTMENTS[i][0]
        else:
            job_id = _JOBS[rng.randrange(2, len(_JOBS))][0]
            # Always a lower id, so the self-referencing FK resolves on insert.
            manager_id = 200 + rng.randrange(1, min(i, 6) + 1)
            department_id = _maybe(rng, 0.10, _DEPARTMENTS[rng.randrange(len(_DEPARTMENTS))][0])

        first = _FIRST_NAMES[rng.randrange(len(_FIRST_NAMES))]
        last = _LAST_NAMES[rng.randrange(len(_LAST_NAMES))]
        email = f"{first[0].lower()}{last.lower()}{employee_id}@example.com"
        assert email not in emails
        emails.add(email)

        lo, hi = job_by_id[job_id]
        commission = _fraction(rng, 5, 400, 3) if job_id in _COMMISSION_JOBS else None
        employees.append(
            (
                employee_id,
                first,
                last,
                email,
                _dt_between(rng, dt.date(2015, 1, 1), dt.date(2026, 3, 31)),
                job_id,
                _money(rng, lo, hi),
                commission,
                manager_id,
                department_id,
            )
        )
    rows["hr_employees"] = employees

    history: list[Row] = []
    seen: set[tuple[int, dt.datetime]] = set()
    while len(history) < 40:
        employee = employees[rng.randrange(len(employees))]
        start = _dt_between(rng, dt.date(2012, 1, 1), dt.date(2023, 12, 31))
        key = (employee[0], start)
        if key in seen:
            continue
        seen.add(key)
        end = _maybe(rng, 0.25, start + dt.timedelta(days=rng.randrange(90, 1500)))
        history.append(
            (
                employee[0],
                start,
                end,
                _JOBS[rng.randrange(len(_JOBS))][0],
                _maybe(rng, 0.15, _DEPARTMENTS[rng.randrange(len(_DEPARTMENTS))][0]),
            )
        )
    history.sort(key=lambda r: (r[0], r[1]))
    rows["hr_job_history"] = history
    return rows


# --------------------------------------------------------------------------- #
# library
# --------------------------------------------------------------------------- #

_TITLE_A = ("The", "A", "Her", "Our", "No")
_TITLE_B = ("Quiet", "Distant", "Broken", "Golden", "Hidden", "Final", "Patient")
_TITLE_C = ("Harbour", "Archive", "Orchard", "Lighthouse", "Cartographer", "Winter", "Signal")
_SUMMARIES = (
    "A slow, careful study of memory and place.",
    "Essays on infrastructure, collected from a decade of reporting.",
    "Includes an index, a glossary, and forty pages of notes.",
    "The author's first novel, written while working nights.",
    "Chapter one opens mid-sentence;\nthe effect is deliberate.",
)


def _rows_library(rng: random.Random) -> Rows:
    rows: Rows = {}

    authors: list[Row] = []
    for i in range(1, 31):
        first = _FIRST_NAMES[rng.randrange(len(_FIRST_NAMES))]
        last = _LAST_NAMES[rng.randrange(len(_LAST_NAMES))]
        authors.append(
            (
                i,
                f"{first} {last}",
                _maybe(rng, 0.20, rng.randrange(1890, 2001)),
                _maybe(rng, 0.15, _COUNTRIES[rng.randrange(len(_COUNTRIES))]),
            )
        )
    rows["library_authors"] = authors

    books: list[Row] = []
    for i in range(1, 61):
        title = (
            f"{_TITLE_A[rng.randrange(len(_TITLE_A))]} "
            f"{_TITLE_B[rng.randrange(len(_TITLE_B))]} "
            f"{_TITLE_C[rng.randrange(len(_TITLE_C))]}"
        )
        books.append(
            (
                i,
                f"978{i:010d}",
                title,
                rng.randrange(1, 31),
                _maybe(rng, 0.15, _dt_between(rng, dt.date(1995, 1, 1), dt.date(2025, 12, 31))),
                _maybe(rng, 0.10, rng.randrange(80, 900)),
                _maybe(rng, 0.25, _SUMMARIES[rng.randrange(len(_SUMMARIES))]),
            )
        )
    rows["library_books"] = books

    copies: list[Row] = []
    for i in range(1, 121):
        copies.append(
            (
                i,
                rng.randrange(1, 61),
                _dt_between(rng, dt.date(2016, 1, 1), dt.date(2026, 1, 31)),
                f"{chr(65 + rng.randrange(8))}{rng.randrange(1, 40):02d}-{rng.randrange(1, 10)}",
                _maybe(rng, 0.15, rng.randrange(1, 6)),
            )
        )
    rows["library_copies"] = copies

    members: list[Row] = []
    for i in range(1, 51):
        first = _FIRST_NAMES[rng.randrange(len(_FIRST_NAMES))]
        last = _LAST_NAMES[rng.randrange(len(_LAST_NAMES))]
        members.append(
            (
                i,
                f"{first} {last}",
                _dt_between(rng, dt.date(2018, 1, 1), dt.date(2026, 2, 28)),
                # Nullable AND unique: several NULLs coexist in a unique index on
                # both engines, which is worth having in the data on purpose.
                _maybe(rng, 0.20, f"member{i}@example.org"),
                ("ADULT", "CHILD", "STUDENT", "STAFF")[rng.randrange(4)],
            )
        )
    rows["library_members"] = members

    loans: list[Row] = []
    for i in range(200):
        borrowed = _dt_between(rng, dt.date(2024, 1, 1), dt.date(2026, 6, 30))
        due = borrowed + dt.timedelta(days=rng.randrange(7, 43))
        returned = _maybe(rng, 0.35, borrowed + dt.timedelta(days=rng.randrange(1, 70)))
        late_fee = (
            _money(rng, 0, 25) if returned is not None and returned > due else Decimal("0.00")
        )
        loans.append(
            (
                90000 + i,
                rng.randrange(1, 121),
                rng.randrange(1, 51),
                borrowed,
                due,
                returned,
                late_fee.quantize(Decimal("0.01")),
            )
        )
    rows["library_loans"] = loans
    return rows


# --------------------------------------------------------------------------- #
# logistics (held out)
# --------------------------------------------------------------------------- #

_CARRIERS = (
    (1, "Noordzee Freight", "NZFR", 1),
    (2, "Baltica Lines", "BLTC", 0),
    (3, "Alpen Kombi", "ALPK", 1),
    (4, "Iberia Rail Cargo", "IBRC", 0),
    (5, "Adriatic Roro", "ADRR", 0),
    (6, "Vistula Haulage", None, 0),
    (7, "Nordic Express", "NDEX", 1),
    (8, "Aegean Bulk", None, 0),
)
_EVENT_CODES = (
    "BOOKING_CREATED",
    "PICKED_UP",
    "DEPARTED",
    "ARRIVED",
    "CUSTOMS_HOLD",
    "CUSTOMS_CLEARED",
    "OUT_FOR_DELIVERY",
    "DELIVERED",
    "DELAY_REPORTED",
)
_REMARKS = (
    "Seal intact on arrival.",
    "Held for documentation: missing packing list.",
    "Driver reported congestion, 90 minutes lost.",
    "Reefer unit logged -18 C throughout.",
    "Partial offload; two pallets remain on board.",
)


def _rows_logistics(rng: random.Random) -> Rows:
    rows: Rows = {}

    warehouses: list[Row] = []
    for i in range(1, 11):
        city = _CITIES[i - 1]
        warehouses.append(
            (
                i,
                f"WH-{city[:3].upper()}{i:02d}",
                city,
                _COUNTRIES[rng.randrange(len(_COUNTRIES))],
                _maybe(rng, 0.20, rng.randrange(500, 40000)),
            )
        )
    rows["logistics_warehouses"] = warehouses
    rows["logistics_carriers"] = list(_CARRIERS)

    shipments: list[Row] = []
    for i in range(120):
        shipment_id = 7000000 + i
        origin = rng.randrange(1, 11)
        dest = rng.randrange(1, 11)
        while dest == origin:
            dest = rng.randrange(1, 11)
        dispatched = _dt_between(rng, dt.date(2025, 1, 1), dt.date(2026, 7, 31))
        status = ("BOOKED", "IN_TRANSIT", "DELIVERED", "EXCEPTION")[rng.randrange(4)]
        delivered = (
            dispatched + dt.timedelta(days=rng.randrange(1, 21), hours=rng.randrange(24))
            if status == "DELIVERED"
            else None
        )
        shipments.append(
            (
                shipment_id,
                f"TRK{shipment_id}{chr(65 + rng.randrange(26))}",
                origin,
                dest,
                _maybe(rng, 0.15, rng.randrange(1, 9)),
                dispatched,
                delivered,
                _maybe(rng, 0.10, _money(rng, 50, 28000, "0.001")),
                status,
            )
        )
    rows["logistics_shipments"] = shipments

    legs: list[Row] = []
    leg_id = 1
    for shipment in shipments:
        shipment_id, _ref, origin, dest = shipment[0], shipment[1], shipment[2], shipment[3]
        hops = rng.randrange(1, 4)
        previous_leg_id: int | None = None
        current_from = origin
        departed = shipment[5]
        for seq in range(1, hops + 1):
            to_warehouse = dest if seq == hops else rng.randrange(1, 11)
            while to_warehouse == current_from:
                to_warehouse = rng.randrange(1, 11)
            arrived = _maybe(rng, 0.15, departed + dt.timedelta(hours=rng.randrange(4, 60)))
            legs.append(
                (
                    leg_id,
                    shipment_id,
                    seq,
                    previous_leg_id,
                    current_from,
                    to_warehouse,
                    departed,
                    arrived,
                )
            )
            previous_leg_id = leg_id
            leg_id += 1
            current_from = to_warehouse
            departed = (arrived or departed) + dt.timedelta(hours=rng.randrange(1, 12))
    rows["logistics_shipment_legs"] = legs

    events: list[Row] = []
    event_id = 1
    for shipment in shipments:
        for _ in range(rng.randrange(1, 6)):
            events.append(
                (
                    event_id,
                    shipment[0],
                    shipment[5] + dt.timedelta(hours=rng.randrange(0, 400)),
                    _EVENT_CODES[rng.randrange(len(_EVENT_CODES))],
                    _maybe(rng, 0.20, _CITIES[rng.randrange(len(_CITIES))]),
                    _maybe(rng, 0.40, _REMARKS[rng.randrange(len(_REMARKS))]),
                )
            )
            event_id += 1
    rows["logistics_tracking_events"] = events
    return rows


_BUILDERS = {
    "retail": _rows_retail,
    "hr": _rows_hr,
    "library": _rows_library,
    "logistics": _rows_logistics,
}


def _to_field(value: object, kind: ValueKind) -> str:
    """Render one Python value as a CSV field. None becomes an empty field."""
    if value is None:
        return ""
    if kind is ValueKind.TIMESTAMP:
        assert isinstance(value, dt.datetime)
        return value.strftime(TIMESTAMP_FORMAT)
    text = str(value)
    if kind is ValueKind.TEXT and text == "":
        raise ValueError("empty strings are not allowed in seed data: Oracle stores them as NULL")
    return text


def csv_path(out_dir: Path, schema: str, table: str) -> Path:
    return out_dir / schema / f"{table}.csv"


def generate_schema(schema: Schema, out_dir: Path, rng: random.Random) -> dict[str, int]:
    """Generate and write one schema's CSVs. Returns rows written per table."""
    rows = _BUILDERS[schema.name](rng)
    written: dict[str, int] = {}

    for table in schema.tables:
        table_rows = rows[table.name]
        path = csv_path(out_dir, schema.name, table.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(table.column_names)
            for row in table_rows:
                if len(row) != len(table.columns):
                    raise ValueError(
                        f"{table.name}: generated {len(row)} values for "
                        f"{len(table.columns)} columns"
                    )
                writer.writerow(
                    _to_field(value, column.kind)
                    for value, column in zip(row, table.columns, strict=True)
                )
        written[table.name] = len(table_rows)
    return written


def generate_all(out_dir: Path = DEFAULT_OUT_DIR) -> dict[str, dict[str, int]]:
    """Regenerate every schema's CSVs from the fixed seed."""
    rng = random.Random(SEED)
    return {name: generate_schema(schema, out_dir, rng) for name, schema in SCHEMAS.items()}
