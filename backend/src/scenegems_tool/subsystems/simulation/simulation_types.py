from dataclasses import dataclass
from typing import Any, Mapping

from scenegems_tool.subsystems.pool.pool_task import PoolTask

# Kept apart from the service module, which imports the vessel stack, so launchers and requesters can name
# the service, its task, its signals and its streams without loading it. Standard library only.
# The service's name on its own. A worker node's instance takes the name the cluster gave it
# (simulation-subsystem-<number>) and the topic root of its broker (messaging/mqtt_client.py service_topic).
SIMULATION_SERVICE_NAME = "simulation-subsystem"
RUN_SIMULATION_TASK = "run-simulation"  # the start-task name of a request: one run of every vessel's stack
COMPARE_REPEATS_TASK = "compare-repeats"  # the subsystem's second request: how far finished repeats of one run drift apart

OBSERVE_SIGNAL = "observe"  # somebody watches the run, or stopped watching: {"active", "speed"}
START_SIGNAL = "start"  # the operator's Start of an attended run

SIMULATION_FRAMES_STREAM = "simulation_frames"  # sensor/simulation_frames: the frames of an observed run, in batches
SIMULATION_LOG_STREAM = "simulation_log"  # sensor/simulation_log: the lines the run's containers wrote, in batches
SIMULATION_RESULT_STREAM = "simulation_result"  # sensor/simulation_result: the result of a run or of a comparison, or why it has none

# What the subsystem's container is told about the worker node it belongs to, next to the broker and the reference
# area every subsystem gets: the names its tasks' containers, folders and networks start with (instance_scope.py).
CONTROL_NODE_VARIABLE = "SCENEGEMS_CONTROL_NODE_ID"
WORKER_NODE_VARIABLE = "SCENEGEMS_WORKER_NODE_ID"
BROKER_NETWORK_VARIABLE = "SCENEGEMS_DOCKER_NETWORK"  # the Docker network the cluster's broker is reached on (utils/docker_compose_network.py)


@dataclass(frozen=True)
class RunSimulationTask(PoolTask):
    """One run. Its seed (PoolTask.seed) is the run seed of the payload, which the runner seeds the environment with."""

    job_id: str  # the job the run belongs to: its containers and its frames are named after it
    attempt: int  # the job's attempt, so a retry never meets what an earlier one left
    payload: Mapping[str, Any]  # the simulation job's payload: the runner and what it runs (jobs/simulation_job.py)


@dataclass(frozen=True)
class CompareRepeatsTask(PoolTask):
    """One comparison of the repeats of a run. Nothing in it is drawn at random; the seed is carried for the record."""

    payload: Mapping[str, Any]  # the calibration.deviation job's payload: the repeats' trajectories, the stack and the reference (jobs/calibration_deviation_job.py)
