import anyio
import pytest

from scenegems_tool.cluster.fingerprints.job_images import MONITORING_IMAGE, SCENARIO_EXECUTION_IMAGE, SCENE_GENERATION_IMAGE
from scenegems_tool.cluster.master.scheduling.fingerprint_policy import ExpectedFingerprints, ListingState, node_mismatches, with_required_fingerprints
from scenegems_tool.cluster.protocol.jobs import JobRequirements, JobSubmission, JobType
from scenegems_tool.cluster.release.manifest import Release, ReleaseImage, write_release
from tests.scenegems_tool.cluster.master.conftest import EXPECTED
from tests.scenegems_tool.cluster.master.fake_stores import InMemoryNodeStore
from tests.scenegems_tool.cluster.stack_images import GAZEBO_IMAGE, SITL_IMAGE
from tests.scenegems_tool.persistence.stores.builders import ManualClock, make_hello


def _load(expected: ExpectedFingerprints) -> None:
    anyio.run(expected.load)


def test_a_fixed_listing_is_ready():
    expected = ExpectedFingerprints.fixed({"a:latest": "1"})
    assert expected.state == ListingState.READY and expected.current() == {"a:latest": "1"}


def test_the_listing_is_computed_once_on_load():
    calls = []
    expected = ExpectedFingerprints(lambda: calls.append(1) or {"a:latest": "1"})
    assert expected.state == ListingState.PENDING and expected.current() is None
    _load(expected)
    _load(expected)
    assert expected.current() == {"a:latest": "1"} and calls == [1]


@pytest.mark.parametrize("compute, message", [(lambda: (_ for _ in ()).throw(RuntimeError("no bash")), "no bash"), (lambda: {}, "no fingerprinted image")])
def test_a_failed_listing_leases_nothing_and_says_why(compute, message):
    expected = ExpectedFingerprints(compute)
    _load(expected)
    assert expected.state == ListingState.FAILED and expected.current() is None and message in expected.error


def test_the_listing_is_read_from_the_release(tmp_path):
    manifest = tmp_path / "release.json"
    images = {SCENARIO_EXECUTION_IMAGE: ReleaseImage("sha256:1", "fp-execution"), "postgres:16.10-alpine": ReleaseImage("sha256:2")}
    write_release(manifest, Release(name="scenegems", revision="abc", dirty=False, created_at="2026-10-25T12:00:00+00:00", images=images))
    expected = ExpectedFingerprints.of_release(manifest)
    _load(expected)
    assert expected.state == ListingState.READY and expected.current() == {SCENARIO_EXECUTION_IMAGE: "fp-execution"}


def test_without_a_release_nothing_is_leased_and_the_error_says_why(tmp_path):
    unset = ExpectedFingerprints.of_release(None)
    _load(unset)
    assert unset.state == ListingState.FAILED and "SCENEGEMS_RELEASE_MANIFEST" in unset.error
    missing = ExpectedFingerprints.of_release(tmp_path / "release.json")
    _load(missing)
    assert missing.state == ListingState.FAILED and "cannot read the release file" in missing.error


def test_a_submission_gets_the_fingerprints_of_its_images():
    submission = with_required_fingerprints(JobSubmission(job_type=JobType.SIMULATION_GAZEBO, payload={"simulation_layer": "gazebo"}), EXPECTED)
    assert submission.requirements.fingerprints == {SCENARIO_EXECUTION_IMAGE: "fp-execution", SITL_IMAGE: "fp-sitl", GAZEBO_IMAGE: "fp-gazebo"}


def test_a_submission_that_names_fingerprints_keeps_them():
    pinned = JobRequirements(fingerprints={MONITORING_IMAGE: "campaign-pin"}, labels={"site": "lab"})
    submission = JobSubmission(job_type=JobType.MONITORING_POST_HOC, requirements=pinned)
    assert with_required_fingerprints(submission, EXPECTED) is submission


def test_other_requirements_are_kept():
    submission = JobSubmission(job_type=JobType.SCENE_GENERATION, requirements=JobRequirements(labels={"site": "lab"}, min_memory_mb=100))
    required = with_required_fingerprints(submission, EXPECTED).requirements
    assert required.labels == {"site": "lab"} and required.min_memory_mb == 100 and required.fingerprints == {SCENE_GENERATION_IMAGE: "fp-scene"}


def test_node_mismatches_cover_the_images_of_its_capabilities_only():
    node = InMemoryNodeStore(ManualClock()).register(make_hello("n", slots={JobType.SCENE_GENERATION: 1}, fingerprints={SCENE_GENERATION_IMAGE: "fp-scene", MONITORING_IMAGE: "old"}))
    assert node_mismatches(node, EXPECTED) == []
    stale = InMemoryNodeStore(ManualClock()).register(make_hello("n", slots={JobType.MONITORING_POST_HOC: 1}, fingerprints={MONITORING_IMAGE: "old"}))
    assert [(mismatch.image, mismatch.actual) for mismatch in node_mismatches(stale, EXPECTED)] == [(MONITORING_IMAGE, "old")]


def _simulation_node(job_type, fingerprints):
    return InMemoryNodeStore(ManualClock()).register(make_hello("n", slots={job_type: 1}, fingerprints=fingerprints))


def test_a_gazebo_node_needs_the_gazebo_image_and_a_sitl_node_does_not():
    sitl_only = {SCENARIO_EXECUTION_IMAGE: "fp-execution", SITL_IMAGE: "fp-sitl"}
    assert node_mismatches(_simulation_node(JobType.SIMULATION_ARDUPILOT_SIM, sitl_only), EXPECTED) == []
    missing = node_mismatches(_simulation_node(JobType.SIMULATION_GAZEBO, sitl_only), EXPECTED)
    assert [(mismatch.image, mismatch.missing) for mismatch in missing] == [(GAZEBO_IMAGE, True)]
    stale = node_mismatches(_simulation_node(JobType.SIMULATION_GAZEBO, {**sitl_only, GAZEBO_IMAGE: "old"}), EXPECTED)
    assert [(mismatch.image, mismatch.actual) for mismatch in stale] == [(GAZEBO_IMAGE, "old")]
