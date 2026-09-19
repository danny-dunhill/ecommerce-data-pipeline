import pytest

from ecom_pipeline.extract import ExtractError, validate_sources
from ecom_pipeline.sample import make_sample
from sample_data import DATASET_ROW_COUNTS, REVIEW_MESSAGE, read_rows, write_dataset


@pytest.fixture
def source_dir(tmp_path):
    directory = tmp_path / "source"
    write_dataset(directory)
    return directory


def ids(directory, file_name, column):
    return {row[column] for row in read_rows(directory / file_name)}


def test_sample_keeps_the_requested_number_of_orders(source_dir, tmp_path):
    counts = make_sample(source_dir, tmp_path / "sample", n_orders=2)

    assert counts["orders"] == 2
    assert len(read_rows(tmp_path / "sample" / "olist_orders_dataset.csv")) == 2


def test_sample_is_consistent_across_tables(source_dir, tmp_path):
    sample = tmp_path / "sample"
    make_sample(source_dir, sample, n_orders=2)

    orders = ids(sample, "olist_orders_dataset.csv", "order_id")
    items = read_rows(sample / "olist_order_items_dataset.csv")

    # everything that belongs to an order refers to a sampled order
    for file_name in (
        "olist_order_items_dataset.csv",
        "olist_order_payments_dataset.csv",
        "olist_order_reviews_dataset.csv",
    ):
        assert ids(sample, file_name, "order_id") <= orders
    # each sampled order keeps all of its rows
    assert ids(sample, "olist_order_payments_dataset.csv", "order_id") == orders
    # customers, products and sellers are exactly the ones that are referenced
    assert ids(sample, "olist_customers_dataset.csv", "customer_id") == ids(
        sample, "olist_orders_dataset.csv", "customer_id"
    )
    assert ids(sample, "olist_products_dataset.csv", "product_id") == {
        i["product_id"] for i in items
    }
    assert ids(sample, "olist_sellers_dataset.csv", "seller_id") == {i["seller_id"] for i in items}


def test_sample_with_more_orders_than_available_keeps_everything(source_dir, tmp_path):
    counts = make_sample(source_dir, tmp_path / "sample", n_orders=100)

    assert counts["orders"] == DATASET_ROW_COUNTS["orders"]
    assert counts["order_items"] == DATASET_ROW_COUNTS["order_items"]
    # p4 and s3 are never ordered, so they are not part of the sample
    assert counts["products"] == DATASET_ROW_COUNTS["products"] - 1
    assert counts["sellers"] == DATASET_ROW_COUNTS["sellers"] - 1


def test_same_seed_gives_the_same_sample(source_dir, tmp_path):
    make_sample(source_dir, tmp_path / "a", n_orders=2, seed=7)
    make_sample(source_dir, tmp_path / "b", n_orders=2, seed=7)

    file_name = "olist_orders_dataset.csv"
    assert (tmp_path / "a" / file_name).read_bytes() == (tmp_path / "b" / file_name).read_bytes()


def test_translation_table_is_copied_completely(source_dir, tmp_path):
    counts = make_sample(source_dir, tmp_path / "sample", n_orders=1)

    assert (
        counts["product_category_translation"] == DATASET_ROW_COUNTS["product_category_translation"]
    )


def test_multiline_review_comment_survives_the_round_trip(source_dir, tmp_path):
    make_sample(source_dir, tmp_path / "sample", n_orders=100)

    reviews = read_rows(tmp_path / "sample" / "olist_order_reviews_dataset.csv")

    assert REVIEW_MESSAGE in {row["review_comment_message"] for row in reviews}


def test_sample_folder_can_be_used_like_the_full_data_folder(source_dir, tmp_path):
    make_sample(source_dir, tmp_path / "sample", n_orders=2)

    assert validate_sources(tmp_path / "sample")  # all files present, columns unchanged


def test_source_and_target_must_differ(source_dir):
    with pytest.raises(ValueError, match="differ"):
        make_sample(source_dir, source_dir)


def test_at_least_one_order_is_required(source_dir, tmp_path):
    with pytest.raises(ValueError, match="at least 1"):
        make_sample(source_dir, tmp_path / "sample", n_orders=0)


def test_missing_source_files_raise_extract_error(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()

    with pytest.raises(ExtractError):
        make_sample(empty, tmp_path / "sample")
