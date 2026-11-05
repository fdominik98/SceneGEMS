"""The scene generation worker in process: a seed fixes the scene, the real seed is recorded, the last sample is final."""

import hashlib
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from scenegems_tool.subsystems.scene_generation.scene_generation_types import MqttSceneGenerationTask
from scenegems_tool.subsystems.scene_generation.scene_generation_worker import MAX_SEED, run_scene_generation_worker
from utils.file_system_utils import COLREGS_CONSTANTS_FOLDER, FUNCTIONAL_MODELS_FOLDER, STATIC_OBSTACLE_TYPES_FOLDER, VESSEL_TYPES_FOLDER

SMALL_CLASS = "2vessel_0obstacle_scenarios"


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as file:
        return file.read()


def _task(seed, scenario_class: str = SMALL_CLASS) -> MqttSceneGenerationTask:
    return MqttSceneGenerationTask(
        sender="test",
        task_uuid="uuid",
        request_id="request",
        functional_scenario_content=_read(f"{FUNCTIONAL_MODELS_FOLDER}/all/{scenario_class}/fec0.problem"),
        colregs_constraints_content=_read(f"{COLREGS_CONSTANTS_FOLDER}/general_maritime_constants.yaml"),
        vessel_types_content=_read(f"{VESSEL_TYPES_FOLDER}/vessel_types.yaml"),
        obstacle_types_content=_read(f"{STATIC_OBSTACLE_TYPES_FOLDER}/static_obstacle_types.yaml"),
        timeout=60,
        seed=seed,
    )


class _Queue:
    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


def generate(seed, scenario_class: str = SMALL_CLASS):
    """Every (evaluation data, final) the worker queued."""
    queue = _Queue()
    run_scene_generation_worker(_task(seed, scenario_class), queue, threading.Event())
    return [(evaluation_data, final) for _, evaluation_data, final in queue.items]


def _scene(samples) -> str:
    finals = [evaluation_data for evaluation_data, final in samples if final]
    assert len(finals) == 1 and samples[-1][1]  # one final sample, the last one
    return json.dumps(finals[0].best_scene.to_dict(), sort_keys=True)


def test_the_same_seed_gives_the_same_scene():
    first, second = generate(7), generate(7)
    assert _scene(first) == _scene(second)
    assert first[-1][0].random_seed == 7 and first[-1][0].is_valid


def test_another_seed_gives_another_scene():
    assert _scene(generate(7)) != _scene(generate(8))


def test_without_a_seed_the_worker_draws_one_and_records_it():
    samples = generate(None)
    seed = samples[-1][0].random_seed
    assert 0 <= seed <= MAX_SEED
    assert _scene(samples) == _scene(generate(seed))


_SCRIPT = """
import hashlib, json, sys
from tests.scenegems_tool.subsystems.scene_generation.test_scene_generation_worker import _scene, generate
print(hashlib.sha256(_scene(generate(int(sys.argv[1]), sys.argv[2])).encode()).hexdigest())
"""


@pytest.mark.slow
@pytest.mark.parametrize("scenario_class", [SMALL_CLASS, "3vessel_0obstacle_scenarios"])
def test_the_scene_does_not_depend_on_the_process(scenario_class):
    """Workers are separate processes with their own hash seed, so set and dict orders must not reach the scene."""
    source = Path(__file__).resolve().parents[4]
    digests = set()
    for hash_seed in ("0", "1", "4242"):
        environment = {**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONPATH": str(source)}
        output = subprocess.run([sys.executable, "-c", _SCRIPT, "11", scenario_class], cwd=source.parent, env=environment, capture_output=True, text=True, check=True).stdout
        digests.add(output.strip().splitlines()[-1])
    assert len(digests) == 1, digests
    assert hashlib.sha256(b"").hexdigest() not in digests
