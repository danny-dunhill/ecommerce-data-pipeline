"""Integration tests: staging tables in a real PostgreSQL -> DataFrames -> transform -> checks."""

import pytest
from typer.testing import CliRunner

from ecom_pipeline.cli import app
from ecom_pipeline.quality import has_errors, run_checks
from ecom_pipeline.staging import LoadError, load_staging, read_staging
from ecom_pipeline.tables import TABLES
from ecom_pipeline.transform import INPUT_TABLES, transform
from sample_data import DATASET_ROW_COUNTS, write_dataset

pytestmark = pytest.mark.integration


@pytest.fixture
def loaded_staging(engine, clean_staging, tmp_path):
    write_dataset(tmp_path)
    load_staging(engine, tmp_path)


def input_specs():
    return [spec for spec in TABLES if spec.name in INPUT_TABLES]


def test_read_staging_returns_the_source_columns_as_text(engine, loaded_staging):
    frames = read_staging(engine, input_specs())

    assert set(frames) == set(INPUT_TABLES)
    for spec in input_specs():
        assert list(frames[spec.name].columns) == list(spec.columns)  # no _loaded_at
        assert len(frames[spec.name]) == DATASET_ROW_COUNTS[spec.name]
    orders = frames["orders"].set_index("order_id")
    assert orders.loc["o1", "order_purchase_timestamp"] == "2017-01-01 10:00:00"


def test_read_staging_keeps_empty_values_as_missing(engine, loaded_staging):
    frames = read_staging(engine, input_specs())

    missing_category = frames["products"]["product_category_name"].isna()
    assert missing_category.sum() == 1  # product p3


def test_read_staging_tells_the_user_to_load_staging_first(engine, clean_staging):
    with pytest.raises(LoadError, match="load-staging"):
        read_staging(engine, input_specs())


def test_staging_data_passes_the_transform_and_the_blocking_checks(engine, loaded_staging):
    clean = transform(read_staging(engine, input_specs()))

    assert not has_errors(run_checks(clean))
    assert len(clean.orders) == DATASET_ROW_COUNTS["orders"]


def test_validate_command_works_end_to_end(loaded_staging):
    result = CliRunner().invoke(app, ["validate"])

    assert result.exit_code == 0
    assert "0 failed (errors)" in result.output
    assert "Data-quality checks passed" in result.output
