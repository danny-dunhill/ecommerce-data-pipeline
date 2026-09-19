"""Command-line interface (``pipeline ...``).

Exit codes, so that schedulers and CI can tell what happened:

* 0: success
* 1: database problem (unreachable, query failed)
* 2: bad configuration or bad command-line arguments
* 3: problem with the data (missing files, unexpected columns, row count mismatch,
  failed data-quality checks)
"""

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import psycopg
import typer
from dotenv import find_dotenv, load_dotenv
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from ecom_pipeline import __version__
from ecom_pipeline.config import ConfigError, Settings, get_settings
from ecom_pipeline.db import check_connection, get_engine
from ecom_pipeline.extract import ExtractError
from ecom_pipeline.logging_setup import configure_logging
from ecom_pipeline.quality import (
    CheckResult,
    Severity,
    format_report,
    has_errors,
    run_checks,
)
from ecom_pipeline.reports import REPORTS, fetch_report, format_table
from ecom_pipeline.sample import make_sample
from ecom_pipeline.staging import LoadError, load_staging, read_staging
from ecom_pipeline.tables import TABLES
from ecom_pipeline.transform import INPUT_TABLES, CleanData, TransformError, transform
from ecom_pipeline.warehouse import load_warehouse

logger = logging.getLogger(__name__)

app = typer.Typer(
    help="E-commerce data pipeline: raw CSV -> PostgreSQL star schema.",
    no_args_is_help=True,
    add_completion=False,
)


def _load_settings_or_exit() -> Settings:
    """Read the settings, or stop the command with exit code 2 and a clear message."""
    try:
        return get_settings()
    except ConfigError as exc:
        logger.error("%s", exc)
        raise typer.Exit(code=2) from exc


class ReportName(StrEnum):
    """The reports of ``pipeline report`` (must match the keys of ``reports.REPORTS``)."""

    MONTHLY_REVENUE = "monthly-revenue"
    TOP_PRODUCTS = "top-products"
    REPEAT_CUSTOMERS = "repeat-customers"


def _reason(exc: Exception) -> str:
    """Why a database call failed: the first line of the driver's message.

    SQLAlchemy wraps the driver error in ``exc.orig`` and adds the SQL text and parameters
    to its own message, so only the driver's first line is shown. For a failed login that is
    e.g. ``password authentication failed for user "ecom"`` (libpq never echoes the password).
    """
    lines = str(getattr(exc, "orig", None) or exc).strip().splitlines()
    return lines[0] if lines else type(exc).__name__


@contextmanager
def _database(action: str) -> Iterator[Engine]:
    """Give a command an engine, and turn known failures into exit codes.

    Data problems (bad files, failed checks) exit with 3, database problems with 1.
    The engine is always closed at the end.
    """
    engine = get_engine(_load_settings_or_exit())
    try:
        yield engine
    except (ExtractError, LoadError, TransformError) as exc:
        logger.error("%s", exc)
        raise typer.Exit(code=3) from exc
    except (SQLAlchemyError, psycopg.Error) as exc:
        logger.error("Database error while %s: %s", action, _reason(exc))
        logger.debug("Full error", exc_info=True)
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()


def _warning_count(results: list[CheckResult]) -> int:
    return sum(1 for r in results if r.severity is Severity.WARNING and not r.passed)


def _read_clean_data(engine: Engine) -> tuple[CleanData, list[CheckResult]]:
    """Read staging, clean it and run the checks. Prints the report."""
    raw = read_staging(engine, [spec for spec in TABLES if spec.name in INPUT_TABLES])
    clean = transform(raw)
    results = run_checks(clean)
    typer.echo(format_report(results))
    return clean, results


def _load_validated_warehouse(engine: Engine) -> None:
    """Load the warehouse, but only if there is no failed blocking check."""
    clean, results = _read_clean_data(engine)
    if has_errors(results):
        logger.error("Data-quality checks failed: nothing was loaded into the warehouse")
        raise typer.Exit(code=3)
    row_counts = load_warehouse(engine, clean)
    logger.info(
        "Warehouse load finished: %d tables, %d rows processed (%d quality warnings)",
        len(row_counts),
        sum(row_counts.values()),
        _warning_count(results),
    )


@app.callback()
def main(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging."),
) -> None:
    """Runs before every command: load `.env` (if present) and set up logging."""
    load_dotenv(find_dotenv(usecwd=True))  # real environment variables always win
    configure_logging("DEBUG" if verbose else os.environ.get("LOG_LEVEL", "INFO"))


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(f"ecom-pipeline {__version__}")


@app.command("check-db")
def check_db() -> None:
    """Check that the configured database is reachable."""
    settings = _load_settings_or_exit()

    target = settings.database_url.render_as_string(hide_password=True)
    engine = get_engine(settings)
    try:
        check_connection(engine)
    except SQLAlchemyError as exc:
        logger.error("Cannot connect to %s: %s", target, _reason(exc))
        logger.debug("Full error", exc_info=True)
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()

    logger.info("Database connection OK: %s", target)


@app.command("load-staging")
def load_staging_command(
    data_dir: Path = typer.Option(
        Path("data/raw"),
        "--data-dir",
        "-d",
        exists=True,
        file_okay=False,
        readable=True,
        help="Folder with the Olist CSV files (use data/sample for the small sample).",
    ),
) -> None:
    """Load the raw CSV files into the PostgreSQL `staging` schema (safe to re-run)."""
    with _database("loading staging") as engine:
        row_counts = load_staging(engine, data_dir)

    logger.info(
        "Staging load finished: %d tables, %d rows in total",
        len(row_counts),
        sum(row_counts.values()),
    )


@app.command()
def validate() -> None:
    """Clean the staging data and run the data-quality checks (nothing is written).

    Exit code 3 if a blocking check fails. Warnings are shown but do not fail the command.
    """
    with _database("reading staging") as engine:
        _, results = _read_clean_data(engine)

    if has_errors(results):
        logger.error("Data-quality checks failed: the data must not be loaded")
        raise typer.Exit(code=3)
    logger.info("Data-quality checks passed (%d warnings)", _warning_count(results))


@app.command("load-warehouse")
def load_warehouse_command() -> None:
    """Load the star schema from the staging tables (validates first, safe to re-run)."""
    with _database("loading the warehouse") as engine:
        _load_validated_warehouse(engine)


@app.command()
def run(
    data_dir: Path = typer.Option(
        Path("data/raw"),
        "--data-dir",
        "-d",
        exists=True,
        file_okay=False,
        readable=True,
        help="Folder with the Olist CSV files (use data/sample for the small sample).",
    ),
) -> None:
    """Run the whole pipeline: CSV files -> staging -> validation -> star schema."""
    with _database("running the pipeline") as engine:
        load_staging(engine, data_dir)
        _load_validated_warehouse(engine)


@app.command()
def report(
    name: Annotated[ReportName, typer.Argument(help="Which report to print.")],
    limit: Annotated[
        int,
        typer.Option(
            "--limit",
            "-n",
            min=1,
            help="Maximum number of rows to print (monthly-revenue: the latest months).",
        ),
    ] = 20,
) -> None:
    """Print an analytical report from the `analytics` views (load the warehouse first)."""
    selected = REPORTS[name.value]
    with _database("reading the report") as engine:
        columns, rows = fetch_report(engine, selected, limit)

    typer.echo(f"{selected.description}\n")
    typer.echo(format_table(columns, rows))


@app.command("make-sample")
def make_sample_command(
    source_dir: Path = typer.Option(
        Path("data/raw"),
        "--source-dir",
        exists=True,
        file_okay=False,
        readable=True,
        help="Folder with the full Olist CSV files.",
    ),
    target_dir: Path = typer.Option(
        Path("data/sample"),
        "--target-dir",
        file_okay=False,
        help="Folder where the sample files are written.",
    ),
    orders: int = typer.Option(1000, "--orders", "-n", min=1, help="Number of orders to keep."),
    seed: int = typer.Option(
        42, "--seed", help="Random seed: the same seed gives the same sample."
    ),
) -> None:
    """Write a small, consistent sample of the dataset (for tests, CI and demos)."""
    try:
        make_sample(source_dir, target_dir, n_orders=orders, seed=seed)
    except ExtractError as exc:
        logger.error("%s", exc)
        raise typer.Exit(code=3) from exc
    except ValueError as exc:
        logger.error("%s", exc)
        raise typer.Exit(code=2) from exc

    logger.info("Sample written to %s", target_dir)
