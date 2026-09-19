"""Data-quality checks on the cleaned tables.

Every check counts the rows that break one rule and returns a ``CheckResult``. Checks
never change the data and never raise: they *report*. What happens with the report is
decided by the caller.

Each check has a severity:

* ``ERROR``: the data would corrupt the star schema (duplicate keys, orders that point to
  a customer that does not exist, negative prices). The pipeline must not load it.
* ``WARNING``: the data is odd but loading it is safe (a delivery date before the
  purchase date, products without a category). It is reported, so that it can be
  investigated, but it does not stop the pipeline.

The rules are deliberately simple and readable. Add a rule by writing one small function
and adding it to ``_CHECKS``.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

import pandas as pd

from ecom_pipeline.transform import CleanData

KNOWN_ORDER_STATUSES = frozenset(
    {
        "created",
        "approved",
        "invoiced",
        "processing",
        "shipped",
        "delivered",
        "canceled",
        "unavailable",
    }
)


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class CheckResult:
    """The outcome of one check: how many of the checked rows broke the rule."""

    name: str
    severity: Severity
    description: str
    failed: int
    total: int

    @property
    def passed(self) -> bool:
        return self.failed == 0


Check = Callable[[CleanData], CheckResult]


def _count(mask: pd.Series) -> int:
    """Number of ``True`` values; a missing value (``<NA>``) counts as ``False``."""
    return int(mask.fillna(False).sum())


def _key_problems(frame: pd.DataFrame, columns: list[str]) -> int:
    """Rows with an empty key plus rows that repeat a key that already appeared."""
    keys = frame[columns]
    return _count(keys.isna().any(axis=1)) + int(keys.dropna().duplicated().sum())


# --- errors: the star schema cannot be built from such data ---------------------------------


def _customers_key(data: CleanData) -> CheckResult:
    return CheckResult(
        "customers_key",
        Severity.ERROR,
        "customer_id is present and unique",
        _key_problems(data.customers, ["customer_id"]),
        len(data.customers),
    )


def _products_key(data: CleanData) -> CheckResult:
    return CheckResult(
        "products_key",
        Severity.ERROR,
        "product_id is present and unique",
        _key_problems(data.products, ["product_id"]),
        len(data.products),
    )


def _orders_key(data: CleanData) -> CheckResult:
    return CheckResult(
        "orders_key",
        Severity.ERROR,
        "order_id is present and unique",
        _key_problems(data.orders, ["order_id"]),
        len(data.orders),
    )


def _order_items_key(data: CleanData) -> CheckResult:
    return CheckResult(
        "order_items_key",
        Severity.ERROR,
        "(order_id, order_item_id) is present and unique",
        _key_problems(data.order_items, ["order_id", "order_item_id"]),
        len(data.order_items),
    )


def _orders_customer_exists(data: CleanData) -> CheckResult:
    orphans = ~data.orders["customer_id"].isin(data.customers["customer_id"])
    return CheckResult(
        "orders_customer_exists",
        Severity.ERROR,
        "every order belongs to a known customer",
        _count(orphans),
        len(data.orders),
    )


def _items_order_exists(data: CleanData) -> CheckResult:
    orphans = ~data.order_items["order_id"].isin(data.orders["order_id"])
    return CheckResult(
        "items_order_exists",
        Severity.ERROR,
        "every order item belongs to a known order",
        _count(orphans),
        len(data.order_items),
    )


def _items_product_exists(data: CleanData) -> CheckResult:
    orphans = ~data.order_items["product_id"].isin(data.products["product_id"])
    return CheckResult(
        "items_product_exists",
        Severity.ERROR,
        "every order item refers to a known product",
        _count(orphans),
        len(data.order_items),
    )


def _orders_have_purchase_time(data: CleanData) -> CheckResult:
    return CheckResult(
        "orders_have_purchase_time",
        Severity.ERROR,
        "every order has a purchase timestamp",
        _count(data.orders["order_purchase_timestamp"].isna()),
        len(data.orders),
    )


def _orders_status_known(data: CleanData) -> CheckResult:
    unknown = ~data.orders["order_status"].isin(KNOWN_ORDER_STATUSES)
    return CheckResult(
        "orders_status_known",
        Severity.ERROR,
        "order_status is one of the known values",
        _count(unknown),
        len(data.orders),
    )


def _items_amounts_valid(data: CleanData) -> CheckResult:
    items = data.order_items
    invalid = (
        items["price"].isna()
        | items["freight_value"].isna()
        | (items["price"] < 0)
        | (items["freight_value"] < 0)
    )
    return CheckResult(
        "items_amounts_valid",
        Severity.ERROR,
        "price and freight_value are present and not negative",
        _count(invalid),
        len(items),
    )


def _payments_amount_valid(data: CleanData) -> CheckResult:
    values = data.order_payments["payment_value"]
    return CheckResult(
        "payments_amount_valid",
        Severity.ERROR,
        "payment_value is present and not negative",
        _count(values.isna() | (values < 0)),
        len(data.order_payments),
    )


# --- warnings: odd, but safe to load ------------------------------------------------------


def _delivery_after_purchase(data: CleanData) -> CheckResult:
    orders = data.orders
    too_early = orders["order_delivered_customer_date"] < orders["order_purchase_timestamp"]
    return CheckResult(
        "delivery_after_purchase",
        Severity.WARNING,
        "an order is not delivered before it was purchased",
        _count(too_early),
        len(orders),
    )


def _delivered_has_delivery_date(data: CleanData) -> CheckResult:
    orders = data.orders
    no_date = orders["order_delivered_customer_date"].isna()
    missing = (orders["order_status"] == "delivered") & no_date
    return CheckResult(
        "delivered_has_delivery_date",
        Severity.WARNING,
        "orders with status 'delivered' have a delivery date",
        _count(missing),
        len(orders),
    )


def _orders_have_items(data: CleanData) -> CheckResult:
    without_items = ~data.orders["order_id"].isin(data.order_items["order_id"])
    return CheckResult(
        "orders_have_items",
        Severity.WARNING,
        "every order has at least one item",
        _count(without_items),
        len(data.orders),
    )


def _products_have_category(data: CleanData) -> CheckResult:
    return CheckResult(
        "products_have_category",
        Severity.WARNING,
        "every product has a category",
        _count(data.products["category_name"].isna()),
        len(data.products),
    )


_CHECKS: tuple[Check, ...] = (
    _customers_key,
    _products_key,
    _orders_key,
    _order_items_key,
    _orders_customer_exists,
    _items_order_exists,
    _items_product_exists,
    _orders_have_purchase_time,
    _orders_status_known,
    _items_amounts_valid,
    _payments_amount_valid,
    _delivery_after_purchase,
    _delivered_has_delivery_date,
    _orders_have_items,
    _products_have_category,
)


_STATUS_LABELS = {Severity.ERROR: "FAIL", Severity.WARNING: "WARN"}


def run_checks(data: CleanData) -> list[CheckResult]:
    """Run every check and return all results (passed and failed), in a fixed order."""
    return [check(data) for check in _CHECKS]


def has_errors(results: list[CheckResult]) -> bool:
    """True if at least one ``ERROR`` check failed, i.e. the data must not be loaded."""
    return any(result.severity is Severity.ERROR and not result.passed for result in results)


def format_report(results: list[CheckResult]) -> str:
    """Render the results as a plain-text table (ASCII only, so any terminal can show it)."""
    width = max(len(result.name) for result in results)
    lines = []
    for result in results:
        status = _STATUS_LABELS[result.severity] if not result.passed else "OK"
        lines.append(
            f"[{status:<4}] {result.name:<{width}}  {result.failed:>7} of {result.total:<7} "
            f"{result.description}"
        )
    errors = sum(1 for r in results if r.severity is Severity.ERROR and not r.passed)
    warnings = sum(1 for r in results if r.severity is Severity.WARNING and not r.passed)
    lines.append(f"{len(results)} checks: {errors} failed (errors), {warnings} warnings")
    return "\n".join(lines)
