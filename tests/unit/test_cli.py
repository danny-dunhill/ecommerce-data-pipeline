import pytest
from sqlalchemy.exc import OperationalError
from typer.testing import CliRunner

from ecom_pipeline import __version__
from ecom_pipeline.cli import app
from ecom_pipeline.staging import LoadError
from sample_data import raw_frames, write_dataset

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

    for command in (
        "check-db",
        "load-staging",
        "validate",
        "load-warehouse",
        "run",
        "make-sample",
        "version",
    ):
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


def test_validate_prints_the_report_and_succeeds_for_valid_data(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setattr("ecom_pipeline.cli.read_staging", lambda engine, tables: raw_frames())

    result = runner.invoke(app, ["validate"])

    assert result.exit_code == 0
    assert "[OK  ] customers_key" in result.output
    assert "[WARN] delivered_has_delivery_date" in result.output  # a warning does not fail
    assert "Data-quality checks passed" in result.output


def test_validate_exits_with_code_3_when_a_blocking_check_fails(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    raw = raw_frames()
    raw["order_items"].loc[0, "price"] = "-5.00"
    monkeypatch.setattr("ecom_pipeline.cli.read_staging", lambda engine, tables: raw)

    result = runner.invoke(app, ["validate"])

    assert result.exit_code == 3
    assert "[FAIL] items_amounts_valid" in result.output


def test_validate_exits_with_code_3_when_a_value_has_the_wrong_type(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    raw = raw_frames()
    raw["order_items"].loc[0, "price"] = "twelve"
    monkeypatch.setattr("ecom_pipeline.cli.read_staging", lambda engine, tables: raw)

    result = runner.invoke(app, ["validate"])

    assert result.exit_code == 3
    assert "order_items.price" in result.output


def test_validate_exits_with_code_3_when_staging_was_not_loaded(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")

    def not_loaded(engine, tables):
        raise LoadError("Staging tables not found. Run `pipeline load-staging` first.")

    monkeypatch.setattr("ecom_pipeline.cli.read_staging", not_loaded)

    result = runner.invoke(app, ["validate"])

    assert result.exit_code == 3
    assert "load-staging" in result.output


def test_validate_exits_with_code_2_when_config_missing():
    result = runner.invoke(app, ["validate"])

    assert result.exit_code == 2
    assert "Missing required environment variables" in result.output


def patch_staging_data(monkeypatch, raw=None):
    """Make the commands read ``raw`` (default: valid data) instead of a real database."""
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setattr(
        "ecom_pipeline.cli.read_staging", lambda engine, tables: raw or raw_frames()
    )


def test_load_warehouse_loads_valid_data(monkeypatch):
    patch_staging_data(monkeypatch)
    loaded = []

    def fake_load(engine, clean):
        loaded.append(clean)
        return {"fact_orders": 4, "dim_date": 365}

    monkeypatch.setattr("ecom_pipeline.cli.load_warehouse", fake_load)

    result = runner.invoke(app, ["load-warehouse"])

    assert result.exit_code == 0
    assert len(loaded) == 1
    assert "Warehouse load finished: 2 tables, 369 rows processed (2 quality warnings)" in (
        result.output
    )


def test_load_warehouse_does_not_load_anything_when_a_blocking_check_fails(monkeypatch):
    raw = raw_frames()
    raw["order_items"].loc[0, "price"] = "-5.00"
    patch_staging_data(monkeypatch, raw)

    def must_not_be_called(engine, clean):
        raise AssertionError("the warehouse must not be loaded")

    monkeypatch.setattr("ecom_pipeline.cli.load_warehouse", must_not_be_called)

    result = runner.invoke(app, ["load-warehouse"])

    assert result.exit_code == 3
    assert "[FAIL] items_amounts_valid" in result.output
    assert "nothing was loaded" in result.output


def test_load_warehouse_exits_with_code_3_when_staging_was_not_loaded(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")

    def not_loaded(engine, tables):
        raise LoadError("Staging tables not found. Run `pipeline load-staging` first.")

    monkeypatch.setattr("ecom_pipeline.cli.read_staging", not_loaded)

    result = runner.invoke(app, ["load-warehouse"])

    assert result.exit_code == 3
    assert "load-staging" in result.output


def test_load_warehouse_exits_with_code_2_when_config_missing():
    result = runner.invoke(app, ["load-warehouse"])

    assert result.exit_code == 2


def test_run_loads_staging_then_the_warehouse(monkeypatch, tmp_path):
    patch_staging_data(monkeypatch)
    calls = []
    monkeypatch.setattr(
        "ecom_pipeline.cli.load_staging",
        lambda engine, data_dir: calls.append(("staging", data_dir)) or {"orders": 3},
    )
    monkeypatch.setattr(
        "ecom_pipeline.cli.load_warehouse",
        lambda engine, clean: calls.append(("warehouse", None)) or {"fact_orders": 4},
    )

    result = runner.invoke(app, ["run", "--data-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert calls == [("staging", tmp_path), ("warehouse", None)]


def test_run_stops_with_code_3_when_source_files_are_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    result = runner.invoke(app, ["run", "--data-dir", str(empty_dir)])

    assert result.exit_code == 3
    assert "file not found" in result.output
