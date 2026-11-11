"""The layout of agent topics: the WARA-PS one under the first level of the broker."""

import pytest

from scenegems_tool.messaging.topic_layout import CLUSTER_TOPIC_ROOT, SERVICE_TOPIC_LEVELS, WARAPS_TOPIC_ROOT, UnitTopic, parse_unit_topic, require_topic_root, service_topic, unit_topic


def test_a_service_topic_follows_the_waraps_layout_under_the_brokers_root():
    assert service_topic(CLUSTER_TOPIC_ROOT, "scene-generation-subsystem-1") == "scenegems/service/virtual/real/scene-generation-subsystem-1"
    assert service_topic(WARAPS_TOPIC_ROOT, "simulation-subsystem-265ca868") == "waraps/service/virtual/real/simulation-subsystem-265ca868"
    assert len(service_topic(CLUSTER_TOPIC_ROOT, "name").split("/")) == SERVICE_TOPIC_LEVELS


def test_a_cluster_topic_has_no_level_for_where_the_service_runs():
    topic = service_topic(CLUSTER_TOPIC_ROOT, "trajectory-generation-subsystem-2")
    assert topic.split("/")[:4] == ["scenegems", "service", "virtual", "real"], "the root, then the agent API's levels, then the name"


@pytest.mark.parametrize("root", ["", "scenegems/local", "+", "scene#gems"])
def test_a_topic_root_is_one_plain_level(root):
    with pytest.raises(ValueError):
        require_topic_root(root)


@pytest.mark.parametrize("name", ["", "a/b", "+", "name#"])
def test_a_service_name_is_one_plain_level(name):
    with pytest.raises(ValueError):
        service_topic(CLUSTER_TOPIC_ROOT, name)


def test_a_vessels_topic_is_a_unit_of_the_surface_domain_under_the_brokers_root():
    assert unit_topic(CLUSTER_TOPIC_ROOT, "simulation", "os-265ca868") == "scenegems/unit/surface/simulation/os-265ca868"
    assert unit_topic(WARAPS_TOPIC_ROOT, "real", "piraya") == "waraps/unit/surface/real/piraya"


@pytest.mark.parametrize("context, name", [("virtual", "os"), ("simulation", ""), ("simulation", "a/b"), ("real", "+")])
def test_a_unit_is_real_or_simulated_and_its_name_one_plain_level(context, name):
    with pytest.raises(ValueError):
        unit_topic(CLUSTER_TOPIC_ROOT, context, name)


def test_a_unit_topic_is_read_back_level_by_level():
    assert parse_unit_topic("scenegems/unit/surface/simulation/os-265ca868") == UnitTopic("scenegems", "surface", "simulation", "os-265ca868")
    assert parse_unit_topic("waraps/unit/air/real/drone1") == UnitTopic("waraps", "air", "real", "drone1")


@pytest.mark.parametrize(
    "topic",
    [
        "",
        "lab/boat",
        "waraps/unit/surface/os",
        "waraps/service/virtual/real/name",
        "waraps/unit/surface/virtual/os",
        "waraps/unit/surface/real/os/sensor",
        "waraps/unit/+/real/os",
        "waraps/unit/surface/real/",
    ],
)
def test_a_topic_outside_the_unit_layout_is_no_unit(topic):
    assert parse_unit_topic(topic) is None
