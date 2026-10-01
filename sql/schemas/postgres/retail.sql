-- Schema: retail (online storefront)
-- Dialect: PostgreSQL. This is the hand-written REFERENCE translation of
-- sql/schemas/oracle/retail.sql, following docs/type-mapping.md.
--
-- Type decisions applied here:
--   NUMBER(3), NUMBER(1)  -> smallint
--   NUMBER(6)             -> integer
--   NUMBER(10), NUMBER(12)-> bigint
--   NUMBER(p,s) with s>0  -> numeric(p,s)
--   VARCHAR2(n)           -> varchar(n)
--   CLOB                  -> text
--   DATE                  -> timestamp(0)   because an Oracle DATE carries a time

CREATE TABLE retail_categories (
    category_id         integer                     NOT NULL,
    category_name       varchar(60)                 NOT NULL,
    parent_category_id  integer,
    sort_order          smallint        DEFAULT 0   NOT NULL,
    CONSTRAINT retail_categories_pk PRIMARY KEY (category_id),
    CONSTRAINT retail_categories_uq UNIQUE (category_name),
    CONSTRAINT retail_categories_fk_parent FOREIGN KEY (parent_category_id)
        REFERENCES retail_categories (category_id)
);

CREATE TABLE retail_customers (
    customer_id     bigint                      NOT NULL,
    email           varchar(255)                NOT NULL,
    full_name       varchar(120)                NOT NULL,
    signup_date     timestamp(0)                NOT NULL,
    loyalty_tier    varchar(10)                 NOT NULL,
    credit_limit    numeric(12,2),
    is_active       smallint        DEFAULT 1   NOT NULL,
    CONSTRAINT retail_customers_pk PRIMARY KEY (customer_id),
    CONSTRAINT retail_customers_uq_email UNIQUE (email),
    CONSTRAINT retail_customers_ck_tier CHECK (loyalty_tier IN ('BRONZE', 'SILVER', 'GOLD')),
    CONSTRAINT retail_customers_ck_active CHECK (is_active IN (0, 1))
);

CREATE TABLE retail_products (
    product_id      bigint          NOT NULL,
    sku             varchar(32)     NOT NULL,
    product_name    varchar(150)    NOT NULL,
    category_id     integer         NOT NULL,
    unit_price      numeric(10,2)   NOT NULL,
    description     text,
    launched_on     timestamp(0),
    CONSTRAINT retail_products_pk PRIMARY KEY (product_id),
    CONSTRAINT retail_products_uq_sku UNIQUE (sku),
    CONSTRAINT retail_products_fk_category FOREIGN KEY (category_id)
        REFERENCES retail_categories (category_id),
    CONSTRAINT retail_products_ck_price CHECK (unit_price >= 0)
);

CREATE TABLE retail_orders (
    order_id        bigint          NOT NULL,
    customer_id     bigint          NOT NULL,
    order_date      timestamp(0)    NOT NULL,
    status          varchar(20)     NOT NULL,
    discount_pct    numeric(5,4),
    notes           varchar(400),
    CONSTRAINT retail_orders_pk PRIMARY KEY (order_id),
    CONSTRAINT retail_orders_fk_customer FOREIGN KEY (customer_id)
        REFERENCES retail_customers (customer_id),
    CONSTRAINT retail_orders_ck_status
        CHECK (status IN ('NEW', 'PAID', 'SHIPPED', 'CANCELLED')),
    CONSTRAINT retail_orders_ck_discount CHECK (discount_pct >= 0 AND discount_pct < 1)
);

CREATE TABLE retail_order_items (
    order_id    bigint          NOT NULL,
    line_no     smallint        NOT NULL,
    product_id  bigint          NOT NULL,
    quantity    integer         NOT NULL,
    unit_price  numeric(10,2)   NOT NULL,
    CONSTRAINT retail_order_items_pk PRIMARY KEY (order_id, line_no),
    CONSTRAINT retail_order_items_fk_order FOREIGN KEY (order_id)
        REFERENCES retail_orders (order_id),
    CONSTRAINT retail_order_items_fk_product FOREIGN KEY (product_id)
        REFERENCES retail_products (product_id),
    CONSTRAINT retail_order_items_ck_qty CHECK (quantity > 0)
);

CREATE INDEX retail_orders_ix_cust_date ON retail_orders (customer_id, order_date);

CREATE INDEX retail_products_ix_category ON retail_products (category_id);

-- NOCACHE -> CACHE 1, NOCYCLE -> NO CYCLE.
CREATE SEQUENCE retail_customer_seq START WITH 1000 INCREMENT BY 1 CACHE 1 NO CYCLE;

CREATE SEQUENCE retail_order_seq START WITH 500000 INCREMENT BY 1 CACHE 1 NO CYCLE;

-- NVL -> COALESCE.
CREATE VIEW retail_order_totals AS
SELECT o.order_id,
       o.customer_id,
       o.order_date,
       o.status,
       COALESCE(SUM(i.quantity * i.unit_price), 0) AS gross_amount,
       COUNT(i.line_no)                           AS line_count
FROM retail_orders o
     LEFT JOIN retail_order_items i ON i.order_id = o.order_id
GROUP BY o.order_id, o.customer_id, o.order_date, o.status;
