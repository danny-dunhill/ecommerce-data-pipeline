"""Helpers that write tiny, valid Olist-shaped CSV files for the tests.

The rows are consistent with each other (every order has a customer, items, a payment
and a review), and they contain the awkward cases that real data has: empty values, and
a review comment with a comma, quotes and a line break inside one quoted field.
"""

import csv
from pathlib import Path

from ecom_pipeline.tables import TABLES

REVIEW_MESSAGE = 'Great product,\nvery "fast" delivery'

DATASET: dict[str, list[dict[str, str]]] = {
    "customers": [
        {
            "customer_id": f"c{i}",
            "customer_unique_id": f"u{i}",
            "customer_zip_code_prefix": "01000",
            "customer_city": "sao paulo",
            "customer_state": "SP",
        }
        for i in (1, 2, 3)
    ],
    "orders": [
        {
            "order_id": f"o{i}",
            "customer_id": f"c{i}",
            "order_status": "delivered",
            "order_purchase_timestamp": f"2017-01-0{i} 10:00:00",
            "order_approved_at": "" if i == 3 else f"2017-01-0{i} 11:00:00",
        }
        for i in (1, 2, 3)
    ],
    "order_items": [
        {
            "order_id": "o1",
            "order_item_id": "1",
            "product_id": "p1",
            "seller_id": "s1",
            "price": "10.00",
            "freight_value": "2.50",
        },
        {
            "order_id": "o1",
            "order_item_id": "2",
            "product_id": "p2",
            "seller_id": "s1",
            "price": "20.00",
            "freight_value": "2.50",
        },
        {
            "order_id": "o2",
            "order_item_id": "1",
            "product_id": "p2",
            "seller_id": "s2",
            "price": "20.00",
            "freight_value": "3.00",
        },
        {
            "order_id": "o3",
            "order_item_id": "1",
            "product_id": "p3",
            "seller_id": "s2",
            "price": "5.00",
            "freight_value": "1.00",
        },
    ],
    "order_payments": [
        {
            "order_id": f"o{i}",
            "payment_sequential": "1",
            "payment_type": "credit_card",
            "payment_installments": "1",
            "payment_value": "12.50",
        }
        for i in (1, 2, 3)
    ],
    "order_reviews": [
        {
            "review_id": "r1",
            "order_id": "o1",
            "review_score": "5",
            "review_comment_message": REVIEW_MESSAGE,
        },
        {"review_id": "r2", "order_id": "o2", "review_score": "3"},
        {
            "review_id": "r3",
            "order_id": "o3",
            "review_score": "1",
            "review_comment_title": "bad",
        },
    ],
    # p4 is never ordered and s3 never sells: a sample must not include them
    "products": [
        {
            "product_id": f"p{i}",
            "product_category_name": "" if i == 3 else "toys",
            "product_photos_qty": "1",
        }
        for i in (1, 2, 3, 4)
    ],
    "sellers": [
        {
            "seller_id": f"s{i}",
            "seller_zip_code_prefix": "02000",
            "seller_city": "rio",
            "seller_state": "RJ",
        }
        for i in (1, 2, 3)
    ],
    "product_category_translation": [
        {"product_category_name": "toys", "product_category_name_english": "toys"},
        {
            "product_category_name": "beleza_saude",
            "product_category_name_english": "health_beauty",
        },
    ],
}

# how many rows each table of DATASET has
DATASET_ROW_COUNTS = {name: len(rows) for name, rows in DATASET.items()}


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    """Write a CSV file in the same style as the source data: every field quoted."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_ALL, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def write_dataset(directory: Path) -> None:
    """Write all source CSV files of ``DATASET`` into ``directory``."""
    directory.mkdir(parents=True, exist_ok=True)
    for spec in TABLES:
        rows = [[row.get(column, "") for column in spec.columns] for row in DATASET[spec.name]]
        write_csv(directory / spec.csv_file, list(spec.columns), rows)


def read_rows(path: Path) -> list[dict[str, str]]:
    """Read a CSV file into a list of dictionaries."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))
