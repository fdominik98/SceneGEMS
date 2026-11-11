"""The trajectory generation document: one generator node per TrajectoryGeneratorId, code locations that exist."""

from pathlib import Path

from scenegems_tool.subsystems.trajectory_generation.trajectory_generation_specs import DOCUMENT_ID, trajectory_generation_document
from scenegems_tool.subsystems.trajectory_generation.trajectory_generation_types import TrajectoryGeneratorId
from utils.file_system_utils import BACKEND_ROOT

SOURCE_ROOT = Path(BACKEND_ROOT) / "src"


def test_every_generator_id_has_a_node_in_the_generator_lane():
    document = trajectory_generation_document()
    generators = {node.id for node in document.nodes if node.lane == "generator"}
    assert generators == {f"{DOCUMENT_ID}/{member.value}" for member in TrajectoryGeneratorId}


def test_the_search_shows_its_defaults_from_the_code_and_the_straight_generator_none():
    nodes = {node.id: node for node in trajectory_generation_document().nodes}
    search = {fact.key: fact.value for fact in nodes["trajectory_generation/monitor_driven_rrt"].facts}
    assert search["bestRandomNodesK"] == 20 and search["randomness"].startswith("seeded")
    assert not {"goalSampleRate", "bestLeafSampleRate", "maxLeafs", "smoothingRounds"} & set(search)
    assert {fact.key: fact.value for fact in nodes["trajectory_generation/straight"].facts}["randomness"] == "none"


def test_the_request_reaches_both_generators_and_the_search_uses_the_monitor():
    document = trajectory_generation_document()
    edges = {edge.id for edge in document.edges}
    for generator in ("monitor_driven_rrt", "straight"):
        assert f"trajectory_generation/request__{generator}" in edges
    [request] = [node for node in document.nodes if node.lane == "entry"]
    facts = {fact.key: fact.value for fact in request.facts}
    assert (facts["request"], facts["tasks"]) == ("generate-trajectories", "one per request: one plan for the scene")
    assert "slots" in facts["pool"] and "sensor/planned_trajectory" in facts["publishes"]
    assert "trajectory_generation/monitor_driven_rrt__colregs_monitor" in edges
    assert "trajectory_generation/straight__colregs_monitor" not in edges


def test_every_code_location_exists():
    for node in trajectory_generation_document().nodes:
        for fact in node.facts:
            if fact.key == "code":
                assert (SOURCE_ROOT / str(fact.value)).exists(), fact.value
