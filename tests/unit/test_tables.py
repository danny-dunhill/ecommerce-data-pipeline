import pytest

from ecom_pipeline.tables import TABLES, TableSpec


def test_all_expected_tables_are_defined():
    assert {spec.name for spec in TABLES} == {
        "customers",
        "orders",
        "order_items",
        "order_payments",
        "order_reviews",
        "products",
        "sellers",
        "product_category_translation",
    }


def test_table_names_and_csv_files_are_unique():
    assert len({spec.name for spec in TABLES}) == len(TABLES)
    assert len({spec.csv_file for spec in TABLES}) == len(TABLES)


def test_geolocation_is_intentionally_not_loaded():
    assert not any("geolocation" in spec.csv_file for spec in TABLES)


@pytest.mark.parametrize(
    "name, columns",
    [
        ("orders; DROP TABLE x", ("a",)),  # SQL injection attempt in the table name
        ("orders", ("Bad-Name",)),  # upper case and a dash
        ("orders", ("a b",)),  # space
        ("1orders", ("a",)),  # starts with a digit
        ("orders", ("a", "a")),  # duplicate column
    ],
)
def test_unsafe_or_duplicate_names_are_rejected(name, columns):
    with pytest.raises(ValueError):
        TableSpec(name=name, csv_file="file.csv", columns=columns)
