-- Schema: retail (online storefront)
-- Dialect: Oracle. This is SOURCE material: deliberately idiomatic Oracle.
-- The reference PostgreSQL translation lives in sql/schemas/postgres/retail.sql
-- and follows the policy in docs/type-mapping.md.

CREATE TABLE retail_categories (
    category_id         NUMBER(6)                   NOT NULL,
    category_name       VARCHAR2(60)                NOT NULL,
    parent_category_id  NUMBER(6),
    sort_order          NUMBER(3)       DEFAULT 0   NOT NULL,
    CONSTRAINT retail_categories_pk PRIMARY KEY (category_id),
    CONSTRAINT retail_categories_uq UNIQUE (category_name),
    CONSTRAINT retail_categories_fk_parent FOREIGN KEY (parent_category_id)
        REFERENCES retail_categories (category_id)
);

CREATE TABLE retail_customers (
    customer_id     NUMBER(10)                  NOT NULL,
    email           VARCHAR2(255)               NOT NULL,
    full_name       VARCHAR2(120)               NOT NULL,
    signup_date     DATE                        NOT NULL,
    loyalty_tier    VARCHAR2(10)                NOT NULL,
    credit_limit    NUMBER(12,2),
    is_active       NUMBER(1)       DEFAULT 1   NOT NULL,
    CONSTRAINT retail_customers_pk PRIMARY KEY (customer_id),
    CONSTRAINT retail_customers_uq_email UNIQUE (email),
    CONSTRAINT retail_customers_ck_tier CHECK (loyalty_tier IN ('BRONZE', 'SILVER', 'GOLD')),
    CONSTRAINT retail_customers_ck_active CHECK (is_active IN (0, 1))
);

CREATE TABLE retail_products (
    product_id      NUMBER(10)      NOT NULL,
    sku             VARCHAR2(32)    NOT NULL,
    product_name    VARCHAR2(150)   NOT NULL,
    category_id     NUMBER(6)       NOT NULL,
    unit_price      NUMBER(10,2)    NOT NULL,
    description     CLOB,
    launched_on     DATE,
    CONSTRAINT retail_products_pk PRIMARY KEY (product_id),
    CONSTRAINT retail_products_uq_sku UNIQUE (sku),
    CONSTRAINT retail_products_fk_category FOREIGN KEY (category_id)
        REFERENCES retail_categories (category_id),
    CONSTRAINT retail_products_ck_price CHECK (unit_price >= 0)
);

CREATE TABLE retail_orders (
    order_id        NUMBER(12)      NOT NULL,
    customer_id     NUMBER(10)      NOT NULL,
    order_date      DATE            NOT NULL,
    status          VARCHAR2(20)    NOT NULL,
    discount_pct    NUMBER(5,4),
    notes           VARCHAR2(400),
    CONSTRAINT retail_orders_pk PRIMARY KEY (order_id),
    CONSTRAINT retail_orders_fk_customer FOREIGN KEY (customer_id)
        REFERENCES retail_customers (customer_id),
    CONSTRAINT retail_orders_ck_status
        CHECK (status IN ('NEW', 'PAID', 'SHIPPED', 'CANCELLED')),
    CONSTRAINT retail_orders_ck_discount CHECK (discount_pct >= 0 AND discount_pct < 1)
);

CREATE TABLE retail_order_items (
    order_id    NUMBER(12)      NOT NULL,
    line_no     NUMBER(4)       NOT NULL,
    product_id  NUMBER(10)      NOT NULL,
    quantity    NUMBER(6)       NOT NULL,
    unit_price  NUMBER(10,2)    NOT NULL,
    CONSTRAINT retail_order_items_pk PRIMARY KEY (order_id, line_no),
    CONSTRAINT retail_order_items_fk_order FOREIGN KEY (order_id)
        REFERENCES retail_orders (order_id),
    CONSTRAINT retail_order_items_fk_product FOREIGN KEY (product_id)
        REFERENCES retail_products (product_id),
    CONSTRAINT retail_order_items_ck_qty CHECK (quantity > 0)
);

CREATE INDEX retail_orders_ix_cust_date ON retail_orders (customer_id, order_date);

CREATE INDEX retail_products_ix_category ON retail_products (category_id);

CREATE SEQUENCE retail_customer_seq START WITH 1000 INCREMENT BY 1 NOCACHE NOCYCLE;

CREATE SEQUENCE retail_order_seq START WITH 500000 INCREMENT BY 1 NOCACHE NOCYCLE;

CREATE VIEW retail_order_totals AS
SELECT o.order_id,
       o.customer_id,
       o.order_date,
       o.status,
       NVL(SUM(i.quantity * i.unit_price), 0) AS gross_amount,
       COUNT(i.line_no)                       AS line_count
FROM retail_orders o
     LEFT JOIN retail_order_items i ON i.order_id = o.order_id
GROUP BY o.order_id, o.customer_id, o.order_date, o.status;
