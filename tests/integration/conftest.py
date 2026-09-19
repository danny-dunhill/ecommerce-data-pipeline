"""Fixtures shared by the integration tests (they need a real PostgreSQL).

Locally, start the database first with ``docker compose up -d --wait db`` (or ``make up``).
If PostgreSQL is not reachable the tests are skipped, not failed. In CI a PostgreSQL
service container is always available, so they run there.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ecom_pipeline.config import ConfigError, get_settings
from ecom_pipeline.db import check_connection, get_engine


@pytest.fixture
def engine():
    try:
        settings = get_settings()
    except ConfigError:
        pytest.skip("Database environment variables are not set")

    engine = get_engine(settings)
    try:
        check_connection(engine)
    except SQLAlchemyError:
        engine.dispose()
        pytest.skip("PostgreSQL is not reachable (start it with `make up`)")

    yield engine
    engine.dispose()


@pytest.fixture
def clean_staging(engine):
    """Start and finish each test with no ``staging`` schema, so tests cannot affect each other."""

    def drop_schema():
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA IF EXISTS staging CASCADE"))

    drop_schema()
    yield
    drop_schema()


@pytest.fixture
def clean_warehouse(engine):
    """Start and finish each test without the ``dw`` and ``analytics`` schemas."""

    def drop_schema():
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA IF EXISTS analytics CASCADE"))
            connection.execute(text("DROP SCHEMA IF EXISTS dw CASCADE"))

    drop_schema()
    yield
    drop_schema()
