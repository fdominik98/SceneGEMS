"""What a job runner needs from its worker node: identity, slots, broker access, the shared pools, artifact transport and observations.

The worker node daemon builds one WorkerNodeContext from its configuration
(daemon/worker_node_runtime.py) and calls `shutdown` when it stops. Tests build one directly.
"""

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional

from scenegems_tool.cluster.fingerprints.components import JOB_TYPE_COMPONENTS
from scenegems_tool.cluster.protocol.jobs import JobSpec, JobType
from scenegems_tool.cluster.worker_node.artifacts.worker_node_artifacts import ArtifactTransport
from scenegems_tool.cluster.worker_node.instance_scope import InstanceScope
from scenegems_tool.cluster.worker_node.job_observation import JobObservations
from scenegems_tool.cluster.worker_node.launchers.pooled.service_pools import ServicePools
from scenegems_tool.cluster.worker_node.subsystem import Subsystem
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence

# The subsystem a job's own containers are named after (instance_scope.py)
_JOB_SUBSYSTEMS = {
    JobType.DESIGN_SPACE_EXPLORATION: Subsystem.DESIGN_SPACE_EXPLORATION,
    JobType.SCENE_GENERATION: Subsystem.SCENE_GENERATION,
    JobType.TRAJECTORY_GENERATION: Subsystem.TRAJECTORY_GENERATION,
    JobType.SIMULATION: Subsystem.SIMULATION,
    JobType.MONITORING_POST_HOC: Subsystem.MONITORING,
    JobType.CALIBRATION_DEVIATION: Subsystem.SIMULATION,  # repeats of a simulation, in the simulation subsystem's image
}
# The job type whose slots size each pooled subsystem's worker pool.
_POOL_JOB_TYPES = {
    Subsystem.SCENE_GENERATION: JobType.SCENE_GENERATION,
    Subsystem.TRAJECTORY_GENERATION: JobType.TRAJECTORY_GENERATION,
    Subsystem.MONITORING: JobType.MONITORING_POST_HOC,
}


@dataclass
class WorkerNodeContext:
    control_node_id: str
    worker_node_id: str
    # The broker as this process dials it (client_broker) and as containers dial it
    # (agent_broker), with the first level of its topics.
    mqtt_connection: MQttConnectionInfo
    reference_geofence: Geofence  # frame of the pooled services; simulation payloads carry their own
    slots: Dict[JobType, int] = field(default_factory=dict)
    components: FrozenSet[str] = frozenset()  # what the worker node runs jobs with; empty for any (the workbench)
    broker_network: Optional[str] = None  # Docker network the broker is reachable on; SCENEGEMS_DOCKER_NETWORK when None
    artifacts: Optional[ArtifactTransport] = None  # downloads referenced inputs and uploads results; None keeps results inline
    observations: JobObservations = field(default_factory=JobObservations)  # running jobs' live observations; the daemon's lease manager opens them
    # The number the control node gave this worker node in its Welcome; it tells the worker node's pooled services from
    # every other worker node's on MQTT. 1 for a worker node that runs alone (tests, tools).
    instance_number: int = 1
    pools: ServicePools = field(init=False)

    def __post_init__(self) -> None:
        self.pools = ServicePools(self.control_node_id, self.worker_node_id, self.mqtt_connection, self.reference_geofence, self.pool_workers, self.broker_network, lambda: self.instance_number)

    def lacks(self, job: JobSpec) -> List[str]:
        """The components the job requires that this worker node does not offer; empty when it offers them all, or when it names none."""
        if not self.components:
            return []
        return [component for component in job.requirements.components if component not in self.components]

    def pool_workers(self, subsystem: Subsystem) -> int:
        return max(1, self.slots.get(_POOL_JOB_TYPES[subsystem], 1))

    def pool_subsystems(self) -> List[Subsystem]:
        """The pooled subsystems this worker node offers by its components; none for a worker node that names no components."""
        return [subsystem for subsystem, job_type in _POOL_JOB_TYPES.items() if JOB_TYPE_COMPONENTS[job_type] in self.components]

    def start_pools(self) -> None:
        """Start the pools of the subsystems the worker node offers, so they are up before the first job (the daemon, once it has its number)."""
        self.pools.start(self.pool_subsystems())

    def check_pools(self) -> List[Subsystem]:
        """Start again the pools whose container is gone; returns the subsystems that were restarted."""
        return self.pools.ensure_running()

    def job_scope(self, job: JobSpec) -> InstanceScope:
        """The scope of a job's per-job stack, named after the job's subsystem; each attempt gets its own, so a retry never meets a leftover."""
        return InstanceScope.per_job(self.control_node_id, self.worker_node_id, _JOB_SUBSYSTEMS[job.job_type].value, job.job_id, job.attempt)

    def set_instance_number(self, instance_number: int) -> None:
        """The number from the control node's Welcome. Pools named after another number are removed; start_pools starts them under the new one."""
        if instance_number == self.instance_number:
            return
        self.pools.shutdown()
        self.instance_number = instance_number

    def shutdown(self) -> None:
        self.pools.shutdown()
