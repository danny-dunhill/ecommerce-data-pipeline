import pytest

from ecom_pipeline.extract import ExtractError, count_records, read_header, validate_sources
from ecom_pipeline.tables import TABLES
from sample_data import DATASET_ROW_COUNTS, write_csv, write_dataset


def test_read_header_returns_column_names_without_quotes(tmp_path):
    path = tmp_path / "file.csv"
    path.write_text('"a","b","c"\n"1","2","3"\n', encoding="utf-8")

    assert read_header(path) == ["a", "b", "c"]


def test_read_header_ignores_byte_order_mark(tmp_path):
    path = tmp_path / "file.csv"
    path.write_bytes(b"\xef\xbb\xbfa,b\n1,2\n")

    assert read_header(path) == ["a", "b"]


def test_count_records_skips_header_and_counts_multiline_field_once(tmp_path):
    path = tmp_path / "file.csv"
    write_csv(path, ["id", "text"], [["1", "one line"], ["2", "two\nlines"], ["3", "x"]])

    assert count_records(path) == 3  # the file has 5 physical lines, but 3 records


def test_validate_sources_accepts_a_complete_folder(tmp_path):
    write_dataset(tmp_path)

    sources = validate_sources(tmp_path)

    assert set(sources) == set(DATASET_ROW_COUNTS)
    assert all(path.is_file() for path in sources.values())


def test_validate_sources_reports_missing_files(tmp_path):
    write_dataset(tmp_path)
    (tmp_path / "olist_orders_dataset.csv").unlink()

    with pytest.raises(ExtractError) as exc_info:
        validate_sources(tmp_path)

    message = str(exc_info.value)
    assert "orders" in message
    assert "file not found" in message


def test_validate_sources_rejects_unexpected_columns(tmp_path):
    write_dataset(tmp_path)
    write_csv(
        tmp_path / "olist_sellers_dataset.csv", ["seller_id", "something_else"], [["s1", "x"]]
    )

    with pytest.raises(ExtractError) as exc_info:
        validate_sources(tmp_path)

    message = str(exc_info.value)
    assert "sellers" in message
    assert "unexpected columns" in message
    assert "something_else" in message


def test_validate_sources_rejects_files_that_are_not_utf8(tmp_path):
    write_dataset(tmp_path)
    (tmp_path / "olist_sellers_dataset.csv").write_bytes(b"\xff\xfe\x00\x01 not text")

    with pytest.raises(ExtractError, match="UTF-8"):
        validate_sources(tmp_path)


def test_validate_sources_reports_all_problems_at_once(tmp_path):
    write_dataset(tmp_path)
    (tmp_path / "olist_orders_dataset.csv").unlink()
    (tmp_path / "olist_customers_dataset.csv").unlink()

    with pytest.raises(ExtractError) as exc_info:
        validate_sources(tmp_path)

    message = str(exc_info.value)
    assert "orders" in message
    assert "customers" in message


def test_validate_sources_fails_for_an_empty_folder(tmp_path):
    with pytest.raises(ExtractError) as exc_info:
        validate_sources(tmp_path)

    # every one of the tables is reported as missing
    assert str(exc_info.value).count("file not found") == len(TABLES)
