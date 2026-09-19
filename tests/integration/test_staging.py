"""Integration tests for the staging load, run against a real PostgreSQL."""

import pytest
from sqlalchemy import text

from ecom_pipeline import staging
from ecom_pipeline.staging import LoadError, load_staging
from ecom_pipeline.tables import TABLES
from sample_data import DATASET_ROW_COUNTS, REVIEW_MESSAGE, write_csv, write_dataset

pytestmark = pytest.mark.integration


@pytest.fixture
def source_dir(tmp_path):
    write_dataset(tmp_path)
    return tmp_path


def scalar(engine, sql):
    with engine.connect() as connection:
        return connection.execute(text(sql)).scalar_one()


def table_counts(engine):
    return {
        spec.name: scalar(engine, f"SELECT count(*) FROM staging.{spec.name}") for spec in TABLES
    }


def test_loads_every_table_with_the_expected_row_count(engine, clean_staging, source_dir):
    returned = load_staging(engine, source_dir)

    assert returned == DATASET_ROW_COUNTS
    assert table_counts(engine) == DATASET_ROW_COUNTS


def test_running_the_load_twice_does_not_duplicate_rows(engine, clean_staging, source_dir):
    load_staging(engine, source_dir)
    load_staging(engine, source_dir)

    assert table_counts(engine) == DATASET_ROW_COUNTS


def test_empty_values_become_null(engine, clean_staging, source_dir):
    load_staging(engine, source_dir)

    # o3 has no approval time, r2 has no comment title: both are "" in the CSV file
    assert (
        scalar(engine, "SELECT order_approved_at FROM staging.orders WHERE order_id = 'o3'") is None
    )
    assert (
        scalar(
            engine, "SELECT review_comment_title FROM staging.order_reviews WHERE review_id = 'r2'"
        )
        is None
    )
    assert (
        scalar(engine, "SELECT order_approved_at FROM staging.orders WHERE order_id = 'o1'")
        is not None
    )


def test_quoted_field_with_comma_quotes_and_line_break_is_loaded_intact(
    engine, clean_staging, source_dir
):
    load_staging(engine, source_dir)

    message = scalar(
        engine, "SELECT review_comment_message FROM staging.order_reviews WHERE review_id = 'r1'"
    )

    assert message == REVIEW_MESSAGE


def test_every_row_records_when_it_was_loaded(engine, clean_staging, source_dir):
    load_staging(engine, source_dir)

    assert scalar(engine, "SELECT count(*) FROM staging.orders WHERE _loaded_at IS NULL") == 0


def test_a_file_postgres_rejects_leaves_the_previous_data_untouched(
    engine, clean_staging, source_dir
):
    load_staging(engine, source_dir)
    products = next(spec for spec in TABLES if spec.name == "products")
    # one row has one column too many: PostgreSQL refuses it while the load is running
    broken_row = ["p9", "toys", "1", "2", "3", "4", "5", "6", "7", "EXTRA"]
    write_csv(source_dir / products.csv_file, list(products.columns), [broken_row])

    with pytest.raises(LoadError, match="products"):
        load_staging(engine, source_dir)

    # the whole load was rolled back, so the first load is still intact
    assert table_counts(engine) == DATASET_ROW_COUNTS


def test_a_row_count_mismatch_fails_the_load_and_rolls_it_back(
    engine, clean_staging, source_dir, monkeypatch
):
    load_staging(engine, source_dir)
    monkeypatch.setattr(staging, "count_records", lambda path: 999)

    with pytest.raises(LoadError, match="999"):
        load_staging(engine, source_dir)

    assert table_counts(engine) == DATASET_ROW_COUNTS
