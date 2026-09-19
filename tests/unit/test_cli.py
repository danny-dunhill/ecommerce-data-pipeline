import pytest
from typer.testing import CliRunner

from ecom_pipeline import __version__
from ecom_pipeline.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    """Make sure a developer's real .env or shell variables cannot leak into tests."""
    monkeypatch.chdir(tmp_path)  # no .env file here
    for name in (
        "DATABASE_URL",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
    ):
        monkeypatch.delenv(name, raising=False)


def test_no_arguments_shows_help():
    result = runner.invoke(app, [])

    assert "check-db" in result.output
    assert "version" in result.output


def test_version_command_prints_version():
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert __version__ in result.output


def test_check_db_succeeds_with_reachable_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")

    result = runner.invoke(app, ["check-db"])

    assert result.exit_code == 0
    assert "Database connection OK" in result.output


def test_check_db_fails_with_exit_code_1_when_database_unreachable(monkeypatch, tmp_path):
    missing_dir = tmp_path / "does-not-exist" / "db.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{missing_dir}")

    result = runner.invoke(app, ["check-db"])

    assert result.exit_code == 1
    assert "Cannot connect" in result.output


def test_check_db_fails_with_exit_code_2_when_config_missing():
    result = runner.invoke(app, ["check-db"])

    assert result.exit_code == 2
    assert "Missing required environment variables" in result.output


def test_password_is_never_logged(monkeypatch):
    monkeypatch.setenv("POSTGRES_USER", "ecom")
    monkeypatch.setenv("POSTGRES_PASSWORD", "super-secret-value")
    monkeypatch.setenv("POSTGRES_DB", "ecom_db")
    monkeypatch.setenv("POSTGRES_PORT", "1")  # nothing listens here -> connection fails

    result = runner.invoke(app, ["check-db"])

    assert result.exit_code == 1
    assert "super-secret-value" not in result.output
