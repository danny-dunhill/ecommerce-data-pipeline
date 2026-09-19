import pytest

from ecom_pipeline.config import ConfigError, get_settings

BASE_ENV = {
    "POSTGRES_USER": "ecom",
    "POSTGRES_PASSWORD": "secret",
    "POSTGRES_DB": "ecom_db",
}


def test_builds_url_from_postgres_variables():
    settings = get_settings(BASE_ENV)

    assert settings.database_url.drivername == "postgresql+psycopg"
    assert settings.database_url.username == "ecom"
    assert settings.database_url.password == "secret"
    assert settings.database_url.database == "ecom_db"
    assert settings.database_url.host == "localhost"  # default
    assert settings.database_url.port == 5432  # default


def test_custom_host_and_port_are_used():
    env = {**BASE_ENV, "POSTGRES_HOST": "db", "POSTGRES_PORT": "5433"}

    settings = get_settings(env)

    assert settings.database_url.host == "db"
    assert settings.database_url.port == 5433


def test_database_url_takes_precedence():
    env = {**BASE_ENV, "DATABASE_URL": "sqlite+pysqlite:///:memory:"}

    settings = get_settings(env)

    assert settings.database_url.drivername == "sqlite+pysqlite"


def test_missing_variables_are_reported_by_name():
    with pytest.raises(ConfigError) as exc_info:
        get_settings({"POSTGRES_USER": "ecom"})

    message = str(exc_info.value)
    assert "POSTGRES_PASSWORD" in message
    assert "POSTGRES_DB" in message
    assert "POSTGRES_USER" not in message


def test_invalid_port_raises():
    with pytest.raises(ConfigError, match="POSTGRES_PORT"):
        get_settings({**BASE_ENV, "POSTGRES_PORT": "not-a-number"})


def test_invalid_database_url_raises():
    with pytest.raises(ConfigError, match="DATABASE_URL"):
        get_settings({"DATABASE_URL": "this is not a url"})


def test_special_characters_in_password_are_escaped():
    settings = get_settings({**BASE_ENV, "POSTGRES_PASSWORD": "p@ss:w/rd"})

    rendered = settings.database_url.render_as_string(hide_password=False)

    assert settings.database_url.password == "p@ss:w/rd"
    assert "p@ss:w/rd" not in rendered  # must be percent-encoded inside the URL


def test_log_level_defaults_to_info_and_is_uppercased():
    assert get_settings(BASE_ENV).log_level == "INFO"
    assert get_settings({**BASE_ENV, "LOG_LEVEL": "debug"}).log_level == "DEBUG"
