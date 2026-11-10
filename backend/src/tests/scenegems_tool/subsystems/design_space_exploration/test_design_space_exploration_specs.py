"""The design space exploration document names what the job runs: its literals are checked against the code."""

from pathlib import Path

from scenegems_tool.architecture.architecture_model import ROLE_STEP
from scenegems_tool.assurance.campaign.campaign_config import DesignSpaceExplorationConfig
from scenegems_tool.cluster.fingerprints.components import DESIGN_SPACE_EXPLORATION_IMAGE
from scenegems_tool.cluster.node.jobs import design_space_exploration_job
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.subsystems.design_space_exploration import design_space
from scenegems_tool.subsystems.design_space_exploration import design_space_exploration_specs as specs
from scenegems_tool.subsystems.design_space_exploration.design_space_exploration_specs import design_space_exploration_document
from scenegems_tool.subsystems.subsystem_spec import default_measured_facts
from utils.file_system_utils import BACKEND_ROOT
from utils.image_names import image_repository

SOURCE_ROOT = Path(BACKEND_ROOT) / "src"
REPOSITORY_ROOT = Path(BACKEND_ROOT).parent


def test_the_literals_match_the_job_the_image_and_the_defaults():
    assert specs.JOB_TYPE == JobType.DESIGN_SPACE_EXPLORATION.value
    assert specs.IMAGE_REPOSITORY == image_repository(DESIGN_SPACE_EXPLORATION_IMAGE)
    assert specs.GENERATOR_COMMAND == " ".join(design_space_exploration_job.GENERATOR_COMMAND)
    assert specs.DEFAULT_SCOPE == design_space.DEFAULT_SCOPE
    section = DesignSpaceExplorationConfig(specification="class A.", scope="A = 1")
    assert (specs.DEFAULT_TIMEOUT_S, specs.DEFAULT_MAX_FECS) == (section.timeout_s, section.max_fecs)
    assert specs.DEFAULT_TIMEOUT_S == design_space_exploration_job.DEFAULT_TIMEOUT_S


def test_the_request_flows_through_the_problem_and_the_generator_to_the_fecs():
    document = design_space_exploration_document()
    assert [lane.id for lane in document.lanes] == ["entry", "problem", "exploration", "output"]
    edges = {(edge.source.split("/")[1], edge.target.split("/")[1]) for edge in document.edges}
    assert edges == {
        ("cluster_job", "colregs_specification"),
        ("cluster_job", "scope_bounds"),
        ("colregs_specification", "refinery"),
        ("scope_bounds", "refinery"),
        ("refinery", "fec_sources"),
    }


def test_every_interface_of_the_metamodel_is_implemented():
    document = design_space_exploration_document()
    assert {node.id for node in document.metamodel_nodes} == {node.implements for node in document.nodes}


def test_it_is_the_first_step_of_the_chain_and_names_its_job_type():
    document = design_space_exploration_document()
    assert (document.role, document.step, document.takes, document.gives) == (ROLE_STEP, "Design space exploration", "a specification and a scope", "FECs")
    assert document.job_types == (JobType.DESIGN_SPACE_EXPLORATION.value,)


def test_every_code_location_in_the_repository_exists():
    document = design_space_exploration_document()
    locations = [str(fact.value) for node in document.nodes for fact in node.facts if fact.key == "code"]
    locations += [node.code for node in document.metamodel_nodes if node.code]
    for location in locations:
        if location == specs.UPSTREAM:
            continue  # the generator lives in the Refinery repository
        root = REPOSITORY_ROOT if location.startswith("backend/") else SOURCE_ROOT
        assert (root / location).exists(), location


def test_the_measured_exploration_times_are_shown_on_the_generator():
    document = design_space_exploration_document(default_measured_facts())
    generator = next(node for node in document.nodes if node.id == "design_space_exploration/refinery")
    measured = {fact.key: fact.value for fact in generator.facts if fact.measured}
    assert measured == {"fecs_one_target_ship": 7, "fecs_two_target_ships": 28, "fecs_two_target_ships_one_obstacle": 28}
    assert generator.evidence
