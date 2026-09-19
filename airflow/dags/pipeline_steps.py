"""The steps of the daily pipeline run: one place that says *what* runs and in which order.

This file has no Airflow imports on purpose. The DAG (``ecommerce_pipeline.py``) turns every
``Step`` into one Airflow task, and the unit tests read the same list to prove that every
step is a real ``pipeline`` command, so the schedule can never drift away from the CLI.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Step:
    """One task of the DAG."""

    task_id: str
    # Arguments of the `pipeline` command. `{data_dir}` is filled in by the DAG.
    command: str
    # Tasks that must finish successfully before this one starts.
    upstream: tuple[str, ...] = ()
    # Extra attempts after a failure. Only steps where a second try can help get any: a
    # database that is still starting, or a load (which is idempotent and atomic).
    retries: int = 0


STEPS: tuple[Step, ...] = (
    Step("check_db", "check-db", retries=2),
    Step("load_staging", "load-staging --data-dir {data_dir}", ("check_db",), retries=1),
    # Bad data will still be bad on the second try, so no retries: the run stops here and
    # nothing reaches the warehouse.
    Step("validate", "validate", ("load_staging",)),
    Step("load_warehouse", "load-warehouse", ("validate",), retries=1),
    # The reports only read, so they can run side by side.
    Step("report_monthly_revenue", "report monthly-revenue --limit 24", ("load_warehouse",)),
    Step("report_top_products", "report top-products --limit 10", ("load_warehouse",)),
    Step("report_repeat_customers", "report repeat-customers", ("load_warehouse",)),
)
