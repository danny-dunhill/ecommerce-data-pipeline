-- Analytical views (schema `analytics`): the layer that analysts and BI tools query.
--
-- Views hold no data, they are saved queries, so they are simply dropped and created
-- again on every load. That keeps them in step with the tables, also when a column changes.
-- Statements are separated by a semicolon at the end of a line (see star_schema.sql).

CREATE SCHEMA IF NOT EXISTS analytics;

DROP VIEW IF EXISTS analytics.repeat_customers;
DROP VIEW IF EXISTS analytics.customer_orders;
DROP VIEW IF EXISTS analytics.top_products;
DROP VIEW IF EXISTS analytics.monthly_revenue;
DROP VIEW IF EXISTS analytics.sales_items;

-- The single definition of "a sale": order items of orders that were not canceled and are
-- not "unavailable". Every view below starts from here, so they always agree on revenue.
CREATE VIEW analytics.sales_items AS
SELECT
    order_id,
    order_item_id,
    customer_key,
    product_key,
    order_date_key,
    purchased_at,
    price,
    freight_value
FROM dw.fact_orders
WHERE order_status NOT IN ('canceled', 'unavailable');

-- Revenue per calendar month. "revenue" is the item price without freight.
-- revenue_growth_pct compares with the previous month that has sales.
CREATE VIEW analytics.monthly_revenue AS
WITH monthly AS (
    SELECT
        d.year,
        d.month,
        make_date(d.year, d.month, 1) AS month_start,
        count(DISTINCT s.order_id) AS orders,
        count(*) AS items,
        sum(s.price) AS revenue,
        sum(s.freight_value) AS freight
    FROM analytics.sales_items AS s
    JOIN dw.dim_date AS d ON d.date_key = s.order_date_key
    GROUP BY d.year, d.month
)
SELECT
    year,
    month,
    month_start,
    orders,
    items,
    revenue,
    freight,
    round(revenue / orders, 2) AS avg_order_value,
    round(
        100.0 * (revenue - lag(revenue) OVER (ORDER BY month_start))
        / nullif(lag(revenue) OVER (ORDER BY month_start), 0),
        1
    ) AS revenue_growth_pct
FROM monthly;

-- Every product that was sold, ranked by revenue (1 = best seller). Ties share a rank.
CREATE VIEW analytics.top_products AS
SELECT
    p.product_id,
    p.category_name_en AS category,
    count(*) AS units_sold,
    count(DISTINCT s.order_id) AS orders,
    sum(s.price) AS revenue,
    rank() OVER (ORDER BY sum(s.price) DESC) AS revenue_rank
FROM analytics.sales_items AS s
JOIN dw.dim_products AS p USING (product_key)
GROUP BY p.product_key, p.product_id, p.category_name_en;

-- One row per real person. customer_id is created per order in the source, so the person
-- is identified by customer_unique_id.
CREATE VIEW analytics.customer_orders AS
SELECT
    c.customer_unique_id,
    count(DISTINCT s.order_id) AS orders,
    sum(s.price) AS revenue,
    CAST(min(s.purchased_at) AS date) AS first_order_date,
    CAST(max(s.purchased_at) AS date) AS last_order_date,
    count(DISTINCT s.order_id) > 1 AS is_repeat
FROM analytics.sales_items AS s
JOIN dw.dim_customers AS c USING (customer_key)
GROUP BY c.customer_unique_id;

-- How many customers came back for a second order, and how much revenue they bring.
CREATE VIEW analytics.repeat_customers AS
SELECT
    count(*) AS customers,
    count(*) FILTER (WHERE is_repeat) AS repeat_customers,
    round(100.0 * count(*) FILTER (WHERE is_repeat) / nullif(count(*), 0), 2)
        AS repeat_rate_pct,
    round(
        100.0 * coalesce(sum(revenue) FILTER (WHERE is_repeat), 0) / nullif(sum(revenue), 0),
        1
    ) AS repeat_revenue_share_pct
FROM analytics.customer_orders;
