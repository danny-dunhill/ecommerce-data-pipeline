"""Application settings, loaded from environment variables.

Nothing secret is ever hard-coded: credentials come from the environment
(or from a local ``.env`` file that is git-ignored).
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

REQUIRED_DB_VARS = ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    """Immutable, validated application settings."""

    database_url: URL
    log_level: str = "INFO"


def get_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build :class:`Settings` from environment variables.

    ``DATABASE_URL`` wins if it is set. Otherwise the URL is assembled from
    ``POSTGRES_USER``, ``POSTGRES_PASSWORD``, ``POSTGRES_DB`` and the optional
    ``POSTGRES_HOST`` (default ``localhost``) and ``POSTGRES_PORT`` (default ``5432``).

    Args:
        env: Mapping to read from. Defaults to ``os.environ``; passing a plain
            dict makes this function trivial to test.

    Raises:
        ConfigError: if required variables are missing or malformed.
    """
    env = os.environ if env is None else env
    log_level = env.get("LOG_LEVEL", "INFO").upper()

    raw_url = env.get("DATABASE_URL")
    if raw_url:
        try:
            return Settings(database_url=make_url(raw_url), log_level=log_level)
        except ArgumentError as exc:
            raise ConfigError("DATABASE_URL is not a valid database URL.") from exc

    missing = [name for name in REQUIRED_DB_VARS if not env.get(name)]
    if missing:
        raise ConfigError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Copy .env.example to .env, or set DATABASE_URL."
        )

    try:
        port = int(env.get("POSTGRES_PORT", "5432"))
    except ValueError as exc:
        raise ConfigError("POSTGRES_PORT must be an integer.") from exc

    # URL.create escapes special characters in the password for us.
    url = URL.create(
        drivername="postgresql+psycopg",
        username=env["POSTGRES_USER"],
        password=env["POSTGRES_PASSWORD"],
        host=env.get("POSTGRES_HOST", "localhost"),
        port=port,
        database=env["POSTGRES_DB"],
    )
    return Settings(database_url=url, log_level=log_level)
