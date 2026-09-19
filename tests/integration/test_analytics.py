"""Integration tests: the analytical views and reports, on a real PostgreSQL."""

from dataclasses import replace

import pandas as pd
import pytest
from sqlalchemy import text
from typer.testing import CliRunner

from ecom_pipeline.cli import app
from ecom_pipeline.reports import REPORTS, fetch_report
from ecom_pipeline.transform import transform
from ecom_pipeline.warehouse import load_warehouse
from sample_data import raw_frames, write_dataset

pytestmark = pytest.mark.integration


def rows(engine, sql):
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(text(sql))]


@pytest.fixture
def clean():
    return transform(raw_frames())


def test_monthly_revenue_sums_prices_freight_and_orders(engine, clean_warehouse, clean):
    load_warehouse(engine, clean)

    ((month_start, orders, items, revenue, freight, average, growth),) = rows(
        engine,
        "SELECT month_start, orders, items, revenue, freight, avg_order_value,"
        " revenue_growth_pct FROM analytics.monthly_revenue",
    )

    assert str(month_start) == "2017-01-01"
    assert (orders, items) == (3, 4)  # order o1 has two items
    assert (revenue, freight) == (55, 9)
    assert float(average) == 18.33
    assert growth is None  # there is no previous month to compare with


def test_monthly_revenue_shows_growth_against_the_previous_month(engine, clean_warehouse, clean):
    orders = clean.orders.copy()
    orders.loc[orders["order_id"] == "o3", "order_purchase_timestamp"] = pd.Timestamp("2017-02-10")
    load_warehouse(engine, replace(clean, orders=orders))

    result = rows(
        engine,
        "SELECT month_start, revenue, revenue_growth_pct FROM analytics.monthly_revenue"
        " ORDER BY month_start",
    )

    assert [(str(m), r) for m, r, _ in result] == [("2017-01-01", 50), ("2017-02-01", 5)]
    assert result[1][2] == -90  # from 50 down to 5


def test_growth_is_empty_after_a_month_without_sales(engine, clean_warehouse, clean):
    orders = clean.orders.copy()
    # January and March have sales, February has none: March is not "month over month"
    orders.loc[orders["order_id"] == "o3", "order_purchase_timestamp"] = pd.Timestamp("2017-03-10")
    load_warehouse(engine, replace(clean, orders=orders))

    result = rows(
        engine,
        "SELECT month_start, revenue_growth_pct FROM analytics.monthly_revenue"
        " ORDER BY month_start",
    )

    assert [(str(month), growth) for month, growth in result] == [
        ("2017-01-01", None),
        ("2017-03-01", None),
    ]


def test_monthly_report_with_a_limit_keeps_the_latest_months(engine, clean_warehouse, clean):
    orders = clean.orders.copy()
    orders.loc[orders["order_id"] == "o3", "order_purchase_timestamp"] = pd.Timestamp("2017-02-10")
    load_warehouse(engine, replace(clean, orders=orders))
    report = REPORTS["monthly-revenue"]

    _, latest = fetch_report(engine, report, limit=1)
    _, both = fetch_report(engine, report, limit=5)

    assert [str(row[2]) for row in latest] == ["2017-02-01"]
    assert [str(row[2]) for row in both] == ["2017-01-01", "2017-02-01"]  # oldest first


def test_canceled_orders_do_not_count_as_sales(engine, clean_warehouse, clean):
    orders = clean.orders.copy()
    orders.loc[orders["order_id"] == "o3", "order_status"] = "canceled"
    load_warehouse(engine, replace(clean, orders=orders))

    ((order_count, revenue),) = rows(
        engine, "SELECT orders, revenue FROM analytics.monthly_revenue"
    )

    assert (order_count, revenue) == (2, 50)


def test_top_products_are_ranked_by_revenue(engine, clean_warehouse, clean):
    load_warehouse(engine, clean)

    result = rows(
        engine,
        "SELECT revenue_rank, product_id, units_sold, revenue FROM analytics.top_products"
        " ORDER BY revenue_rank",
    )

    # p2 was sold twice (2 x 20), p1 once (10), p3 once (5)
    assert result == [(1, "p2", 2, 40), (2, "p1", 1, 10), (3, "p3", 1, 5)]


def test_repeat_customers_are_counted_by_the_person_not_by_the_order(
    engine, clean_warehouse, clean
):
    customers = clean.customers.copy()
    # customer_id c2 belongs to the same real person as c1: that person ordered twice
    customers.loc[customers["customer_id"] == "c2", "customer_unique_id"] = "u1"
    load_warehouse(engine, replace(clean, customers=customers))

    ((people, repeat, rate, revenue_share),) = rows(
        engine, "SELECT * FROM analytics.repeat_customers"
    )

    assert (people, repeat) == (2, 1)
    assert float(rate) == 50.0
    assert float(revenue_share) == 90.9  # 50 of the 55 total


def test_views_can_be_created_again_by_a_second_load(engine, clean_warehouse, clean):
    load_warehouse(engine, clean)
    load_warehouse(engine, clean)

    assert rows(engine, "SELECT count(*) FROM analytics.monthly_revenue") == [(1,)]


def test_report_commands_print_results_from_the_warehouse(
    engine, clean_staging, clean_warehouse, tmp_path
):
    write_dataset(tmp_path)
    runner = CliRunner()
    assert runner.invoke(app, ["run", "--data-dir", str(tmp_path)]).exit_code == 0

    monthly = runner.invoke(app, ["report", "monthly-revenue"])
    top_one = runner.invoke(app, ["report", "top-products", "--limit", "1"])

    assert monthly.exit_code == 0, monthly.output
    assert "2017-01-01" in monthly.output
    assert "55.00" in monthly.output
    assert top_one.exit_code == 0, top_one.output
    assert "p2" in top_one.output
    assert "p1" not in top_one.output  # the limit is applied


def test_report_command_needs_a_loaded_warehouse(engine, clean_warehouse):
    result = CliRunner().invoke(app, ["report", "monthly-revenue"])

    assert result.exit_code == 3
    assert "load-warehouse" in result.output
