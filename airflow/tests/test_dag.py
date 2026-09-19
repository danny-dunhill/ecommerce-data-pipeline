"""Loads the real DAG file with Airflow itself and checks the task graph.

Airflow is a heavy dependency, so these tests only run where it is installed: the
`airflow-dag` job of the CI workflow. Everywhere else they are skipped.
"""

import runpy
from pathlib import Path

import pytest

pytest.importorskip("airflow")

DAGS = Path(__file__).resolve().parents[1] / "dags"


@pytest.fixture(scope="module")
def dag():
    return runpy.run_path(str(DAGS / "ecommerce_pipeline.py"))["dag"]


@pytest.fixture(scope="module")
def steps():
    return runpy.run_path(str(DAGS / "pipeline_steps.py"))["STEPS"]


def test_the_dag_loads_and_has_one_task_per_step(dag, steps):
    assert dag.dag_id == "ecommerce_pipeline"
    assert set(dag.task_dict) == {step.task_id for step in steps}


def test_the_task_graph_matches_the_steps(dag, steps):
    for step in steps:
        task = dag.get_task(step.task_id)
        assert task.upstream_task_ids == set(step.upstream)
        assert task.retries == step.retries


def test_every_task_calls_the_pipeline_command_of_its_own_virtualenv(dag):
    for task in dag.tasks:
        assert task.bash_command.startswith("/opt/airflow/pipeline-venv/bin/pipeline ")


def test_runs_do_not_overlap_and_missed_days_are_not_replayed(dag):
    assert dag.max_active_runs == 1
    assert dag.catchup is False
