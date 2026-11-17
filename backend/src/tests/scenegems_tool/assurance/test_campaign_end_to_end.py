"""The Phase 4 exit test on one host (design doc 5.4, P4.7), now on Kubernetes: a control node and a worker node
installed from the release bundle's chart into k3d, campaigns through every stage implementation, and a control node
restart in the middle.

The cluster is deployed as the deployment tool deploys it (local_cluster.py: values from the roles, the chart
installed with helm and waited for). One campaign has 20 cases (five two-vessel classes at quota 4) with straight
trajectories and three runs: replay with the post-hoc monitor, USV Navigation with the live monitor, replay with the
empty monitor. A second, small campaign uses the monitor-driven RRT. Once some cases are complete the control node's
pod is deleted (its Deployment scaled to none) and stays away until every lease has expired, then a new pod is
created (scaled to one again); both campaigns must finish with their books in order. The operator API is reached
through a port forward to the service control-node-api, opened again after the restart, as the console reaches it.

Needs k3d, helm, kubectl and Docker, and every image of the release built under SCENEGEMS_TEST_IMAGE_TAG (latest by
default; tests/scenegems_tool/cluster/worker_node/k3d_cluster.py); the bundle is made of those images as they are.
About fifteen minutes.
"""

import hashlib
import time
import uuid
from contextlib import ExitStack
from typing import Any, Callable, Dict, List

import httpx
import pytest

from tests.scenegems_tool.assurance.local_cluster import LocalCluster, bundle_release, control_node, deploy, worker_node

pytestmark = [pytest.mark.kubernetes, pytest.mark.slow]

CLUSTER = "p4-rehearsal"
WORKER_NODE_PARAMETERS = {
    "SCENEGEMS_WORKER_NODE_SLOTS": "scene_generation:2,trajectory_generation:2,simulation:2,monitoring.post_hoc:2",
    "SCENEGEMS_WORKER_NODE_COMPONENTS": "asv_system/replay,asv_system/usv_navigation,control_layer/none,simulation_layer/kinematic,scene_generation,trajectory_generation,monitoring",
}
STRAIGHT_CLASSES = [f"2vessel_0obstacle_scenarios/fec{index}" for index in range(5)]
RRT_CLASSES = [f"2vessel_0obstacle_scenarios/fec{index}" for index in (5, 6)]
QUOTA = 4
RUNS = ["replay_post_hoc", "usv_navigation_live", "replay_empty"]

STRAIGHT_CAMPAIGN = f"""
format: 1
name: local rehearsal, straight
scope:
  - classes: [{", ".join(STRAIGHT_CLASSES)}]
    quota: {QUOTA}
    failure_budget: 8
trajectories:
  generator: straight
  timespan_s: 120
  timeout_s: 300
execution:
  runs:
    - name: replay_post_hoc
      stack: {{simulation_layer: kinematic, mode: replay}}
      monitor: post_hoc
    - name: usv_navigation_live
      stack: {{simulation_layer: kinematic, mode: usv_navigation}}
      monitor: live
    - name: replay_empty
      stack: {{simulation_layer: kinematic, mode: replay}}
      monitor: empty
policy:
  seed: 26
"""

RRT_CAMPAIGN = f"""
format: 1
name: local rehearsal, monitor-driven RRT
scope:
  - classes: [{", ".join(RRT_CLASSES)}]
    quota: 1
    failure_budget: 2
trajectories:
  generator: monitor_driven_rrt
  timeout_s: 600
execution:
  runs:
    - name: usv_navigation_post_hoc
      stack: {{simulation_layer: kinematic, mode: usv_navigation}}
      monitor: post_hoc
policy:
  seed: 27
"""


def _wait_for(condition: Callable[[], Any], timeout_s: float, what: str, every_s: float = 3.0) -> Any:
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            value = condition()
        except httpx.HTTPError:
            value = None
        if value:
            return value
        if time.monotonic() > deadline:
            raise TimeoutError(f"{what} did not happen within {timeout_s:.0f} s")
        time.sleep(every_s)


class OperatorApi:
    """The operator API through a port forward to the control node's service; the forward is opened again after a restart, since it ends with the pod it reached."""

    def __init__(self, cluster: LocalCluster):
        self.cluster = cluster
        self._stack = ExitStack()
        self.client: httpx.Client

    def open(self) -> "OperatorApi":
        port = self._stack.enter_context(self.cluster.forward("operator-api"))
        self.client = self._stack.enter_context(httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=60))
        return self

    def close(self) -> None:
        self._stack.close()
        self._stack = ExitStack()

    def _call(self, method: str, *arguments: Any, **options: Any) -> httpx.Response:
        """A request; a forward that broke during the long wait (kubectl ends it on a lost stream) is opened again once."""
        try:
            return getattr(self.client, method)(*arguments, **options)
        except httpx.TransportError:
            self.close()
            self.open()
            return getattr(self.client, method)(*arguments, **options)

    def get(self, *arguments: Any, **options: Any) -> httpx.Response:
        return self._call("get", *arguments, **options)

    def post(self, *arguments: Any, **options: Any) -> httpx.Response:
        return self.client.post(*arguments, **options)  # not repeated: it may have reached the control node


@pytest.fixture(scope="module")
def cluster(k3d_cluster, tmp_path_factory):
    release_dir, release = bundle_release(tmp_path_factory.mktemp("local-cluster"), k3d_cluster.image_tag)
    members = [control_node(k3d_cluster.node), worker_node(f"e2e-{uuid.uuid4().hex[:6]}", k3d_cluster.node, **WORKER_NODE_PARAMETERS)]
    local = deploy(k3d_cluster, release_dir, release, members, cluster_id=CLUSTER)
    try:
        yield local
    finally:
        local.uninstall()


@pytest.fixture(scope="module")
def api(cluster):
    operator = OperatorApi(cluster).open()
    try:
        yield operator
    finally:
        operator.close()


def _create(api: OperatorApi, config: str) -> Dict[str, Any]:
    response = api.post("/cluster/campaigns", params={"start": "true"}, content=config.encode(), headers={"Content-Type": "application/yaml"})
    assert response.status_code == 201, response.text
    return response.json()


def _campaign(api: OperatorApi, campaign_id: str) -> Dict[str, Any]:
    response = api.get(f"/cluster/campaigns/{campaign_id}")
    response.raise_for_status()
    return response.json()


def _all(api: OperatorApi, path: str, **params: Any) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    while True:
        page = api.get(path, params={**params, "limit": 1000, "offset": len(items)}).json()
        items.extend(page)
        if len(page) < 1000:
            return items


def _live_leases(cluster: LocalCluster) -> int:
    count = cluster.kubectl(
        "exec",
        "statefulset/postgres",
        "-c",
        "postgres",
        "--",
        "psql",
        "-U",
        "scenegems",
        "-d",
        "scenegems",
        "-tAc",
        "SELECT count(*) FROM job WHERE state IN ('leased', 'running') AND lease_expires_at > now()",
    )
    return int(count.strip())


def _control_node_pods(cluster: LocalCluster) -> List[str]:
    return cluster.kubectl("get", "pods", "-l", "app.kubernetes.io/name=control-node-api", "-o", "name").split()


def _restart_control_node_after_the_leases_expired(cluster: LocalCluster, api: OperatorApi) -> None:
    """The control node's pod deleted and kept away until every lease has expired, then a new one created, as a crashed control node comes back."""
    api.close()
    before = _control_node_pods(cluster)
    cluster.kubectl("scale", "deployment/control-node-api", "--replicas=0")
    _wait_for(lambda: not _control_node_pods(cluster), 120, "the control node's pod going")
    _wait_for(lambda: _live_leases(cluster) == 0, 180, "every lease expiring while the control node is down")
    cluster.kubectl("scale", "deployment/control-node-api", "--replicas=1")
    cluster.wait_ready()
    assert not set(_control_node_pods(cluster)) & set(before), "a new pod"
    api.open()


def test_campaigns_through_every_stage_survive_a_control_node_restart(cluster, api):
    _wait_for(
        lambda: [worker_node for worker_node in api.get("/cluster/worker-nodes").json() if worker_node["status"] == "online" and not worker_node["out_of_date"]],
        240,
        "the worker node coming online and up to date",
    )
    straight = _create(api, STRAIGHT_CAMPAIGN)
    rrt = _create(api, RRT_CAMPAIGN)

    _wait_for(lambda: _campaign(api, straight["campaign_id"])["totals"]["complete"] >= 6, 1200, "six complete cases before the restart", every_s=5)
    _restart_control_node_after_the_leases_expired(cluster, api)

    finished = {}
    for campaign in (straight, rrt):
        finished[campaign["campaign_id"]] = _wait_for(
            lambda: (lambda view: view if view["actual_state"] in ("completed", "stopped") else None)(_campaign(api, campaign["campaign_id"])),
            2400,
            f"campaign {campaign['name']} finishing",
            every_s=5,
        )

    # The straight campaign: every class complete with exactly its quota, one verdict per case and run
    view = finished[straight["campaign_id"]]
    assert view["actual_state"] == "completed"
    assert {entry["fec_id"]: (entry["state"], entry["complete"]) for entry in view["fecs"]} == {class_id: ("complete", QUOTA) for class_id in STRAIGHT_CLASSES}
    verdicts = _all(api, f"/cluster/campaigns/{straight['campaign_id']}/verdicts")
    assert len(verdicts) == len(STRAIGHT_CLASSES) * QUOTA * len(RUNS)
    states_by_run = {run_index: {verdict["state"] for verdict in verdicts if verdict["run_index"] == run_index} for run_index in range(len(RUNS))}
    assert states_by_run[0] <= {"passed", "failed"} and states_by_run[1] <= {"passed", "failed"} and states_by_run[2] == {"unmonitored"}
    assert {verdict["monitor"] for verdict in verdicts} == {"post_hoc", "live", "empty"}
    cases = _all(api, f"/cluster/campaigns/{straight['campaign_id']}/cases")
    assert all(case["state"] in ("complete", "dropped", "failed", "cancelled") for case in cases)  # nothing left active
    assert sum(case["state"] == "complete" for case in cases) == len(STRAIGHT_CLASSES) * QUOTA
    # A run record is written when its simulation ends: each complete case has exactly one per run, the
    # rest belong to cases that were cut
    records = _all(api, f"/cluster/campaigns/{straight['campaign_id']}/run-records")
    assert all(record["state_digest"] for record in records)
    assert len({(record["case_id"], record["run_index"], record["repeat_index"]) for record in records}) == len(records)
    case_states = {case["case_id"]: case["state"] for case in cases}
    complete_runs = sorted((record["case_id"], record["run_index"]) for record in records if case_states[record["case_id"]] == "complete")
    assert complete_runs == sorted((case_id, run_index) for case_id, state in case_states.items() if state == "complete" for run_index in range(len(RUNS)))
    assert {case_states[record["case_id"]] for record in records} <= {"complete", "cancelled"}
    events = _all(api, f"/cluster/campaigns/{straight['campaign_id']}/events")
    # The engine first started before the campaign existed, so its one engine_started is the restart's
    kinds = [event["kind"] for event in events]
    assert kinds.count("engine_started") == 1 and kinds.index("engine_started") > kinds.index("started")

    # Results travelled as artifacts: a state log is in the control node's store and matches its address
    state_log = next(record["artifacts"]["state_log"] for record in records if record["artifacts"].get("state_log"))
    content = api.get(f"/cluster/artifacts/{state_log}")
    assert content.status_code == 200 and hashlib.sha256(content.content).hexdigest() == state_log

    # No job of either campaign is left queued, leased or running
    for state in ("queued", "leased", "running"):
        left = [job for job in _all(api, "/cluster/jobs", state=state) if job["idempotency_key"].startswith("campaign:")]
        assert left == [], f"{len(left)} campaign jobs are still {state}"

    # The RRT campaign finished too; a class may be abandoned when its searches find no complete plan
    view = finished[rrt["campaign_id"]]
    assert view["actual_state"] == "completed"
    assert all(entry["state"] in ("complete", "abandoned") for entry in view["fecs"])
    assert all(entry["complete"] == 1 for entry in view["fecs"] if entry["state"] == "complete")
