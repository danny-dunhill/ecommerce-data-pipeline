"""Description of the raw source files and the staging tables they are loaded into.

This module is the single source of truth for the source layout: the CSV validation,
the ``CREATE TABLE`` statements, the ``COPY`` statements and the sample builder all
read it, so a column is only ever spelled out in one place.

The column names are copied 1:1 from the CSV headers, including the misspellings that
exist in the original dataset (``product_name_lenght``). Staging is a raw copy of the
source. Renaming and typing happens later, in the transform step.
"""

import re
from dataclasses import dataclass

# Only plain lower-case identifiers are allowed, because table and column names are
# placed into SQL text. Everything else is rejected when a spec is created.
_SAFE_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]*")


@dataclass(frozen=True)
class TableSpec:
    """One source CSV file and the staging table it is loaded into."""

    name: str  # staging table name, e.g. "orders"
    csv_file: str  # file name inside the data directory
    columns: tuple[str, ...]  # column names in the exact order of the CSV header

    def __post_init__(self) -> None:
        for identifier in (self.name, *self.columns):
            if not _SAFE_IDENTIFIER.fullmatch(identifier):
                raise ValueError(f"Not a safe SQL identifier: {identifier!r}")
        if len(set(self.columns)) != len(self.columns):
            raise ValueError(f"Duplicate column names in table {self.name!r}")


TABLES: tuple[TableSpec, ...] = (
    TableSpec(
        name="customers",
        csv_file="olist_customers_dataset.csv",
        columns=(
            "customer_id",
            "customer_unique_id",
            "customer_zip_code_prefix",
            "customer_city",
            "customer_state",
        ),
    ),
    TableSpec(
        name="orders",
        csv_file="olist_orders_dataset.csv",
        columns=(
            "order_id",
            "customer_id",
            "order_status",
            "order_purchase_timestamp",
            "order_approved_at",
            "order_delivered_carrier_date",
            "order_delivered_customer_date",
            "order_estimated_delivery_date",
        ),
    ),
    TableSpec(
        name="order_items",
        csv_file="olist_order_items_dataset.csv",
        columns=(
            "order_id",
            "order_item_id",
            "product_id",
            "seller_id",
            "shipping_limit_date",
            "price",
            "freight_value",
        ),
    ),
    TableSpec(
        name="order_payments",
        csv_file="olist_order_payments_dataset.csv",
        columns=(
            "order_id",
            "payment_sequential",
            "payment_type",
            "payment_installments",
            "payment_value",
        ),
    ),
    TableSpec(
        name="order_reviews",
        csv_file="olist_order_reviews_dataset.csv",
        columns=(
            "review_id",
            "order_id",
            "review_score",
            "review_comment_title",
            "review_comment_message",
            "review_creation_date",
            "review_answer_timestamp",
        ),
    ),
    TableSpec(
        name="products",
        csv_file="olist_products_dataset.csv",
        columns=(
            "product_id",
            "product_category_name",
            "product_name_lenght",  # sic: the misspelling is part of the source data
            "product_description_lenght",  # sic
            "product_photos_qty",
            "product_weight_g",
            "product_length_cm",
            "product_height_cm",
            "product_width_cm",
        ),
    ),
    TableSpec(
        name="sellers",
        csv_file="olist_sellers_dataset.csv",
        columns=(
            "seller_id",
            "seller_zip_code_prefix",
            "seller_city",
            "seller_state",
        ),
    ),
    TableSpec(
        name="product_category_translation",
        csv_file="product_category_name_translation.csv",
        columns=(
            "product_category_name",
            "product_category_name_english",
        ),
    ),
)
# olist_geolocation_dataset.csv is intentionally not loaded: latitude/longitude are not
# needed for the revenue and product analysis, and the file has about one million rows.
