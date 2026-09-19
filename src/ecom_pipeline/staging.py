"""Load the raw CSV files 1:1 into the ``staging`` schema of PostgreSQL.

Staging is a disposable raw copy of the source: every column is ``TEXT`` and nothing is
cleaned or converted yet. That happens in the transform step. Keeping the raw copy means
we can always re-run the transformations without downloading the data again.

Design decisions:

* **PostgreSQL COPY** streams a whole file to the server in one command. It is far
  faster than inserting row by row, and it parses quoted fields that contain commas
  and line breaks (review comments) correctly.
* **Idempotent:** each table is dropped and re-created before loading, so running the
  load twice gives exactly the same result and never duplicates rows.
* **Atomic:** all tables are loaded in one transaction (PostgreSQL supports
  transactional DDL). If anything fails, the previous state stays untouched.
* **Reconciled:** after each load, the number of rows in the database must equal the
  number of records in the CSV file, otherwise the load fails and is rolled back.
"""

import logging
import time
from collections.abc import Sequence
from pathlib import Path

from psycopg import errors as psycopg_errors
from sqlalchemy import Connection, Engine, text

from ecom_pipeline.extract import count_records, validate_sources
from ecom_pipeline.tables import TABLES, TableSpec

logger = logging.getLogger(__name__)

STAGING_SCHEMA = "staging"
COPY_CHUNK_BYTES = 1024 * 1024  # stream files in 1 MiB pieces, never all in memory


class LoadError(RuntimeError):
    """Raised when the loaded data does not match the source files."""


def qualified_name(spec: TableSpec) -> str:
    """Return the schema-qualified table name, e.g. ``staging.orders``."""
    return f"{STAGING_SCHEMA}.{spec.name}"


def create_table_sql(spec: TableSpec) -> str:
    """Build the ``CREATE TABLE`` statement: all source columns as TEXT plus a load time."""
    columns = ",\n    ".join(f"{column} TEXT" for column in spec.columns)
    return (
        f"CREATE TABLE {qualified_name(spec)} (\n"
        f"    {columns},\n"
        f"    _loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()\n"
        f")"
    )


def copy_sql(spec: TableSpec) -> str:
    """Build the ``COPY`` statement that receives one CSV file from the client.

    ``FORCE_NULL`` turns an empty quoted value ("") into NULL, so that missing values
    look the same no matter how the CSV file was quoted.
    """
    columns = ", ".join(spec.columns)
    return (
        f"COPY {qualified_name(spec)} ({columns}) FROM STDIN "
        f"WITH (FORMAT csv, HEADER true, FORCE_NULL ({columns}))"
    )


def load_staging(
    engine: Engine, data_dir: Path, tables: Sequence[TableSpec] = TABLES
) -> dict[str, int]:
    """Reload all staging tables from the CSV files in ``data_dir``.

    Returns:
        Mapping of staging table name to the number of rows loaded.

    Raises:
        ExtractError: if the source files are missing or have unexpected columns.
        LoadError: if PostgreSQL rejects a file, or a table's row count does not match
            its CSV file.
        sqlalchemy.exc.SQLAlchemyError, psycopg.Error: on other database problems.
    """
    sources = validate_sources(data_dir, tables)  # fail fast, before touching the database

    row_counts: dict[str, int] = {}
    with engine.begin() as connection:  # one transaction: everything or nothing
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {STAGING_SCHEMA}"))
        for spec in tables:
            row_counts[spec.name] = _reload_table(connection, spec, sources[spec.name])
    return row_counts


def _reload_table(connection: Connection, spec: TableSpec, csv_path: Path) -> int:
    started = time.perf_counter()
    table = qualified_name(spec)
    expected = count_records(csv_path)

    connection.execute(text(f"DROP TABLE IF EXISTS {table}"))
    connection.execute(text(create_table_sql(spec)))

    # COPY is not available through SQLAlchemy itself, so we use the underlying
    # psycopg connection. It is the same connection, hence the same transaction.
    try:
        with (
            connection.connection.cursor() as cursor,
            cursor.copy(copy_sql(spec)) as copy,
            csv_path.open("rb") as source,
        ):
            while chunk := source.read(COPY_CHUNK_BYTES):
                copy.write(chunk)
    except psycopg_errors.DataError as exc:  # e.g. a row with too many columns
        raise LoadError(f"{table}: PostgreSQL rejected {csv_path.name}: {exc}") from exc

    loaded = connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
    if loaded != expected:
        raise LoadError(
            f"{table}: the CSV file has {expected} records but {loaded} rows were loaded"
        )

    logger.info("Loaded %-30s %8d rows in %.1fs", table, loaded, time.perf_counter() - started)
    return loaded
