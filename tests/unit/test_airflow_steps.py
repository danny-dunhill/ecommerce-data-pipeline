"""The Airflow DAG is built from ``airflow/dags/pipeline_steps.py``. That file has no Airflow
imports, so the schedule can be tested here without installing Airflow."""

import importlib.util
import shlex
import sys
from pathlib import Path

import pytest
import typer.main

from ecom_pipeline.cli import app

STEPS_FILE = Path(__file__).resolve().parents[2] / "airflow" / "dags" / "pipeline_steps.py"


def load_steps():
    spec = importlib.util.spec_from_file_location("pipeline_steps", STEPS_FILE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module.STEPS


STEPS = load_steps()


def test_task_ids_are_unique():
    ids = [step.task_id for step in STEPS]

    assert len(ids) == len(set(ids))


def test_steps_are_listed_in_a_valid_order_so_the_graph_has_no_cycle():
    seen: set[str] = set()
    for step in STEPS:
        assert set(step.upstream) <= seen, f"{step.task_id} waits for a step that comes later"
        seen.add(step.task_id)


def test_the_run_starts_with_one_task_and_the_load_only_happens_after_validation():
    roots = [step.task_id for step in STEPS if not step.upstream]
    by_id = {step.task_id: step for step in STEPS}

    assert roots == ["check_db"]
    assert by_id["load_warehouse"].upstream == ("validate",)
    assert by_id["validate"].upstream == ("load_staging",)


def test_validation_is_not_retried_because_bad_data_stays_bad():
    by_id = {step.task_id: step for step in STEPS}

    assert by_id["validate"].retries == 0


@pytest.mark.parametrize("step", STEPS, ids=lambda step: step.task_id)
def test_every_step_is_a_valid_pipeline_command(step):
    args = shlex.split(step.command.format(data_dir="."))
    command = typer.main.get_command(app).commands[args[0]]  # KeyError: no such command

    # parses the arguments and options exactly as the CLI would, but runs nothing
    with command.make_context(args[0], args[1:]):
        pass
