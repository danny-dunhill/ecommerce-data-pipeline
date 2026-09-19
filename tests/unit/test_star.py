import datetime as dt
from dataclasses import replace

import pandas as pd

from ecom_pipeline.star import (
    DIM_CUSTOMERS_COLUMNS,
    DIM_PRODUCTS_COLUMNS,
    FACT_ORDERS_COLUMNS,
    build_dim_customers,
    build_dim_date,
    build_dim_products,
    build_fact_orders,
    build_star,
    date_key,
)
from ecom_pipeline.transform import transform
from sample_data import DATASET, raw_frames


def clean_data():
    return transform(raw_frames())


# --- dim_date ----------------------------------------------------------------------------


def test_date_key_writes_the_date_as_a_number():
    days = pd.Series(pd.to_datetime(["2017-10-02", "2018-01-31"]))

    assert list(date_key(days)) == [20171002, 20180131]


def test_date_key_keeps_missing_dates_missing():
    days = pd.Series(pd.to_datetime(["2017-10-02", None]))

    keys = date_key(days)

    assert keys[0] == 20171002
    assert pd.isna(keys[1])


def test_dim_date_has_one_row_per_day_including_a_leap_day():
    dim_date = build_dim_date(dt.date(2020, 2, 28), dt.date(2020, 3, 1))

    assert list(dim_date["date_key"]) == [20200228, 20200229, 20200301]
    assert dim_date["date_key"].is_unique


def test_dim_date_describes_each_day():
    dim_date = build_dim_date(dt.date(2017, 1, 1), dt.date(2017, 1, 2)).set_index("date_key")

    sunday, monday = dim_date.loc[20170101], dim_date.loc[20170102]

    assert sunday["day_name"] == "Sunday"
    assert sunday["day_of_week"] == 7  # ISO: Sunday is the last day of the week
    assert bool(sunday["is_weekend"]) is True
    assert monday["day_of_week"] == 1
    assert bool(monday["is_weekend"]) is False
    assert monday["month_name"] == "January"
    assert monday["quarter"] == 1
    assert monday["full_date"] == dt.date(2017, 1, 2)


# --- the other dimensions ----------------------------------------------------------------


def test_dim_customers_uses_the_warehouse_column_names():
    dim_customers = build_dim_customers(clean_data())

    assert list(dim_customers.columns) == list(DIM_CUSTOMERS_COLUMNS)
    assert len(dim_customers) == len(DATASET["customers"])
    assert dim_customers.loc[0, "city"] == "Sao Paulo"


def test_dim_products_keeps_every_product_even_if_it_was_never_ordered():
    dim_products = build_dim_products(clean_data())

    assert list(dim_products.columns) == list(DIM_PRODUCTS_COLUMNS)
    assert set(dim_products["product_id"]) == {"p1", "p2", "p3", "p4"}  # p4 is never ordered


# --- fact_orders -------------------------------------------------------------------------


def test_fact_has_one_row_per_order_item():
    fact = build_fact_orders(clean_data())

    assert list(fact.columns) == list(FACT_ORDERS_COLUMNS)
    assert len(fact) == len(DATASET["order_items"])  # order o1 has two items -> two rows
    assert fact[["order_id", "order_item_id"]].drop_duplicates().shape[0] == len(fact)


def test_fact_rows_carry_the_columns_of_their_order():
    fact = build_fact_orders(clean_data()).set_index(["order_id", "order_item_id"])

    row = fact.loc[("o1", 2)]

    assert row["customer_id"] == "c1"
    assert row["product_id"] == "p2"
    assert row["order_status"] == "delivered"
    assert row["purchased_at"] == pd.Timestamp("2017-01-01 10:00:00")
    assert row["order_date_key"] == 20170101
    assert row["price"] == 20.0
    assert pd.isna(row["delivered_at"])


def test_orders_without_items_are_not_in_the_fact_table():
    clean = clean_data()
    without_o3 = replace(
        clean, order_items=clean.order_items[clean.order_items["order_id"] != "o3"]
    )

    fact = build_fact_orders(without_o3)

    assert "o3" not in set(fact["order_id"])
    assert len(fact) == 3


def test_fact_revenue_equals_the_revenue_of_the_items():
    clean = clean_data()

    fact = build_fact_orders(clean)

    assert fact["price"].sum() == clean.order_items["price"].sum() == 55.0


# --- the whole star ----------------------------------------------------------------------


def test_dim_date_covers_whole_calendar_years_and_every_fact_date():
    star = build_star(clean_data())

    assert len(star.dim_date) == 365  # all of 2017
    assert set(star.fact_orders["order_date_key"]) <= set(star.dim_date["date_key"])


def test_star_can_be_built_when_there_are_no_items():
    clean = clean_data()
    empty = replace(clean, order_items=clean.order_items.iloc[0:0])

    star = build_star(empty)

    assert len(star.fact_orders) == 0
    assert len(star.dim_date) == 0
    assert len(star.dim_customers) == len(DATASET["customers"])
