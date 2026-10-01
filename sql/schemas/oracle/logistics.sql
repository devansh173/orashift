-- Schema: logistics (freight movement)
-- Dialect: Oracle. SOURCE material.
-- This schema is FULLY HELD OUT of training in phase 4. Its vocabulary shares
-- nothing with the other three, so evaluating on it measures whether the model
-- learned dialect translation rather than these specific table and column names.

CREATE TABLE logistics_warehouses (
    warehouse_id        NUMBER(6)       NOT NULL,
    warehouse_code      VARCHAR2(10)    NOT NULL,
    city                VARCHAR2(60)    NOT NULL,
    country_code        CHAR(2)         NOT NULL,
    capacity_pallets    NUMBER(7),
    CONSTRAINT logistics_warehouses_pk PRIMARY KEY (warehouse_id),
    CONSTRAINT logistics_warehouses_uq_code UNIQUE (warehouse_code),
    CONSTRAINT logistics_warehouses_ck_cap CHECK (capacity_pallets > 0)
);

CREATE TABLE logistics_carriers (
    carrier_id      NUMBER(6)                   NOT NULL,
    carrier_name    VARCHAR2(80)                NOT NULL,
    scac_code       VARCHAR2(4),
    is_bonded       NUMBER(1)       DEFAULT 0   NOT NULL,
    CONSTRAINT logistics_carriers_pk PRIMARY KEY (carrier_id),
    CONSTRAINT logistics_carriers_uq_scac UNIQUE (scac_code),
    CONSTRAINT logistics_carriers_ck_bonded CHECK (is_bonded IN (0, 1))
);

CREATE TABLE logistics_shipments (
    shipment_id           NUMBER(12)      NOT NULL,
    tracking_ref          VARCHAR2(24)    NOT NULL,
    origin_warehouse_id   NUMBER(6)       NOT NULL,
    dest_warehouse_id     NUMBER(6)       NOT NULL,
    carrier_id            NUMBER(6),
    dispatched_at         DATE            NOT NULL,
    delivered_at          DATE,
    gross_weight_kg       NUMBER(10,3),
    status                VARCHAR2(16)    NOT NULL,
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
    leg_id              NUMBER(12)      NOT NULL,
    shipment_id         NUMBER(12)      NOT NULL,
    leg_seq             NUMBER(3)       NOT NULL,
    parent_leg_id       NUMBER(12),
    from_warehouse_id   NUMBER(6)       NOT NULL,
    to_warehouse_id     NUMBER(6)       NOT NULL,
    departed_at         DATE            NOT NULL,
    arrived_at          DATE,
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
    event_id        NUMBER(14)      NOT NULL,
    shipment_id     NUMBER(12)      NOT NULL,
    event_at        DATE            NOT NULL,
    event_code      VARCHAR2(20)    NOT NULL,
    location_city   VARCHAR2(60),
    remarks         CLOB,
    CONSTRAINT logistics_tracking_events_pk PRIMARY KEY (event_id),
    CONSTRAINT logistics_tracking_events_fk_shp FOREIGN KEY (shipment_id)
        REFERENCES logistics_shipments (shipment_id)
);

CREATE INDEX logistics_shipments_ix_dispatch ON logistics_shipments (dispatched_at);

CREATE INDEX logistics_tracking_events_ix_shp ON logistics_tracking_events (shipment_id, event_at);

CREATE SEQUENCE logistics_shipment_seq START WITH 7000000 INCREMENT BY 1 NOCACHE NOCYCLE;

CREATE VIEW logistics_shipment_summary AS
SELECT s.shipment_id,
       s.tracking_ref,
       o.warehouse_code                                      AS origin_code,
       d.warehouse_code                                      AS dest_code,
       NVL(c.carrier_name, 'UNASSIGNED')                     AS carrier_name,
       s.status,
       s.dispatched_at,
       s.delivered_at,
       ROUND(NVL2(s.delivered_at, s.delivered_at - s.dispatched_at, NULL), 6) AS transit_days
FROM logistics_shipments s
     JOIN logistics_warehouses o ON o.warehouse_id = s.origin_warehouse_id
     JOIN logistics_warehouses d ON d.warehouse_id = s.dest_warehouse_id
     LEFT JOIN logistics_carriers c ON c.carrier_id = s.carrier_id;
