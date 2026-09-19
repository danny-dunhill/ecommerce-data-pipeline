"""Airflow DAG: run the e-commerce pipeline every night.

The DAG is deliberately thin. Every task calls one command of the ``pipeline`` CLI, so there
is one code path: what Airflow runs is exactly what you can run by hand. Airflow only adds
the schedule, the order, retries, logs and the web UI.

The pipeline lives in its own virtualenv (see ``airflow/Dockerfile``), so its dependencies
(pandas, SQLAlchemy, ...) cannot clash with the ones Airflow needs.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG, Param

# The list of steps lives next to this file. Making sure this folder is importable keeps the
# DAG working however Airflow sets up its module search path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from pipeline_steps import STEPS  # noqa: E402

PIPELINE = "/opt/airflow/pipeline-venv/bin/pipeline"
# `dataset` is a run parameter (Trigger DAG w/ config): "sample" is small and part of the
# repository, "raw" is the full dataset that you download yourself into data/raw.
DATA_DIR = "/opt/airflow/data/{{ params.dataset }}"

with DAG(
    dag_id="ecommerce_pipeline",
    description="CSV files -> staging -> validation -> star schema -> reports",
    schedule="0 3 * * *",  # every day at 03:00 (UTC)
    start_date=datetime(2026, 1, 1),
    catchup=False,  # do not run for every missed day: the load is a full refresh anyway
    max_active_runs=1,  # two runs at once would drop and re-create the same staging tables
    default_args={
        "retry_delay": timedelta(seconds=30),
        "execution_timeout": timedelta(minutes=30),
    },
    params={
        "dataset": Param(
            "sample",
            enum=["sample", "raw"],
            description="Which folder under data/ to load.",
        )
    },
    tags=["ecommerce", "etl"],
) as dag:
    tasks = {
        step.task_id: BashOperator(
            task_id=step.task_id,
            bash_command=f"{PIPELINE} {step.command.format(data_dir=DATA_DIR)}",
            retries=step.retries,
        )
        for step in STEPS
    }
    for step in STEPS:
        for upstream in step.upstream:
            tasks[upstream] >> tasks[step.task_id]
