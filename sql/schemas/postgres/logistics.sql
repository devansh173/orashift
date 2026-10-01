-- Schema: logistics (freight movement)
-- Dialect: PostgreSQL. Hand-written REFERENCE translation of
-- sql/schemas/oracle/logistics.sql.
--
-- This schema is FULLY HELD OUT of training in phase 4.

CREATE TABLE logistics_warehouses (
    warehouse_id        integer         NOT NULL,
    warehouse_code      varchar(10)     NOT NULL,
    city                varchar(60)     NOT NULL,
    country_code        char(2)         NOT NULL,
    capacity_pallets    integer,
    CONSTRAINT logistics_warehouses_pk PRIMARY KEY (warehouse_id),
    CONSTRAINT logistics_warehouses_uq_code UNIQUE (warehouse_code),
    CONSTRAINT logistics_warehouses_ck_cap CHECK (capacity_pallets > 0)
);

CREATE TABLE logistics_carriers (
    carrier_id      integer                     NOT NULL,
    carrier_name    varchar(80)                 NOT NULL,
    scac_code       varchar(4),
    is_bonded       smallint        DEFAULT 0   NOT NULL,
    CONSTRAINT logistics_carriers_pk PRIMARY KEY (carrier_id),
    CONSTRAINT logistics_carriers_uq_scac UNIQUE (scac_code),
    CONSTRAINT logistics_carriers_ck_bonded CHECK (is_bonded IN (0, 1))
);

CREATE TABLE logistics_shipments (
    shipment_id           bigint          NOT NULL,
    tracking_ref          varchar(24)     NOT NULL,
    origin_warehouse_id   integer         NOT NULL,
    dest_warehouse_id     integer         NOT NULL,
    carrier_id            integer,
    dispatched_at         timestamp(0)    NOT NULL,
    delivered_at          timestamp(0),
    gross_weight_kg       numeric(10,3),
    status                varchar(16)     NOT NULL,
    CONSTRAINT logistics_shipments_pk PRIMARY KEY (shipment_id),
    CONSTRAINT logistics_shipments_uq_ref UNIQUE (tracking_ref),
    CONSTRAINT logistics_shipments_fk_origin FOREIGN KEY (origin_warehouse_id)
        REFERENCES logistics_warehouses (warehouse_id),
    CONSTRAINT logistics_shipments_fk_dest FOREIGN KEY (dest_warehouse_id)
        REFERENCES logistics_warehouses (warehouse_id),
    CONSTRAINT logistics_shipments_fk_carrier FOREIGN KEY (carrier_id)
        REFERENCES logistics_carriers (carrier_id),
    CONSTRAINT logistics_shipments_ck_status
        CHECK (status IN ('BOOKED', 'IN_TRANSIT', 'DELIVERED', 'EXCEPTION')),
    CONSTRAINT logistics_shipments_ck_route CHECK (origin_warehouse_id <> dest_warehouse_id),
    CONSTRAINT logistics_shipments_ck_weight CHECK (gross_weight_kg > 0)
);

CREATE TABLE logistics_shipment_legs (
    leg_id              bigint          NOT NULL,
    shipment_id         bigint          NOT NULL,
    leg_seq             smallint        NOT NULL,
    parent_leg_id       bigint,
    from_warehouse_id   integer         NOT NULL,
    to_warehouse_id     integer         NOT NULL,
    departed_at         timestamp(0)    NOT NULL,
    arrived_at          timestamp(0),
    CONSTRAINT logistics_shipment_legs_pk PRIMARY KEY (leg_id),
    CONSTRAINT logistics_shipment_legs_uq_seq UNIQUE (shipment_id, leg_seq),
    CONSTRAINT logistics_shipment_legs_fk_shp FOREIGN KEY (shipment_id)
        REFERENCES logistics_shipments (shipment_id),
    CONSTRAINT logistics_shipment_legs_fk_parent FOREIGN KEY (parent_leg_id)
        REFERENCES logistics_shipment_legs (leg_id),
    CONSTRAINT logistics_shipment_legs_fk_from FOREIGN KEY (from_warehouse_id)
        REFERENCES logistics_warehouses (warehouse_id),
    CONSTRAINT logistics_shipment_legs_fk_to FOREIGN KEY (to_warehouse_id)
        REFERENCES logistics_warehouses (warehouse_id),
    CONSTRAINT logistics_shipment_legs_ck_arr
        CHECK (arrived_at IS NULL OR arrived_at >= departed_at)
);

CREATE TABLE logistics_tracking_events (
    event_id        bigint          NOT NULL,
    shipment_id     bigint          NOT NULL,
    event_at        timestamp(0)    NOT NULL,
    event_code      varchar(20)     NOT NULL,
    location_city   varchar(60),
    remarks         text,
    CONSTRAINT logistics_tracking_events_pk PRIMARY KEY (event_id),
    CONSTRAINT logistics_tracking_events_fk_shp FOREIGN KEY (shipment_id)
        REFERENCES logistics_shipments (shipment_id)
);

CREATE INDEX logistics_shipments_ix_dispatch ON logistics_shipments (dispatched_at);

CREATE INDEX logistics_tracking_events_ix_shp ON logistics_tracking_events (shipment_id, event_at);

CREATE SEQUENCE logistics_shipment_seq START WITH 7000000 INCREMENT BY 1 CACHE 1 NO CYCLE;

-- Two non-obvious translations here:
--   NVL2(a, b, c)        -> CASE WHEN a IS NOT NULL THEN b ELSE c END
--   DATE minus DATE      -> Oracle returns a NUMBER of days; in PostgreSQL
--                           timestamp minus timestamp returns an interval, so
--                           the epoch is extracted and divided to get days back
--                           as a numeric.
--
-- Both sides ROUND to 6 decimal places. Without it the values are numerically
-- equal but carried to different precision: a non-terminating division keeps
-- 38 significant digits in Oracle's NUMBER and about 16 in PostgreSQL's
-- numeric, so an exact comparison fails on a translation that is in fact
-- correct. See docs/dialect-notes.md.
CREATE VIEW logistics_shipment_summary AS
SELECT s.shipment_id,
       s.tracking_ref,
       o.warehouse_code                      AS origin_code,
       d.warehouse_code                      AS dest_code,
       COALESCE(c.carrier_name, 'UNASSIGNED') AS carrier_name,
       s.status,
       s.dispatched_at,
       s.delivered_at,
       ROUND(
           CASE WHEN s.delivered_at IS NOT NULL
                THEN EXTRACT(EPOCH FROM (s.delivered_at - s.dispatched_at)) / 86400
                ELSE NULL
           END, 6)                           AS transit_days
FROM logistics_shipments s
     JOIN logistics_warehouses o ON o.warehouse_id = s.origin_warehouse_id
     JOIN logistics_warehouses d ON d.warehouse_id = s.dest_warehouse_id
     LEFT JOIN logistics_carriers c ON c.carrier_id = s.carrier_id;
