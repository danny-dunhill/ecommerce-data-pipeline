from sqlalchemy.engine import make_url

from ecom_pipeline import db
from ecom_pipeline.config import Settings


def capture_create_engine(monkeypatch):
    """Replace create_engine so we can see its arguments without opening a connection."""
    captured = {}

    def fake_create_engine(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return "fake-engine"

    monkeypatch.setattr(db, "create_engine", fake_create_engine)
    return captured


def test_postgres_engine_fails_fast_when_the_database_is_unreachable(monkeypatch):
    captured = capture_create_engine(monkeypatch)
    settings = Settings(database_url=make_url("postgresql+psycopg://user:pw@localhost/db"))

    assert db.get_engine(settings) == "fake-engine"

    assert captured["connect_args"] == {"connect_timeout": db.CONNECT_TIMEOUT_SECONDS}
    assert captured["pool_pre_ping"] is True


def test_sqlite_engine_gets_no_postgres_only_options(monkeypatch):
    captured = capture_create_engine(monkeypatch)
    settings = Settings(database_url=make_url("sqlite+pysqlite:///:memory:"))

    db.get_engine(settings)

    assert captured["connect_args"] == {}
