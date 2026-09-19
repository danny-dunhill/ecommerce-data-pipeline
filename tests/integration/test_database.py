"""Integration tests: these talk to a real PostgreSQL.

Locally, start the database first with ``make up`` and export the variables from
``.env``. If PostgreSQL is not reachable the tests are skipped, not failed. In CI a
PostgreSQL service container is always available, so they run there.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ecom_pipeline.config import ConfigError, get_settings
from ecom_pipeline.db import check_connection, get_engine

pytestmark = pytest.mark.integration


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
        pytest.skip("PostgreSQL is not reachable (run `make up` first)")

    yield engine
    engine.dispose()


def test_connects_to_postgres(engine):
    assert engine.dialect.name == "postgresql"


def test_can_run_a_query(engine):
    with engine.connect() as connection:
        assert connection.execute(text("SELECT 1 + 1")).scalar_one() == 2
