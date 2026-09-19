-- Star schema of the warehouse (schema `dw`).
--
-- The script is idempotent: every statement uses IF NOT EXISTS, so it can run before
-- every load. It only creates what is missing; it never changes an existing table.
-- (A real project would use migrations, e.g. Alembic, to evolve the schema.)
--
-- Statements are separated by a semicolon at the end of a line. Do not put a semicolon
-- inside a string or a comment.

CREATE SCHEMA IF NOT EXISTS dw;

-- One row per calendar day. The key is the date written as a number (for example 20170930),
-- a "smart key" that is readable and sorts correctly.
CREATE TABLE IF NOT EXISTS dw.dim_date (
    date_key     INTEGER  PRIMARY KEY,
    full_date    DATE     NOT NULL UNIQUE,
    year         SMALLINT NOT NULL,
    quarter      SMALLINT NOT NULL,
    month        SMALLINT NOT NULL,
    month_name   TEXT     NOT NULL,
    day_of_month SMALLINT NOT NULL,
    day_of_week  SMALLINT NOT NULL,  -- ISO: 1 = Monday ... 7 = Sunday
    day_name     TEXT     NOT NULL,
    is_weekend   BOOLEAN  NOT NULL
);

-- One row per customer_id. In the source, customer_id is created per ORDER, and
-- customer_unique_id identifies the real person, so "repeat customers" group by the latter.
-- customer_key is a surrogate key: it never changes, even if the source id format does.
CREATE TABLE IF NOT EXISTS dw.dim_customers (
    customer_key       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id        TEXT NOT NULL UNIQUE,
    customer_unique_id TEXT NOT NULL,
    zip_code_prefix    TEXT,
    city               TEXT,
    state              TEXT
);

CREATE TABLE IF NOT EXISTS dw.dim_products (
    product_key        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id         TEXT NOT NULL UNIQUE,
    category_name      TEXT,
    category_name_en   TEXT NOT NULL,
    name_length        INTEGER,
    description_length INTEGER,
    photos_qty         INTEGER,
    weight_g           INTEGER,
    length_cm          INTEGER,
    height_cm          INTEGER,
    width_cm           INTEGER
);

-- Grain: ONE ROW PER ORDER ITEM (a product line inside an order). order_id and
-- order_item_id together identify a row; order_id is a "degenerate dimension" (an
-- identifier without a table of its own). Timestamps are local Brazilian time with no
-- time zone, exactly as in the source.
CREATE TABLE IF NOT EXISTS dw.fact_orders (
    order_id              TEXT     NOT NULL,
    order_item_id         INTEGER  NOT NULL,
    customer_key          BIGINT   NOT NULL REFERENCES dw.dim_customers (customer_key),
    product_key           BIGINT   NOT NULL REFERENCES dw.dim_products (product_key),
    order_date_key        INTEGER  NOT NULL REFERENCES dw.dim_date (date_key),
    seller_id             TEXT,
    order_status          TEXT     NOT NULL,
    purchased_at          TIMESTAMP NOT NULL,
    delivered_at          TIMESTAMP,
    estimated_delivery_at TIMESTAMP,
    price                 NUMERIC(12, 2) NOT NULL,
    freight_value         NUMERIC(12, 2) NOT NULL,
    PRIMARY KEY (order_id, order_item_id)
);

-- PostgreSQL does not index foreign keys by itself. Analytical queries join on them.
CREATE INDEX IF NOT EXISTS fact_orders_customer_key_idx ON dw.fact_orders (customer_key);
CREATE INDEX IF NOT EXISTS fact_orders_product_key_idx ON dw.fact_orders (product_key);
CREATE INDEX IF NOT EXISTS fact_orders_order_date_key_idx ON dw.fact_orders (order_date_key);
