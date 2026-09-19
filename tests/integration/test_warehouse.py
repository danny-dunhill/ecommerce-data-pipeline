"""Integration tests: loading the star schema into a real PostgreSQL."""

from dataclasses import replace

import pytest
from sqlalchemy import text
from typer.testing import CliRunner

from ecom_pipeline.cli import app
from ecom_pipeline.staging import LoadError
from ecom_pipeline.star import build_star
from ecom_pipeline.transform import transform
from ecom_pipeline.warehouse import load_star, load_warehouse
from sample_data import raw_frames, write_dataset

pytestmark = pytest.mark.integration


def rows(engine, sql):
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(text(sql))]


def scalar(engine, sql):
    return rows(engine, sql)[0][0]


def counts(engine):
    return {
        table: scalar(engine, f"SELECT count(*) FROM dw.{table}")
        for table in ("dim_date", "dim_customers", "dim_products", "fact_orders")
    }


@pytest.fixture
def clean():
    return transform(raw_frames())


def test_loads_all_tables(engine, clean_warehouse, clean):
    returned = load_warehouse(engine, clean)

    expected = {"dim_date": 365, "dim_customers": 3, "dim_products": 4, "fact_orders": 4}
    assert returned == expected
    assert counts(engine) == expected


def test_fact_rows_point_to_the_right_dimension_rows(engine, clean_warehouse, clean):
    load_warehouse(engine, clean)

    result = rows(
        engine,
        """
        SELECT f.order_id, f.order_item_id, c.customer_id, p.product_id, d.full_date, f.price
        FROM dw.fact_orders f
        JOIN dw.dim_customers c USING (customer_key)
        JOIN dw.dim_products p USING (product_key)
        JOIN dw.dim_date d ON d.date_key = f.order_date_key
        ORDER BY f.order_id, f.order_item_id
        """,
    )

    assert [(r[0], r[1], r[2], r[3], str(r[4])) for r in result] == [
        ("o1", 1, "c1", "p1", "2017-01-01"),
        ("o1", 2, "c1", "p2", "2017-01-01"),
        ("o2", 1, "c2", "p2", "2017-01-02"),
        ("o3", 1, "c3", "p3", "2017-01-03"),
    ]
    assert scalar(engine, "SELECT sum(price) FROM dw.fact_orders") == 55


def test_running_the_load_twice_changes_nothing(engine, clean_warehouse, clean):
    load_warehouse(engine, clean)
    keys_before = rows(engine, "SELECT customer_id, customer_key FROM dw.dim_customers ORDER BY 1")
    versions_before = rows(engine, "SELECT xmin::text FROM dw.fact_orders ORDER BY order_id, 1")

    load_warehouse(engine, clean)

    assert counts(engine) == {
        "dim_date": 365,
        "dim_customers": 3,
        "dim_products": 4,
        "fact_orders": 4,
    }
    # same surrogate keys, and unchanged rows were not even rewritten
    assert rows(engine, "SELECT customer_id, customer_key FROM dw.dim_customers ORDER BY 1") == (
        keys_before
    )
    assert rows(engine, "SELECT xmin::text FROM dw.fact_orders ORDER BY order_id, 1") == (
        versions_before
    )


def test_changed_source_values_update_the_existing_rows(engine, clean_warehouse, clean):
    load_warehouse(engine, clean)
    key_before = scalar(engine, "SELECT customer_key FROM dw.dim_customers WHERE customer_id='c1'")

    customers = clean.customers.copy()
    customers.loc[customers["customer_id"] == "c1", "customer_city"] = "Campinas"
    items = clean.order_items.copy()
    items.loc[(items["order_id"] == "o1") & (items["order_item_id"] == 1), "price"] = 99.5
    load_warehouse(engine, replace(clean, customers=customers, order_items=items))

    assert counts(engine)["fact_orders"] == 4  # updated, not duplicated
    assert counts(engine)["dim_customers"] == 3
    assert scalar(engine, "SELECT city FROM dw.dim_customers WHERE customer_id='c1'") == "Campinas"
    assert scalar(engine, "SELECT customer_key FROM dw.dim_customers WHERE customer_id='c1'") == (
        key_before
    )
    updated_price = scalar(
        engine, "SELECT price FROM dw.fact_orders WHERE order_id='o1' AND order_item_id=1"
    )
    assert updated_price == 99.5
    assert scalar(engine, "SELECT sum(price) FROM dw.fact_orders") == 144.5


def test_new_source_rows_are_added_and_old_keys_survive(engine, clean_warehouse, clean):
    first = replace(
        clean,
        orders=clean.orders[clean.orders["order_id"] != "o3"],
        order_items=clean.order_items[clean.order_items["order_id"] != "o3"],
    )
    load_warehouse(engine, first)
    assert counts(engine)["fact_orders"] == 3
    keys_before = rows(engine, "SELECT customer_id, customer_key FROM dw.dim_customers ORDER BY 1")

    load_warehouse(engine, clean)

    assert counts(engine)["fact_orders"] == 4
    keys_after = rows(engine, "SELECT customer_id, customer_key FROM dw.dim_customers ORDER BY 1")
    assert keys_after == keys_before


def test_a_fact_row_without_its_product_fails_and_rolls_everything_back(
    engine, clean_warehouse, clean
):
    star = build_star(clean)
    star = replace(star, dim_products=star.dim_products[star.dim_products["product_id"] != "p2"])

    with pytest.raises(LoadError, match="would be lost"):
        load_star(engine, star)

    # the schema was created inside the same transaction, so nothing is left behind
    assert scalar(engine, "SELECT to_regclass('dw.fact_orders') IS NULL") is True
    assert scalar(engine, "SELECT count(*) FROM pg_namespace WHERE nspname = 'dw'") == 0


def test_run_command_builds_the_warehouse_from_csv_files_and_can_be_repeated(
    engine, clean_staging, clean_warehouse, tmp_path
):
    write_dataset(tmp_path)
    runner = CliRunner()

    first = runner.invoke(app, ["run", "--data-dir", str(tmp_path)])
    second = runner.invoke(app, ["run", "--data-dir", str(tmp_path)])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert "Warehouse load finished" in second.output
    assert counts(engine)["fact_orders"] == 4


def test_load_warehouse_command_needs_staging(engine, clean_staging, clean_warehouse):
    result = CliRunner().invoke(app, ["load-warehouse"])

    assert result.exit_code == 3
    assert "load-staging" in result.output
