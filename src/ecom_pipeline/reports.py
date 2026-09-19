"""Print the analytical views as text tables (``pipeline report ...``).

The views themselves are defined in SQL (``sql/analytics_views.sql``). This module only
asks them a fixed question and formats the answer, so the numbers always come from one
place: the database.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import Engine, text

from ecom_pipeline.staging import LoadError


@dataclass(frozen=True)
class Report:
    """One report: the view it reads and the query that shapes the output."""

    name: str  # the name used on the command line
    view: str  # the view in the ``analytics`` schema
    sql: str  # the query; ``:limit`` is the maximum number of rows
    description: str


REPORTS: dict[str, Report] = {
    report.name: report
    for report in (
        Report(
            name="monthly-revenue",
            view="monthly_revenue",
            sql="SELECT * FROM analytics.monthly_revenue ORDER BY month_start LIMIT :limit",
            description="Revenue, orders and growth per month",
        ),
        Report(
            name="top-products",
            view="top_products",
            sql=(
                "SELECT revenue_rank, product_id, category, units_sold, orders, revenue "
                "FROM analytics.top_products ORDER BY revenue_rank, product_id LIMIT :limit"
            ),
            description="Best-selling products by revenue",
        ),
        Report(
            name="repeat-customers",
            view="repeat_customers",
            sql="SELECT * FROM analytics.repeat_customers LIMIT :limit",
            description="Share of customers who ordered more than once",
        ),
    )
}


def fetch_report(engine: Engine, report: Report, limit: int) -> tuple[list[str], list[tuple]]:
    """Run a report and return its column names and rows.

    Raises:
        LoadError: if the view does not exist yet (the warehouse was not loaded).
    """
    with engine.connect() as connection:
        view = f"analytics.{report.view}"
        exists = connection.execute(text("SELECT to_regclass(:view) IS NOT NULL"), {"view": view})
        if not exists.scalar_one():
            raise LoadError(
                f"The view {view} does not exist. "
                "Run `pipeline load-warehouse` (or `pipeline run`) first."
            )
        result = connection.execute(text(report.sql), {"limit": limit})
        return list(result.keys()), [tuple(row) for row in result]


def _format_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, Decimal):
        return f"{value:,.2f}"
    return str(value)


def format_table(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    """Render rows as an aligned text table. Numbers are right-aligned, text left-aligned."""
    cells = [[_format_value(value) for value in row] for row in rows]
    numeric = [
        all(isinstance(row[i], int | float | Decimal) for row in rows if row[i] is not None)
        and any(row[i] is not None for row in rows)
        for i in range(len(columns))
    ]
    widths = [
        max([len(column), *(len(row[i]) for row in cells)]) for i, column in enumerate(columns)
    ]

    def line(values: Sequence[str]) -> str:
        parts = [
            value.rjust(width) if numeric[i] else value.ljust(width)
            for i, (value, width) in enumerate(zip(values, widths, strict=True))
        ]
        return "  ".join(parts).rstrip()

    header = line(list(columns))
    separator = "  ".join("-" * width for width in widths)
    return "\n".join([header, separator, *(line(row) for row in cells)])
