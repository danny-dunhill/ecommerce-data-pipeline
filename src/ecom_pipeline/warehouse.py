"""Load the star schema into PostgreSQL (schema ``dw``) with upserts.

How one table is loaded:

1. The DataFrame is streamed with ``COPY`` into a **temporary table** that only lives
   inside the transaction. COPY is the fastest way to move many rows.
2. One ``INSERT ... ON CONFLICT DO UPDATE`` (an *upsert*) moves the rows from the
   temporary table into the real table: new rows are inserted, rows whose business key
   already exists are updated.

Design decisions:

* **Idempotent:** running the load again with the same data changes nothing. The
  ``WHERE ... IS DISTINCT FROM`` in the upsert skips rows that did not change, so they
  are not even rewritten. Surrogate keys stay stable between runs.
* **Atomic:** the schema, all dimensions and the fact table are loaded in one
  transaction. If anything fails, the warehouse stays exactly as it was.
* **Facts find their dimension rows by business key.** The fact rows carry ``customer_id``
  and ``product_id``, and the database swaps them for ``customer_key`` and
  ``product_key``. The number of rows that survive this lookup is checked, so no fact row
  can silently disappear.
* **Upsert only, no deletes.** A row that vanished from the source stays in the
  warehouse. Removing such rows would need a full refresh or soft deletes.
* Identity values are taken by every attempted insert, also when the row already exists,
  so the surrogate keys can have gaps. That is harmless: they only need to be unique.
"""

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import resources

import pandas as pd
from sqlalchemy import Connection, Engine, text

from ecom_pipeline.staging import LoadError
from ecom_pipeline.star import (
    DIM_CUSTOMERS_COLUMNS,
    DIM_DATE_COLUMNS,
    DIM_PRODUCTS_COLUMNS,
    FACT_ORDERS_COLUMNS,
    StarData,
    build_star,
)
from ecom_pipeline.transform import CleanData

logger = logging.getLogger(__name__)

WAREHOUSE_SCHEMA = "dw"
COPY_CHUNK_ROWS = 50_000  # send big tables in pieces, never as one huge text


@dataclass(frozen=True)
class Dimension:
    """A dimension table and how its rows are matched with the source."""

    name: str
    key: tuple[str, ...]  # the business key: what makes a row "the same row" between loads
    columns: tuple[str, ...]  # all columns that are loaded (surrogate keys are generated)


DIMENSIONS: tuple[Dimension, ...] = (
    Dimension("dim_date", ("date_key",), DIM_DATE_COLUMNS),
    Dimension("dim_customers", ("customer_id",), DIM_CUSTOMERS_COLUMNS),
    Dimension("dim_products", ("product_id",), DIM_PRODUCTS_COLUMNS),
)

FACT_TABLE = "fact_orders"
FACT_KEY = ("order_id", "order_item_id")
# Fact columns that the upsert may change (everything except the key)
FACT_VALUE_COLUMNS = (
    "customer_key",
    "product_key",
    "order_date_key",
    "seller_id",
    "order_status",
    "purchased_at",
    "delivered_at",
    "estimated_delivery_at",
    "price",
    "freight_value",
)


# --- SQL text (pure functions, tested without a database) ---------------------------------


def split_statements(script: str) -> list[str]:
    """Split a SQL script into single statements.

    Comment lines are removed and the script is split on semicolons, which is enough for
    plain DDL (no semicolons inside strings, no function bodies).
    """
    lines = [line for line in script.splitlines() if not line.strip().startswith("--")]
    return [statement.strip() for statement in "\n".join(lines).split(";") if statement.strip()]


def schema_statements() -> list[str]:
    """The statements of ``star_schema.sql`` (packaged next to this module)."""
    script = resources.files("ecom_pipeline").joinpath("sql/star_schema.sql").read_text("utf-8")
    return split_statements(script)


def _qualified(table: str) -> str:
    return f"{WAREHOUSE_SCHEMA}.{table}"


def _staging_table(table: str) -> str:
    return f"_load_{table}"


def _changed(target: str, columns: Sequence[str]) -> str:
    """SQL condition: at least one column differs (NULL-safe), so the row must be updated."""
    ours = ", ".join(f"{target}.{column}" for column in columns)
    theirs = ", ".join(f"EXCLUDED.{column}" for column in columns)
    return f"({ours}) IS DISTINCT FROM ({theirs})"


def create_load_table_sql(dimension: Dimension) -> str:
    """A temporary table with the same column types as the dimension, but no rows."""
    columns = ", ".join(dimension.columns)
    return (
        f"CREATE TEMP TABLE {_staging_table(dimension.name)} ON COMMIT DROP AS "
        f"SELECT {columns} FROM {_qualified(dimension.name)} WITH NO DATA"
    )


def upsert_dimension_sql(dimension: Dimension) -> str:
    """Insert new dimension rows and update the ones whose business key already exists."""
    columns = ", ".join(dimension.columns)
    key = ", ".join(dimension.key)
    value_columns = [column for column in dimension.columns if column not in dimension.key]
    assignments = ", ".join(f"{column} = EXCLUDED.{column}" for column in value_columns)
    return (
        f"INSERT INTO {_qualified(dimension.name)} AS target ({columns})\n"
        f"SELECT {columns} FROM {_staging_table(dimension.name)}\n"
        f"ON CONFLICT ({key}) DO UPDATE SET {assignments}\n"
        f"WHERE {_changed('target', value_columns)}"
    )


def create_fact_load_table_sql() -> str:
    """Temporary table for the fact rows (business ids instead of surrogate keys)."""
    return (
        f"CREATE TEMP TABLE {_staging_table(FACT_TABLE)} (\n"
        "    order_id TEXT, order_item_id INTEGER, customer_id TEXT, product_id TEXT,\n"
        "    order_date_key INTEGER, seller_id TEXT, order_status TEXT,\n"
        "    purchased_at TIMESTAMP, delivered_at TIMESTAMP, estimated_delivery_at TIMESTAMP,\n"
        "    price NUMERIC(12, 2), freight_value NUMERIC(12, 2)\n"
        ") ON COMMIT DROP"
    )


def _fact_lookup_sql(select: str) -> str:
    """``select`` over the loaded fact rows joined with their customer and product."""
    load_table = _staging_table(FACT_TABLE)
    return (
        f"{select}\n"
        f"FROM {load_table} AS l\n"
        f"JOIN {_qualified('dim_customers')} AS c ON c.customer_id = l.customer_id\n"
        f"JOIN {_qualified('dim_products')} AS p ON p.product_id = l.product_id"
    )


def count_resolvable_facts_sql() -> str:
    """How many loaded fact rows find both their customer and their product."""
    return _fact_lookup_sql("SELECT count(*)")


def upsert_fact_sql() -> str:
    """Insert new fact rows and update changed ones, swapping business ids for surrogate keys."""
    columns = ", ".join((*FACT_KEY, *FACT_VALUE_COLUMNS))
    select = (
        "SELECT l.order_id, l.order_item_id, c.customer_key, p.product_key, l.order_date_key,"
        " l.seller_id, l.order_status, l.purchased_at, l.delivered_at,"
        " l.estimated_delivery_at, l.price, l.freight_value"
    )
    assignments = ", ".join(f"{column} = EXCLUDED.{column}" for column in FACT_VALUE_COLUMNS)
    return (
        f"INSERT INTO {_qualified(FACT_TABLE)} AS target ({columns})\n"
        f"{_fact_lookup_sql(select)}\n"
        f"ON CONFLICT ({', '.join(FACT_KEY)}) DO UPDATE SET {assignments}\n"
        f"WHERE {_changed('target', FACT_VALUE_COLUMNS)}"
    )


# --- talking to the database --------------------------------------------------------------


def _copy_frame(connection: Connection, table: str, frame: pd.DataFrame) -> None:
    """Stream a DataFrame into ``table`` with COPY, in chunks of ``COPY_CHUNK_ROWS`` rows."""
    columns = ", ".join(frame.columns)
    copy_sql = f"COPY {table} ({columns}) FROM STDIN WITH (FORMAT csv)"
    with connection.connection.cursor() as cursor, cursor.copy(copy_sql) as copy:
        for start in range(0, len(frame), COPY_CHUNK_ROWS):
            chunk = frame.iloc[start : start + COPY_CHUNK_ROWS]
            # missing values are written as nothing, which COPY reads as NULL
            copy.write(chunk.to_csv(index=False, header=False, lineterminator="\n"))


def _load_dimension(connection: Connection, dimension: Dimension, frame: pd.DataFrame) -> int:
    started = time.perf_counter()
    connection.execute(text(create_load_table_sql(dimension)))
    _copy_frame(connection, _staging_table(dimension.name), frame)
    connection.execute(text(upsert_dimension_sql(dimension)))
    logger.info(
        "Loaded %-24s %8d rows in %.1fs",
        _qualified(dimension.name),
        len(frame),
        time.perf_counter() - started,
    )
    return len(frame)


def _load_facts(connection: Connection, frame: pd.DataFrame) -> int:
    started = time.perf_counter()
    connection.execute(text(create_fact_load_table_sql()))
    _copy_frame(connection, _staging_table(FACT_TABLE), frame[list(FACT_ORDERS_COLUMNS)])

    resolvable = connection.execute(text(count_resolvable_facts_sql())).scalar_one()
    if resolvable != len(frame):
        raise LoadError(
            f"{_qualified(FACT_TABLE)}: {len(frame) - resolvable} of {len(frame)} fact rows "
            "have no matching customer or product and would be lost"
        )

    connection.execute(text(upsert_fact_sql()))
    logger.info(
        "Loaded %-24s %8d rows in %.1fs",
        _qualified(FACT_TABLE),
        len(frame),
        time.perf_counter() - started,
    )
    return len(frame)


def load_star(engine: Engine, star: StarData) -> dict[str, int]:
    """Create the schema if needed and upsert all tables in one transaction.

    Returns:
        Mapping of warehouse table name to the number of rows that were processed.

    Raises:
        LoadError: if fact rows have no matching dimension row.
        sqlalchemy.exc.SQLAlchemyError, psycopg.Error: on database problems.
    """
    frames = {
        "dim_date": star.dim_date,
        "dim_customers": star.dim_customers,
        "dim_products": star.dim_products,
    }
    row_counts: dict[str, int] = {}
    with engine.begin() as connection:  # one transaction: everything or nothing
        for statement in schema_statements():
            connection.execute(text(statement))
        for dimension in DIMENSIONS:  # dimensions first: the facts look their rows up
            row_counts[dimension.name] = _load_dimension(
                connection, dimension, frames[dimension.name]
            )
        row_counts[FACT_TABLE] = _load_facts(connection, star.fact_orders)
    return row_counts


def load_warehouse(engine: Engine, clean: CleanData) -> dict[str, int]:
    """Build the star schema tables from the cleaned data and load them."""
    return load_star(engine, build_star(clean))
