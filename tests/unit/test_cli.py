import pytest
from sqlalchemy.exc import OperationalError
from typer.testing import CliRunner

from ecom_pipeline import __version__
from ecom_pipeline.cli import app
from sample_data import write_dataset

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

    for command in ("check-db", "load-staging", "make-sample", "version"):
        assert command in result.output


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

    def failing_check(engine):
        raise OperationalError("SELECT 1", None, Exception("connection refused"))

    # simulate an unreachable database without waiting for a real network timeout
    monkeypatch.setattr("ecom_pipeline.cli.check_connection", failing_check)

    result = runner.invoke(app, ["check-db"])

    assert result.exit_code == 1
    assert "Cannot connect" in result.output
    assert "super-secret-value" not in result.output


def test_load_staging_exits_with_code_3_when_source_files_are_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    result = runner.invoke(app, ["load-staging", "--data-dir", str(empty_dir)])

    assert result.exit_code == 3
    assert "file not found" in result.output


def test_load_staging_exits_with_code_2_when_data_dir_does_not_exist(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")

    result = runner.invoke(app, ["load-staging", "--data-dir", str(tmp_path / "nope")])

    assert result.exit_code == 2


def test_load_staging_exits_with_code_2_when_config_missing(tmp_path):
    result = runner.invoke(app, ["load-staging", "--data-dir", str(tmp_path)])

    assert result.exit_code == 2
    assert "Missing required environment variables" in result.output


def test_make_sample_writes_the_sample_files(tmp_path):
    source, target = tmp_path / "source", tmp_path / "sample"
    write_dataset(source)

    result = runner.invoke(
        app,
        ["make-sample", "--source-dir", str(source), "--target-dir", str(target), "-n", "2"],
    )

    assert result.exit_code == 0
    assert (target / "olist_orders_dataset.csv").is_file()


def test_make_sample_refuses_to_overwrite_its_own_source(tmp_path):
    source = tmp_path / "source"
    write_dataset(source)

    result = runner.invoke(
        app, ["make-sample", "--source-dir", str(source), "--target-dir", str(source)]
    )

    assert result.exit_code == 2
    assert "differ" in result.output


def test_make_sample_exits_with_code_3_when_source_files_are_missing(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()

    result = runner.invoke(
        app, ["make-sample", "--source-dir", str(empty), "--target-dir", str(tmp_path / "out")]
    )

    assert result.exit_code == 3
