"""Command-line interface (``pipeline ...``)."""

import logging
import os

import typer
from dotenv import find_dotenv, load_dotenv
from sqlalchemy.exc import SQLAlchemyError

from ecom_pipeline import __version__
from ecom_pipeline.config import ConfigError, get_settings
from ecom_pipeline.db import check_connection, get_engine
from ecom_pipeline.logging_setup import configure_logging

logger = logging.getLogger(__name__)

app = typer.Typer(
    help="E-commerce data pipeline: raw CSV -> PostgreSQL star schema.",
    no_args_is_help=True,
    add_completion=False,
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
    try:
        settings = get_settings()
    except ConfigError as exc:
        logger.error("%s", exc)
        raise typer.Exit(code=2) from exc

    target = settings.database_url.render_as_string(hide_password=True)
    engine = get_engine(settings)
    try:
        check_connection(engine)
    except SQLAlchemyError as exc:
        logger.error("Cannot connect to %s (%s)", target, type(exc).__name__)
        logger.debug("Full error", exc_info=True)
        raise typer.Exit(code=1) from exc
    finally:
        engine.dispose()

    logger.info("Database connection OK: %s", target)
