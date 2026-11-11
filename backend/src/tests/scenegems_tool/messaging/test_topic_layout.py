"""The layout of agent topics: the WARA-PS one under the first level of the broker."""

import pytest

from scenegems_tool.messaging.topic_layout import CLUSTER_TOPIC_ROOT, SERVICE_TOPIC_LEVELS, WARAPS_TOPIC_ROOT, require_topic_root, service_topic


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
