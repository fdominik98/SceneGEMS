"""The Phase 4 exit test on one host (design doc 5.4, P4.7): a master and a node from the release
bundle, campaigns through every stage implementation, and a master restart in the middle.

The cluster is deployed as the deployment tool deploys it (local_cluster.py). One campaign
has 20 cases (five two-vessel classes at quota 4) with straight trajectories and three runs:
replay with the post-hoc monitor, USV Navigation with the live monitor, replay with the empty
monitor. A second, small campaign uses the monitor-driven RRT. Once some cases are complete
the master-api container stops until every lease has expired, then starts again; both
campaigns must finish with their books in order.

Needs Docker with Compose v2 and the cluster's images built from this checkout
(`./build.sh --release <folder>`); about ten minutes.
"""

import hashlib
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, List

import httpx
import pytest

from scenegems_tool.cluster.release.__main__ import checkout_revision
from scenegems_tool.cluster.release.bundle import build_bundle
from tests.scenegems_tool.assurance.local_cluster import LocalRole, deploy_master, deploy_node, remove_cluster_containers

pytestmark = [pytest.mark.docker, pytest.mark.slow]

REPO_ROOT = Path(__file__).resolve().parents[5]
CLUSTER = "p4-rehearsal"
NODE = "local"
OPERATOR_PORT = 15174
MASTER_PARAMETERS = {"SCENEGEMS_API_PORT": "18443", "SCENEGEMS_BROKER_PORT": "18883", "SCENEGEMS_OPERATOR_PORT": str(OPERATOR_PORT), "POSTGRES_HOST_PORT": "15432"}
NODE_PARAMETERS = {"SCENEGEMS_NODE_CAPABILITIES": "scene_generation:2,trajectory_generation:2,simulation.kinematic:2,monitoring.post_hoc:2"}
STRAIGHT_CLASSES = [f"2vessel_0obstacle_scenarios/functional_model{index}" for index in range(5)]
RRT_CLASSES = [f"2vessel_0obstacle_scenarios/functional_model{index}" for index in (5, 6)]
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


def _docker_available() -> bool:
    return shutil.which("docker") is not None and subprocess.run(["docker", "info"], capture_output=True).returncode == 0


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


@pytest.fixture(scope="module")
def cluster(tmp_path_factory):
    if not _docker_available():
        pytest.skip("Docker is not available")
    work = tmp_path_factory.mktemp("local-cluster")
    revision, dirty = checkout_revision(REPO_ROOT)
    release = build_bundle(work / "release", REPO_ROOT, revision, dirty)
    remove_cluster_containers(CLUSTER)
    roles: List[LocalRole] = []
    try:
        master = deploy_master(work / "release", release, work, CLUSTER, MASTER_PARAMETERS)
        roles.append(master)
        roles.append(deploy_node(work / "release", release, work, CLUSTER, NODE, NODE_PARAMETERS, MASTER_PARAMETERS))
        yield master
    finally:
        for role in reversed(roles):
            role.down()
        remove_cluster_containers(CLUSTER)


@pytest.fixture(scope="module")
def api(cluster):
    with httpx.Client(base_url=f"http://127.0.0.1:{OPERATOR_PORT}", timeout=60) as client:
        yield client


def _create(api: httpx.Client, config: str) -> Dict[str, Any]:
    response = api.post("/cluster/campaigns", params={"start": "true"}, content=config.encode(), headers={"Content-Type": "application/yaml"})
    assert response.status_code == 201, response.text
    return response.json()


def _campaign(api: httpx.Client, campaign_id: str) -> Dict[str, Any]:
    response = api.get(f"/cluster/campaigns/{campaign_id}")
    response.raise_for_status()
    return response.json()


def _all(api: httpx.Client, path: str, **params: Any) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    while True:
        page = api.get(path, params={**params, "limit": 1000, "offset": len(items)}).json()
        items.extend(page)
        if len(page) < 1000:
            return items


def _live_leases(master: LocalRole) -> int:
    count = master.compose("exec", "-T", "postgres", "psql", "-U", "scenegems", "-d", "scenegems", "-tAc", "SELECT count(*) FROM job WHERE state IN ('leased', 'running') AND lease_expires_at > now()")
    return int(count.strip())


def _restart_master_after_the_leases_expired(master: LocalRole) -> None:
    master.compose("stop", "master-api")
    _wait_for(lambda: _live_leases(master) == 0, 180, "every lease expiring while the master is down")
    master.compose("start", "master-api")
    master.wait_ready()


def test_campaigns_through_every_stage_survive_a_master_restart(cluster, api):
    _wait_for(lambda: [node for node in api.get("/cluster/nodes").json() if node["status"] == "online" and not node["out_of_date"]], 240, "the node coming online and up to date")
    straight = _create(api, STRAIGHT_CAMPAIGN)
    rrt = _create(api, RRT_CAMPAIGN)

    _wait_for(lambda: _campaign(api, straight["campaign_id"])["totals"]["complete"] >= 6, 1200, "six complete cases before the restart", every_s=5)
    _restart_master_after_the_leases_expired(cluster)

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

    # Results travelled as artifacts: a state log is in the master's store and matches its address
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
