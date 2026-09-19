from dataclasses import replace

import pandas as pd
import pytest

from ecom_pipeline.quality import (
    CheckResult,
    Severity,
    format_report,
    has_errors,
    run_checks,
)
from ecom_pipeline.transform import transform
from sample_data import raw_frames


@pytest.fixture
def clean():
    """Valid cleaned data (the shared fixture data)."""
    return transform(raw_frames())


def failed(data, name):
    """How many rows the check ``name`` reports as broken."""
    results = {result.name: result for result in run_checks(data)}
    return results[name].failed


def with_value(frame, row, column, value):
    """A copy of ``frame`` where one cell is changed."""
    changed = frame.copy()
    changed.loc[row, column] = value
    return changed


def test_valid_data_has_no_errors(clean):
    results = run_checks(clean)

    assert not has_errors(results)
    assert all(result.total > 0 for result in results)


def test_check_names_are_unique(clean):
    names = [result.name for result in run_checks(clean)]

    assert len(names) == len(set(names))


def test_known_oddities_of_the_fixture_data_are_reported_as_warnings(clean):
    # the fixture orders are "delivered" without a delivery date, and product p3 has no category
    assert failed(clean, "delivered_has_delivery_date") == 3
    assert failed(clean, "products_have_category") == 1


def test_duplicate_customer_id_is_an_error(clean):
    customers = with_value(clean.customers, 1, "customer_id", "c1")

    data = replace(clean, customers=customers)

    assert failed(data, "customers_key") == 1
    assert has_errors(run_checks(data))


def test_missing_order_id_is_an_error(clean):
    orders = with_value(clean.orders, 0, "order_id", pd.NA)

    assert failed(replace(clean, orders=orders), "orders_key") == 1


def test_duplicate_order_item_is_an_error(clean):
    items = with_value(clean.order_items, 1, "order_item_id", 1)  # o1 has item 1 twice now

    assert failed(replace(clean, order_items=items), "order_items_key") == 1


def test_order_with_unknown_customer_is_an_error(clean):
    orders = with_value(clean.orders, 0, "customer_id", "nobody")

    assert failed(replace(clean, orders=orders), "orders_customer_exists") == 1


def test_item_with_unknown_order_is_an_error(clean):
    items = with_value(clean.order_items, 0, "order_id", "ghost")

    assert failed(replace(clean, order_items=items), "items_order_exists") == 1


def test_item_with_unknown_product_is_an_error(clean):
    items = with_value(clean.order_items, 0, "product_id", "ghost")

    assert failed(replace(clean, order_items=items), "items_product_exists") == 1


def test_order_without_purchase_time_is_an_error(clean):
    orders = with_value(clean.orders, 0, "order_purchase_timestamp", pd.NaT)

    assert failed(replace(clean, orders=orders), "orders_have_purchase_time") == 1


def test_unknown_order_status_is_an_error(clean):
    orders = with_value(clean.orders, 0, "order_status", "teleported")

    assert failed(replace(clean, orders=orders), "orders_status_known") == 1


def test_negative_price_is_an_error(clean):
    items = with_value(clean.order_items, 0, "price", -1.0)

    assert failed(replace(clean, order_items=items), "items_amounts_valid") == 1


def test_missing_freight_is_an_error(clean):
    items = with_value(clean.order_items, 0, "freight_value", pd.NA)

    assert failed(replace(clean, order_items=items), "items_amounts_valid") == 1


def test_negative_payment_is_an_error(clean):
    payments = with_value(clean.order_payments, 0, "payment_value", -5.0)

    assert failed(replace(clean, order_payments=payments), "payments_amount_valid") == 1


def test_delivery_before_purchase_is_only_a_warning(clean):
    orders = with_value(
        clean.orders, 0, "order_delivered_customer_date", pd.Timestamp("2016-01-01")
    )
    data = replace(clean, orders=orders)

    assert failed(data, "delivery_after_purchase") == 1
    assert not has_errors(run_checks(data))


def test_order_without_items_is_only_a_warning(clean):
    items = clean.order_items[clean.order_items["order_id"] != "o3"]
    data = replace(clean, order_items=items)

    assert failed(data, "orders_have_items") == 1
    assert not has_errors(run_checks(data))


def test_has_errors_ignores_failed_warnings_and_passed_errors():
    warning = CheckResult("w", Severity.WARNING, "warning", failed=5, total=10)
    passed_error = CheckResult("e", Severity.ERROR, "error", failed=0, total=10)
    failed_error = CheckResult("f", Severity.ERROR, "error", failed=1, total=10)

    assert not has_errors([warning, passed_error])
    assert has_errors([warning, passed_error, failed_error])


def test_report_shows_status_counts_and_a_summary():
    results = [
        CheckResult("good_check", Severity.ERROR, "all fine", failed=0, total=10),
        CheckResult("bad_check", Severity.ERROR, "broken", failed=2, total=10),
        CheckResult("odd_check", Severity.WARNING, "odd", failed=3, total=10),
    ]

    report = format_report(results)

    assert "[OK  ] good_check" in report
    assert "[FAIL] bad_check" in report
    assert "[WARN] odd_check" in report
    assert "3 checks: 1 failed (errors), 1 warnings" in report
    assert report.isascii()  # safe for every Windows terminal encoding
