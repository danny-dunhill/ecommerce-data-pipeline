-- Example queries against the warehouse. Paste them into any SQL client (DBeaver, pgAdmin,
-- a VS Code SQL extension), or run the whole file from PowerShell:
--   Get-Content sql\example_queries.sql | docker compose exec -T db psql -U ecom -d ecom
-- Load the data first: `pipeline run --data-dir data/sample`.

-- 1. Revenue per month, with growth (uses the analytics views)
SELECT month_start, orders, revenue, avg_order_value, revenue_growth_pct
FROM analytics.monthly_revenue
ORDER BY month_start;

-- 2. The ten best-selling products
SELECT revenue_rank, category, units_sold, revenue
FROM analytics.top_products
ORDER BY revenue_rank, product_id
LIMIT 10;

-- 3. How many customers came back?
SELECT * FROM analytics.repeat_customers;

-- 4. Revenue by customer state (a join across the star: fact -> customers)
SELECT c.state, count(DISTINCT s.order_id) AS orders, sum(s.price) AS revenue
FROM analytics.sales_items AS s
JOIN dw.dim_customers AS c USING (customer_key)
GROUP BY c.state
ORDER BY revenue DESC
LIMIT 10;

-- 5. Revenue by product category (a join across the star: fact -> products)
SELECT p.category_name_en AS category, sum(s.price) AS revenue
FROM analytics.sales_items AS s
JOIN dw.dim_products AS p USING (product_key)
GROUP BY p.category_name_en
ORDER BY revenue DESC
LIMIT 10;

-- 6. Do people buy more on weekends? (a join across the star: fact -> date)
SELECT d.is_weekend, count(DISTINCT s.order_id) AS orders, sum(s.price) AS revenue
FROM analytics.sales_items AS s
JOIN dw.dim_date AS d ON d.date_key = s.order_date_key
GROUP BY d.is_weekend;

-- 7. Average days from purchase to delivery, per month (uses the fact table directly)
SELECT d.year, d.month,
       round(avg(EXTRACT(EPOCH FROM (f.delivered_at - f.purchased_at)) / 86400), 1)
           AS avg_delivery_days
FROM dw.fact_orders AS f
JOIN dw.dim_date AS d ON d.date_key = f.order_date_key
WHERE f.delivered_at IS NOT NULL
GROUP BY d.year, d.month
ORDER BY d.year, d.month;
