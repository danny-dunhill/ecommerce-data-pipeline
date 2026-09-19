from ecom_pipeline.staging import copy_sql, create_table_sql, qualified_name
from ecom_pipeline.tables import TABLES


def test_qualified_name_uses_the_staging_schema():
    orders = next(spec for spec in TABLES if spec.name == "orders")

    assert qualified_name(orders) == "staging.orders"


def test_create_table_makes_every_source_column_text_and_adds_load_time():
    for spec in TABLES:
        sql = create_table_sql(spec)

        assert sql.startswith(f"CREATE TABLE staging.{spec.name} (")
        for column in spec.columns:
            assert f"{column} TEXT" in sql
        assert "_loaded_at TIMESTAMPTZ NOT NULL DEFAULT now()" in sql


def test_copy_lists_all_columns_in_order_and_forces_nulls():
    for spec in TABLES:
        sql = copy_sql(spec)
        columns = ", ".join(spec.columns)

        assert sql.startswith(f"COPY staging.{spec.name} ({columns}) FROM STDIN")
        assert "FORMAT csv" in sql
        assert "HEADER true" in sql
        assert f"FORCE_NULL ({columns})" in sql
