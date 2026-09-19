"""Database helpers: engine creation and a connectivity check."""

from sqlalchemy import Engine, create_engine, text

from ecom_pipeline.config import Settings

CONNECT_TIMEOUT_SECONDS = 5


def get_engine(settings: Settings) -> Engine:
    """Create a SQLAlchemy engine.

    ``pool_pre_ping`` tests a connection before using it, so a database restart
    does not break a long-running pipeline with a stale connection. For PostgreSQL
    a connect timeout makes an unreachable database fail fast instead of hanging.
    """
    connect_args: dict[str, int] = {}
    if settings.database_url.get_backend_name() == "postgresql":
        connect_args["connect_timeout"] = CONNECT_TIMEOUT_SECONDS
    return create_engine(settings.database_url, pool_pre_ping=True, connect_args=connect_args)


def check_connection(engine: Engine) -> None:
    """Run a trivial query to prove the database is reachable.

    Raises:
        sqlalchemy.exc.SQLAlchemyError: if the connection or the query fails.
    """
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
