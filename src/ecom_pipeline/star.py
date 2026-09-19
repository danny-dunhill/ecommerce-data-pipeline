"""Build the star-schema tables (as DataFrames) from the cleaned data.

The functions here are pure: cleaned tables in, one DataFrame per warehouse table out.
They rename columns to the warehouse names and prepare the fact rows, but they know
nothing about the database. Loading them is the job of ``ecom_pipeline.warehouse``.

Grain of the fact table: **one row per order item**. Revenue and "top products" need the
product of every line, so an order with three products becomes three fact rows. Orders
without any item add no revenue and have no product, so they are not in the fact table.
"""

import datetime as dt
from dataclasses import dataclass

import pandas as pd

from ecom_pipeline.transform import CleanData

DIM_DATE_COLUMNS = (
    "date_key",
    "full_date",
    "year",
    "quarter",
    "month",
    "month_name",
    "day_of_month",
    "day_of_week",
    "day_name",
    "is_weekend",
)
DIM_CUSTOMERS_COLUMNS = (
    "customer_id",
    "customer_unique_id",
    "zip_code_prefix",
    "city",
    "state",
)
DIM_PRODUCTS_COLUMNS = (
    "product_id",
    "category_name",
    "category_name_en",
    "name_length",
    "description_length",
    "photos_qty",
    "weight_g",
    "length_cm",
    "height_cm",
    "width_cm",
)
# The fact columns as they are before the surrogate keys are looked up: the business ids
# (customer_id, product_id) still stand where the database will later put customer_key
# and product_key.
FACT_ORDERS_COLUMNS = (
    "order_id",
    "order_item_id",
    "customer_id",
    "product_id",
    "order_date_key",
    "seller_id",
    "order_status",
    "purchased_at",
    "delivered_at",
    "estimated_delivery_at",
    "price",
    "freight_value",
)


@dataclass(frozen=True)
class StarData:
    """All warehouse tables, ready to be loaded."""

    dim_date: pd.DataFrame
    dim_customers: pd.DataFrame
    dim_products: pd.DataFrame
    fact_orders: pd.DataFrame


def date_key(timestamps: pd.Series) -> pd.Series:
    """Turn dates into the number ``YYYYMMDD`` (2017-10-02 -> 20171002).

    The same function builds the keys of ``dim_date`` and of the fact table, so they
    always agree.
    """
    keys = timestamps.dt.year * 10000 + timestamps.dt.month * 100 + timestamps.dt.day
    return keys.astype("Int64")


def build_dim_date(start: dt.date, end: dt.date) -> pd.DataFrame:
    """One row per day from ``start`` to ``end`` (both included)."""
    days = pd.Series(pd.date_range(start, end, freq="D"))
    return pd.DataFrame(
        {
            "date_key": date_key(days),
            "full_date": days.dt.date,
            "year": days.dt.year,
            "quarter": days.dt.quarter,
            "month": days.dt.month,
            "month_name": days.dt.month_name(),
            "day_of_month": days.dt.day,
            "day_of_week": days.dt.dayofweek + 1,  # pandas: Monday = 0, ISO: Monday = 1
            "day_name": days.dt.day_name(),
            "is_weekend": days.dt.dayofweek >= 5,
        },
        columns=list(DIM_DATE_COLUMNS),
    )


def build_dim_customers(clean: CleanData) -> pd.DataFrame:
    """One row per ``customer_id``, with the warehouse column names."""
    customers = clean.customers.rename(
        columns={
            "customer_zip_code_prefix": "zip_code_prefix",
            "customer_city": "city",
            "customer_state": "state",
        }
    )
    return customers[list(DIM_CUSTOMERS_COLUMNS)].reset_index(drop=True)


def build_dim_products(clean: CleanData) -> pd.DataFrame:
    """One row per product."""
    return clean.products[list(DIM_PRODUCTS_COLUMNS)].reset_index(drop=True)


def build_fact_orders(clean: CleanData) -> pd.DataFrame:
    """One row per order item, joined with the columns of its order.

    An item whose order is unknown would be dropped by the inner join, but the data-quality
    checks (``items_order_exists``) stop such data before it gets here.
    """
    order_columns = {
        "order_purchase_timestamp": "purchased_at",
        "order_delivered_customer_date": "delivered_at",
        "order_estimated_delivery_date": "estimated_delivery_at",
    }
    orders = clean.orders.rename(columns=order_columns)[
        ["order_id", "customer_id", "order_status", *order_columns.values()]
    ]

    fact = clean.order_items.merge(orders, on="order_id", how="inner", validate="many_to_one")
    fact["order_date_key"] = date_key(fact["purchased_at"])
    return fact[list(FACT_ORDERS_COLUMNS)].reset_index(drop=True)


def build_star(clean: CleanData) -> StarData:
    """Build every warehouse table from the cleaned data."""
    fact_orders = build_fact_orders(clean)

    purchased = fact_orders["purchased_at"].dropna()
    if purchased.empty:
        dim_date = build_dim_date(dt.date(2000, 1, 1), dt.date(2000, 1, 1)).iloc[0:0]
    else:
        # whole calendar years, so that every month in a report is a complete month
        dim_date = build_dim_date(
            dt.date(purchased.min().year, 1, 1), dt.date(purchased.max().year, 12, 31)
        )

    return StarData(
        dim_date=dim_date,
        dim_customers=build_dim_customers(clean),
        dim_products=build_dim_products(clean),
        fact_orders=fact_orders,
    )
