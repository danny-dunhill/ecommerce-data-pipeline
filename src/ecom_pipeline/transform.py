"""Clean and type the raw staging data with pandas.

Staging holds text only. This module turns it into tables with real types (timestamps,
integers, money) and consistent values (trimmed text, upper-case state codes, English
product categories). All functions are pure: a DataFrame goes in, a new DataFrame comes
out, and nothing touches the database. That makes them easy to test with tiny inputs.

Two kinds of problems are handled in two different places:

* **Type problems** (a price that is not a number, a timestamp in an unknown format)
  mean the source does not look like we expect. They stop the run right here with a
  ``TransformError``, because guessing would silently produce wrong numbers.
* **Business-rule problems** (an order without a customer, a delivery before the
  purchase) are *data quality*. They are found by ``ecom_pipeline.quality`` and reported
  with a severity, so that a human can decide what to do.

No row is ever dropped or "fixed" silently here.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd

logger = logging.getLogger(__name__)

# Staging tables the transform step reads (reviews and sellers are not used by the star
# schema, so they stay in staging only).
INPUT_TABLES: tuple[str, ...] = (
    "customers",
    "orders",
    "order_items",
    "order_payments",
    "products",
    "product_category_translation",
)

UNKNOWN_CATEGORY = "unknown"
_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"  # the format used by every timestamp in the source


class TransformError(ValueError):
    """Raised when the raw data cannot be converted to the expected types."""


@dataclass(frozen=True)
class CleanData:
    """The cleaned, typed tables. One DataFrame per table, no row dropped."""

    customers: pd.DataFrame
    products: pd.DataFrame
    orders: pd.DataFrame
    order_items: pd.DataFrame
    order_payments: pd.DataFrame


# --- small building blocks --------------------------------------------------------------


def _require_columns(frame: pd.DataFrame, table: str, columns: list[str]) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise TransformError(f"{table}: missing columns {missing}")


def _text(series: pd.Series) -> pd.Series:
    """Trim whitespace and turn empty strings into missing values (``<NA>``)."""
    return series.astype("string").str.strip().replace("", pd.NA)


def _timestamp(series: pd.Series, table: str, column: str) -> pd.Series:
    """Parse ``YYYY-MM-DD HH:MM:SS`` strictly. Missing values become ``NaT``."""
    try:
        parsed = pd.to_datetime(_text(series), format=_TIMESTAMP_FORMAT, errors="raise")
    except (ValueError, TypeError) as exc:
        raise TransformError(f"{table}.{column}: not a valid timestamp ({exc})") from exc
    return parsed.astype("datetime64[us]")  # the same precision in every column and pandas version


def _number(series: pd.Series, table: str, column: str) -> pd.Series:
    try:
        return pd.to_numeric(_text(series), errors="raise")
    except (ValueError, TypeError) as exc:
        raise TransformError(f"{table}.{column}: not a number ({exc})") from exc


def _integer(series: pd.Series, table: str, column: str) -> pd.Series:
    """Whole numbers with support for missing values (nullable ``Int64``)."""
    numbers = _number(series, table, column)
    if (numbers.dropna() % 1 != 0).any():
        raise TransformError(f"{table}.{column}: contains values that are not whole numbers")
    return numbers.astype("Int64")


def _money(series: pd.Series, table: str, column: str) -> pd.Series:
    """Amounts rounded to cents (nullable ``Float64``)."""
    return _number(series, table, column).astype("Float64").round(2)


# --- one function per table ---------------------------------------------------------------


def clean_customers(customers: pd.DataFrame) -> pd.DataFrame:
    """Trim text, keep zip codes as 5-character text, upper-case the state, title-case the city.

    ``customer_id`` is created per *order* in the source, while ``customer_unique_id``
    identifies the real person. Both are kept, because "repeat customers" needs the second.
    """
    table = "customers"
    _require_columns(
        customers,
        table,
        [
            "customer_id",
            "customer_unique_id",
            "customer_zip_code_prefix",
            "customer_city",
            "customer_state",
        ],
    )
    return pd.DataFrame(
        {
            "customer_id": _text(customers["customer_id"]),
            "customer_unique_id": _text(customers["customer_unique_id"]),
            # text, not a number: a zip code can start with 0 and is never used for maths
            "customer_zip_code_prefix": _text(customers["customer_zip_code_prefix"]).str.zfill(5),
            "customer_city": _text(customers["customer_city"]).str.title(),
            "customer_state": _text(customers["customer_state"]).str.upper(),
        }
    )


def clean_products(products: pd.DataFrame, translation: pd.DataFrame) -> pd.DataFrame:
    """Fix the misspelled column names and add the English category name.

    ``category_name_en`` falls back to the Portuguese name when the translation table has
    no entry, and to ``"unknown"`` when the product has no category at all.
    """
    table = "products"
    _require_columns(
        products,
        table,
        [
            "product_id",
            "product_category_name",
            "product_name_lenght",
            "product_description_lenght",
            "product_photos_qty",
            "product_weight_g",
            "product_length_cm",
            "product_height_cm",
            "product_width_cm",
        ],
    )
    _require_columns(
        translation,
        "product_category_translation",
        ["product_category_name", "product_category_name_english"],
    )

    portuguese_to_english = pd.Series(
        _text(translation["product_category_name_english"]).to_numpy(),
        index=_text(translation["product_category_name"]).to_numpy(),
        dtype="string",
    )
    if portuguese_to_english.index.has_duplicates:
        raise TransformError("product_category_translation: a category is listed twice")

    category = _text(products["product_category_name"])
    untranslated = sorted(set(category.dropna()) - set(portuguese_to_english.index))
    if untranslated:
        logger.warning(
            "%d product categories have no English translation and keep their original name: %s",
            len(untranslated),
            ", ".join(untranslated),
        )
    english = category.map(portuguese_to_english).astype("string")

    return pd.DataFrame(
        {
            "product_id": _text(products["product_id"]),
            "category_name": category,
            "category_name_en": english.fillna(category).fillna(UNKNOWN_CATEGORY),
            "name_length": _integer(products["product_name_lenght"], table, "name_length"),
            "description_length": _integer(
                products["product_description_lenght"], table, "description_length"
            ),
            "photos_qty": _integer(products["product_photos_qty"], table, "photos_qty"),
            "weight_g": _integer(products["product_weight_g"], table, "weight_g"),
            "length_cm": _integer(products["product_length_cm"], table, "length_cm"),
            "height_cm": _integer(products["product_height_cm"], table, "height_cm"),
            "width_cm": _integer(products["product_width_cm"], table, "width_cm"),
        }
    )


def clean_orders(orders: pd.DataFrame) -> pd.DataFrame:
    """Parse the five timestamps and normalise the status to lower case.

    The timestamps have no time zone in the source (they are Brazilian local time), so
    they stay "naive" too. We do not invent a time zone.
    """
    table = "orders"
    timestamp_columns = [
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ]
    _require_columns(orders, table, ["order_id", "customer_id", "order_status", *timestamp_columns])

    cleaned = {
        "order_id": _text(orders["order_id"]),
        "customer_id": _text(orders["customer_id"]),
        "order_status": _text(orders["order_status"]).str.lower(),
    }
    for column in timestamp_columns:
        cleaned[column] = _timestamp(orders[column], table, column)
    return pd.DataFrame(cleaned)


def clean_order_items(order_items: pd.DataFrame) -> pd.DataFrame:
    """Type the item lines: one row per product in an order."""
    table = "order_items"
    _require_columns(
        order_items,
        table,
        [
            "order_id",
            "order_item_id",
            "product_id",
            "seller_id",
            "shipping_limit_date",
            "price",
            "freight_value",
        ],
    )
    return pd.DataFrame(
        {
            "order_id": _text(order_items["order_id"]),
            "order_item_id": _integer(order_items["order_item_id"], table, "order_item_id"),
            "product_id": _text(order_items["product_id"]),
            "seller_id": _text(order_items["seller_id"]),
            "shipping_limit_date": _timestamp(
                order_items["shipping_limit_date"], table, "shipping_limit_date"
            ),
            "price": _money(order_items["price"], table, "price"),
            "freight_value": _money(order_items["freight_value"], table, "freight_value"),
        }
    )


def clean_order_payments(order_payments: pd.DataFrame) -> pd.DataFrame:
    """Type the payments. An order can be paid with several methods, one row each."""
    table = "order_payments"
    _require_columns(
        order_payments,
        table,
        [
            "order_id",
            "payment_sequential",
            "payment_type",
            "payment_installments",
            "payment_value",
        ],
    )
    return pd.DataFrame(
        {
            "order_id": _text(order_payments["order_id"]),
            "payment_sequential": _integer(
                order_payments["payment_sequential"], table, "payment_sequential"
            ),
            "payment_type": _text(order_payments["payment_type"]).str.lower(),
            "payment_installments": _integer(
                order_payments["payment_installments"], table, "payment_installments"
            ),
            "payment_value": _money(order_payments["payment_value"], table, "payment_value"),
        }
    )


def transform(raw: Mapping[str, pd.DataFrame]) -> CleanData:
    """Clean all tables. ``raw`` maps a staging table name to its DataFrame."""
    missing = [name for name in INPUT_TABLES if name not in raw]
    if missing:
        raise TransformError(f"Missing input tables: {missing}")

    clean = CleanData(
        customers=clean_customers(raw["customers"]),
        products=clean_products(raw["products"], raw["product_category_translation"]),
        orders=clean_orders(raw["orders"]),
        order_items=clean_order_items(raw["order_items"]),
        order_payments=clean_order_payments(raw["order_payments"]),
    )
    logger.info(
        "Transformed %d customers, %d products, %d orders, %d order items, %d payments",
        len(clean.customers),
        len(clean.products),
        len(clean.orders),
        len(clean.order_items),
        len(clean.order_payments),
    )
    return clean
