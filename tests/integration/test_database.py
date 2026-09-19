"""Integration tests: these talk to a real PostgreSQL (see conftest.py for the setup)."""

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


def test_connects_to_postgres(engine):
    assert engine.dialect.name == "postgresql"


def test_can_run_a_query(engine):
    with engine.connect() as connection:
        assert connection.execute(text("SELECT 1 + 1")).scalar_one() == 2
