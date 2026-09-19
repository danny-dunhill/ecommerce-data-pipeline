import pandas as pd
import pytest

from ecom_pipeline.tables import TABLES
from ecom_pipeline.transform import (
    INPUT_TABLES,
    UNKNOWN_CATEGORY,
    CleanData,
    TransformError,
    clean_customers,
    clean_order_items,
    clean_orders,
    clean_products,
    transform,
)
from sample_data import DATASET, raw_frames


def frame(table: str, rows: list[dict]) -> pd.DataFrame:
    """A raw (all text) staging DataFrame with the exact columns of ``table``."""
    columns = next(spec.columns for spec in TABLES if spec.name == table)
    return pd.DataFrame(
        [{column: row.get(column) for column in columns} for row in rows],
        columns=list(columns),
        dtype=object,
    )


# --- customers ---------------------------------------------------------------------------


def test_clean_customers_normalises_text():
    raw = frame(
        "customers",
        [
            {
                "customer_id": " c1 ",
                "customer_unique_id": "u1",
                "customer_zip_code_prefix": "1046",
                "customer_city": "  sao paulo ",
                "customer_state": "sp",
            }
        ],
    )

    row = clean_customers(raw).iloc[0]

    assert row["customer_id"] == "c1"
    assert row["customer_zip_code_prefix"] == "01046"  # leading zero restored, still text
    assert row["customer_city"] == "Sao Paulo"
    assert row["customer_state"] == "SP"


def test_clean_customers_turns_empty_text_into_missing_values():
    raw = frame("customers", [{"customer_id": "c1", "customer_city": "   "}])

    cleaned = clean_customers(raw)

    assert pd.isna(cleaned.loc[0, "customer_city"])
    assert pd.isna(cleaned.loc[0, "customer_state"])


def test_clean_customers_reports_missing_columns():
    with pytest.raises(TransformError, match="missing columns"):
        clean_customers(pd.DataFrame({"customer_id": ["c1"]}))


# --- products ----------------------------------------------------------------------------


def translation_frame():
    return frame(
        "product_category_translation",
        [
            {
                "product_category_name": "beleza_saude",
                "product_category_name_english": "health_beauty",
            }
        ],
    )


def test_clean_products_renames_misspelled_columns_and_types_numbers():
    raw = frame(
        "products",
        [
            {
                "product_id": "p1",
                "product_category_name": "beleza_saude",
                "product_name_lenght": "40",
                "product_description_lenght": "287.0",
                "product_photos_qty": "1",
                "product_weight_g": "225",
            }
        ],
    )

    cleaned = clean_products(raw, translation_frame())

    assert "product_name_lenght" not in cleaned.columns
    assert cleaned.loc[0, "name_length"] == 40
    assert cleaned.loc[0, "description_length"] == 287  # "287.0" is a whole number
    assert str(cleaned["weight_g"].dtype) == "Int64"
    assert pd.isna(cleaned.loc[0, "length_cm"])  # missing stays missing, it is not 0


def test_clean_products_adds_english_category_with_fallbacks():
    raw = frame(
        "products",
        [
            {"product_id": "p1", "product_category_name": "beleza_saude"},
            {"product_id": "p2", "product_category_name": "pc_gamer"},  # no translation
            {"product_id": "p3", "product_category_name": None},  # no category at all
        ],
    )

    cleaned = clean_products(raw, translation_frame())

    assert list(cleaned["category_name_en"]) == ["health_beauty", "pc_gamer", UNKNOWN_CATEGORY]
    assert cleaned.loc[2, "category_name"] is pd.NA  # the original stays missing


def test_clean_products_does_not_multiply_rows_when_translation_has_duplicates():
    duplicated = frame(
        "product_category_translation",
        [
            {"product_category_name": "a", "product_category_name_english": "x"},
            {"product_category_name": "a", "product_category_name_english": "y"},
        ],
    )
    raw = frame("products", [{"product_id": "p1", "product_category_name": "a"}])

    with pytest.raises(TransformError, match="listed twice"):
        clean_products(raw, duplicated)


def test_clean_products_rejects_fractional_lengths():
    raw = frame("products", [{"product_id": "p1", "product_name_lenght": "40.5"}])

    with pytest.raises(TransformError, match="not whole numbers"):
        clean_products(raw, translation_frame())


# --- orders ------------------------------------------------------------------------------


def test_clean_orders_parses_timestamps_and_lowercases_status():
    raw = frame(
        "orders",
        [
            {
                "order_id": "o1",
                "customer_id": "c1",
                "order_status": " Delivered",
                "order_purchase_timestamp": "2017-10-02 10:56:33",
                "order_approved_at": None,
            }
        ],
    )

    row = clean_orders(raw).iloc[0]

    assert row["order_status"] == "delivered"
    assert row["order_purchase_timestamp"] == pd.Timestamp("2017-10-02 10:56:33")
    assert pd.isna(row["order_approved_at"])  # missing timestamp -> NaT


def test_clean_orders_rejects_an_unexpected_timestamp_format():
    raw = frame("orders", [{"order_id": "o1", "order_purchase_timestamp": "02/10/2017 10:56"}])

    with pytest.raises(TransformError, match=r"orders\.order_purchase_timestamp"):
        clean_orders(raw)


# --- order items -------------------------------------------------------------------------


def test_clean_order_items_types_and_rounds_amounts():
    raw = frame(
        "order_items",
        [
            {
                "order_id": "o1",
                "order_item_id": "1",
                "product_id": "p1",
                "seller_id": "s1",
                "shipping_limit_date": "2017-09-19 09:45:35",
                "price": "58.9",
                "freight_value": "13.299",
            }
        ],
    )

    row = clean_order_items(raw).iloc[0]

    assert row["order_item_id"] == 1
    assert row["price"] == 58.9
    assert row["freight_value"] == 13.3  # rounded to cents
    assert row["shipping_limit_date"] == pd.Timestamp("2017-09-19 09:45:35")


def test_clean_order_items_rejects_a_price_that_is_not_a_number():
    raw = frame("order_items", [{"order_id": "o1", "order_item_id": "1", "price": "12,50"}])

    with pytest.raises(TransformError, match=r"order_items\.price"):
        clean_order_items(raw)


# --- the whole transform -----------------------------------------------------------------


def test_transform_keeps_every_row():
    clean = transform(raw_frames())

    assert isinstance(clean, CleanData)
    assert len(clean.customers) == len(DATASET["customers"])
    assert len(clean.products) == len(DATASET["products"])
    assert len(clean.orders) == len(DATASET["orders"])
    assert len(clean.order_items) == len(DATASET["order_items"])
    assert len(clean.order_payments) == len(DATASET["order_payments"])


def test_transform_does_not_modify_its_input():
    raw = raw_frames()
    before = {name: frame_.copy() for name, frame_ in raw.items()}

    transform(raw)

    for name in raw:
        assert raw[name].equals(before[name]), name


def test_transform_reports_missing_input_tables():
    raw = raw_frames()
    del raw["orders"]

    with pytest.raises(TransformError, match="orders"):
        transform(raw)


def test_transform_only_needs_the_declared_input_tables():
    raw = {name: frame_ for name, frame_ in raw_frames().items() if name in INPUT_TABLES}

    assert transform(raw).orders.shape[0] == len(DATASET["orders"])
