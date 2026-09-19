"""Build a small, self-consistent sample of the dataset for tests, CI and demos.

The full dataset is too big for a Git repository and is not redistributed here. A sample
of a few hundred kilobytes is enough to run the whole pipeline end to end.

"Self-consistent" means that every related row is kept: for each sampled order we keep
its customer, items, payments and reviews, and for those items the products and sellers.
Without that, joins in later steps would silently lose rows.
"""

import csv
import logging
import random
from pathlib import Path

from ecom_pipeline.extract import validate_sources
from ecom_pipeline.tables import TABLES

logger = logging.getLogger(__name__)


def _column_values(path: Path, column: str) -> list[str]:
    """Return all values of one column of a CSV file."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [row[column] for row in csv.DictReader(handle)]


def _write_filtered(source: Path, target: Path, column: str | None, keep: set[str] | None) -> int:
    """Copy the rows of ``source`` to ``target`` whose ``column`` value is in ``keep``.

    With ``keep=None`` every row is copied. Returns the number of data rows written.
    """
    with (
        source.open(encoding="utf-8-sig", newline="") as source_handle,
        target.open("w", encoding="utf-8", newline="") as target_handle,
    ):
        reader = csv.reader(source_handle)
        writer = csv.writer(target_handle, lineterminator="\n")
        header = next(reader)
        writer.writerow(header)
        index = header.index(column) if column is not None else None

        written = 0
        for row in reader:
            if keep is None or index is None or row[index] in keep:
                writer.writerow(row)
                written += 1
    return written


def make_sample(
    source_dir: Path, target_dir: Path, n_orders: int = 1000, seed: int = 42
) -> dict[str, int]:
    """Write a consistent sample of ``n_orders`` random orders to ``target_dir``.

    The sample files keep the original file names, so the sample folder can be used
    exactly like the full data folder. The same ``seed`` always gives the same sample.

    Returns:
        Mapping of staging table name to the number of rows written.

    Raises:
        ValueError: on invalid arguments (for example source and target are the same).
        ExtractError: if the source files are missing or have unexpected columns.
    """
    if n_orders < 1:
        raise ValueError("n_orders must be at least 1")
    if source_dir.resolve() == target_dir.resolve():
        raise ValueError("The target folder must differ from the source folder")

    sources = validate_sources(source_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = {spec.name: target_dir / spec.csv_file for spec in TABLES}

    order_ids = _column_values(sources["orders"], "order_id")
    chosen_orders = set(random.Random(seed).sample(order_ids, min(n_orders, len(order_ids))))

    counts: dict[str, int] = {}
    # 1. the orders themselves, and everything that hangs directly on an order id
    for name in ("orders", "order_items", "order_payments", "order_reviews"):
        counts[name] = _write_filtered(sources[name], target[name], "order_id", chosen_orders)

    # 2. the customers of those orders
    customer_ids = set(_column_values(target["orders"], "customer_id"))
    counts["customers"] = _write_filtered(
        sources["customers"], target["customers"], "customer_id", customer_ids
    )

    # 3. the products and sellers that appear in the sampled items
    product_ids = set(_column_values(target["order_items"], "product_id"))
    seller_ids = set(_column_values(target["order_items"], "seller_id"))
    counts["products"] = _write_filtered(
        sources["products"], target["products"], "product_id", product_ids
    )
    counts["sellers"] = _write_filtered(
        sources["sellers"], target["sellers"], "seller_id", seller_ids
    )

    # 4. the small category translation table is copied completely
    counts["product_category_translation"] = _write_filtered(
        sources["product_category_translation"],
        target["product_category_translation"],
        None,
        None,
    )

    for name, rows in counts.items():
        logger.info("Sample %-30s %6d rows", name, rows)
    return counts
