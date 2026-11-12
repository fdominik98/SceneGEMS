"""The worker of an exploration task: it runs the Refinery model generator for the task and hands back the FECs.

The generator is the image's own program. `generate-models job -folder <folder>` speaks the job folder protocol
(cluster/worker_node/launchers/per_job/job_container_io.py): it reads job.json, writes a status line a second
while it generates and leaves result.json. Every task gets a folder and a generator process of its own, so the
explorations of a pool share nothing; the folder is removed when the task ends.

The worker relays the generator's status lines as the task's progress and emits one message on the design
space stream: the explored FECs (design_space.explored_fecs), or the generator's error. An error is a result,
not a failed task: a specification that does not parse fails the same way at every attempt, and the requester
has to hear that. A generator that ends without a result document (killed, out of memory) fails the task.

A cancelled task ends its generator at once and emits nothing. A generator that runs past its own limits by
STOP_MARGIN_S is ended and fails the task.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

from scenegems_tool.cluster.worker_node.launchers.container_environment import worker_count_from_environment
from scenegems_tool.cluster.worker_node.launchers.per_job.job_container_io import JOB_DOCUMENT, RESULT_DOCUMENT, STATUS_LINE_PREFIX
from scenegems_tool.subsystems.design_space_exploration.design_space import explored_fecs
from scenegems_tool.subsystems.design_space_exploration.design_space_exploration_types import DESIGN_SPACE_STREAM, ExploreDesignSpaceTask

GENERATOR_COMMAND: Tuple[str, ...] = ("generate-models", "job", "-folder")  # followed by the task's folder
JAVA_OPTIONS_VARIABLE = "JAVA_OPTS"
HEAP_PERCENT = 75.0  # of the container's memory, for all the generators of the pool together
POLL_S = 0.1  # how often the worker looks at its cancel flag while the generator runs
KILL_WAIT_S = 10.0


class GeneratorFailed(RuntimeError):
    """The generator ended without saying how: no result document, or none it could be asked for in time."""


def generator_environment(pool_size: int, environment: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """The generator's environment: the container's, with the Java heap limited to this task's share of the container's memory."""
    made = dict(os.environ if environment is None else environment)
    made[JAVA_OPTIONS_VARIABLE] = f"-XX:MaxRAMPercentage={HEAP_PERCENT / max(1, pool_size):g}"
    return made


def status_of(line: str) -> Optional[Tuple[str, Optional[float], Dict[str, Any]]]:
    """(message, progress, the other fields) of a status line of the generator; None for a log line."""
    if not line.startswith(STATUS_LINE_PREFIX):
        return None
    try:
        status = json.loads(line[len(STATUS_LINE_PREFIX) :])
        message, progress = str(status.pop("message")), status.pop("progress", None)
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    return message, progress, status


def _relay_output(process: Any, channel: Any) -> None:
    """The generator's status lines become the task's progress; its other lines go to the container's log."""
    for line in process.stdout:
        line = line.rstrip("\r\n")
        status = status_of(line)
        if status is None:
            print(line, file=sys.stderr, flush=True)
        else:
            channel.progress(*status)


def _end(process: Any) -> None:
    process.kill()
    try:
        process.wait(timeout=KILL_WAIT_S)
    except subprocess.TimeoutExpired:
        pass


def _outcome(folder: str, exit_code: Optional[int]) -> Dict[str, Any]:
    """What the generator left in its folder as the task's result message."""
    path = os.path.join(folder, RESULT_DOCUMENT)
    try:
        with open(path, encoding="utf-8") as file:
            document = json.load(file)
    except (OSError, ValueError) as error:
        raise GeneratorFailed(f"the model generator ended with exit code {exit_code} and left no result") from error
    if isinstance(document, Mapping) and isinstance(document.get("result"), Mapping):
        try:
            return {"design-space": explored_fecs(document["result"]), "error": None, "retryable": False}
        except ValueError as error:
            return {"design-space": None, "error": str(error), "retryable": False}
    if isinstance(document, Mapping) and document.get("error"):
        return {"design-space": None, "error": str(document["error"]), "retryable": bool(document.get("retryable", False))}
    raise GeneratorFailed("the model generator left a result document with neither a result nor an error")


def explore(
    task: ExploreDesignSpaceTask,
    channel: Any,
    command: Sequence[str] = GENERATOR_COMMAND,
    pool_size: Optional[int] = None,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Run the generator for the task until it ends, the task is cancelled or its time is over; emit what it found."""
    if channel.cancelled:
        return  # cancelled as it started: no generator is started for it
    folder = tempfile.mkdtemp(prefix="explore-")
    try:
        with open(os.path.join(folder, JOB_DOCUMENT), "w", encoding="utf-8") as file:
            json.dump({"job": {"job_id": task.request_id, "payload": task.generator_payload()}}, file)
        environment = generator_environment(worker_count_from_environment(1) if pool_size is None else pool_size)
        process = subprocess.Popen([*command, folder], stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=environment)
        relay = threading.Thread(target=_relay_output, args=(process, channel), name="generator_output", daemon=True)
        relay.start()
        deadline = None if task.run_limit_s is None else clock() + task.run_limit_s
        while True:
            try:
                exit_code = process.wait(timeout=POLL_S)
                break
            except subprocess.TimeoutExpired:
                pass
            if channel.cancelled:
                _end(process)
                return
            if deadline is not None and clock() > deadline:
                _end(process)
                raise GeneratorFailed(f"the model generator did not end within {task.run_limit_s:g} s")
        relay.join(timeout=KILL_WAIT_S)
        if channel.cancelled:
            return
        channel.emit(DESIGN_SPACE_STREAM, _outcome(folder, exit_code), final=True)
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def run_design_space_exploration_worker(task: ExploreDesignSpaceTask, channel: Any) -> None:
    """What a worker process of the design space exploration pool runs for a task."""
    explore(task, channel)
