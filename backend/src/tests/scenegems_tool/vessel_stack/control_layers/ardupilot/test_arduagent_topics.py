"""ArduAgent's topics (deploy/images/arduagent/app): every topic from the effective base, under the broker's first level.

agent_topics.py and config.py use the standard library only, so they load here without the
image's packages (dronekit, pymavlink); agent.py and mqtt_handler.py read the topics from config.
"""

import importlib
import sys
from pathlib import Path

import pytest

ARDUAGENT_APP = Path(__file__).resolve().parents[7] / "deploy" / "images" / "arduagent" / "app"
AGENT_ENVIRONMENT = {
    "DOMAIN": "surface",
    "REAL_SIM": "simulation",
    "NAME": "OS_0_SIM",
    "BROKER": "broker",
    "PORT": "1883",
    "TLS_CERTIFICE": "0",
    "BAUD_RATE": "57600",
}


@pytest.fixture
def arduagent_modules(monkeypatch):
    """Imports ArduAgent's modules fresh from the image folder, so config reads the environment set by the test."""
    monkeypatch.syspath_prepend(str(ARDUAGENT_APP))
    for name in ("agent_topics", "config"):
        monkeypatch.delitem(sys.modules, name, raising=False)

    def load(name: str, **environment: str):
        for key in ("BASE_TOPIC", "OTHER_POSITIONS_TOPIC", "OTHER_POSITIONS_TOPICS", "MQTT_TOPIC_ROOT", "MQTT_TOPIC_PREFIX", "UUID"):
            monkeypatch.delenv(key, raising=False)
        for key, value in {**AGENT_ENVIRONMENT, **environment}.items():
            monkeypatch.setenv(key, value)
        sys.modules.pop(name, None)
        return importlib.import_module(name)

    yield load
    for name in ("agent_topics", "config"):
        sys.modules.pop(name, None)


def test_by_default_the_topics_are_the_wara_ps_topics(arduagent_modules):
    config = arduagent_modules("config").AgentConfig
    assert config.BASE_TOPIC == "waraps/unit/surface/simulation/OS_0_SIM"
    assert config.COMMAND_TOPIC == "waraps/unit/surface/simulation/OS_0_SIM/exec/command"
    assert config.POSITION_TOPIC == "waraps/unit/surface/simulation/OS_0_SIM/sensor/position"
    assert config.OBSTACLE_DISTANCES_TOPIC == "waraps/unit/surface/simulation/OS_0_SIM/sensor/obstacle_distances"
    assert config.RC_OVERRIDE_TOPIC == "waraps/unit/surface/simulation/OS_0_SIM/sensor/rc_override"
    assert config.OTHER_POSITIONS_TOPIC == "waraps/unit/+/+/+/sensor/position"
    assert config.TOPICS.positions_root == "waraps/unit/"
    assert config.TOPICS.collision_avoidance_root == "waraps/unit/surface/simulation/"


def test_the_base_topic_override_moves_every_topic_with_it(arduagent_modules):
    config = arduagent_modules("config", BASE_TOPIC="lab/boat").AgentConfig
    assert config.BASE_TOPIC == "lab/boat"
    assert config.COMMAND_TOPIC == "lab/boat/exec/command", "was computed from the default base before the override"
    assert config.POSITION_TOPIC == "lab/boat/sensor/position"
    assert config.OBSTACLE_DISTANCES_TOPIC == "lab/boat/sensor/obstacle_distances"
    assert config.RC_OVERRIDE_TOPIC == "lab/boat/sensor/rc_override"


def test_the_other_positions_override_replaces_the_default_filter(arduagent_modules):
    config = arduagent_modules("config", BASE_TOPIC="lab/boat", OTHER_POSITIONS_TOPIC="lab/+/sensor/position").AgentConfig
    assert config.COMMAND_TOPIC == "lab/boat/exec/command"
    assert config.OTHER_POSITIONS_TOPIC == "lab/+/sensor/position" and config.TOPICS.other_position_filters == ("lab/+/sensor/position",)


def test_a_topic_prefix_is_not_read_any_more(arduagent_modules):
    """Runs are told apart by the names in their topics (OTHER_POSITIONS_TOPICS), so nothing is put in front of a topic."""
    config = arduagent_modules("config", MQTT_TOPIC_PREFIX="scenegems/m1/workbench/live-ab12cd34/").AgentConfig
    assert config.BASE_TOPIC == "waraps/unit/surface/simulation/OS_0_SIM" and not hasattr(config, "TOPIC_PREFIX")
    assert not hasattr(config.TOPICS, "prefix")


def test_the_uuid_override_is_kept(arduagent_modules):
    assert arduagent_modules("config", UUID="fixed").AgentConfig.UUID == "fixed"


def test_an_agent_whose_name_extends_this_one_is_not_this_agent(arduagent_modules):
    topics = arduagent_modules("agent_topics").AgentTopics.derive("surface", "simulation", "TS_1_SIM")
    assert topics.is_own("waraps/unit/surface/simulation/TS_1_SIM/sensor/position")
    assert not topics.is_own("waraps/unit/surface/simulation/TS_1_SIM2/sensor/position")


def test_the_topic_root_moves_every_topic_to_the_brokers_first_level(arduagent_modules):
    """On a control node's own broker the first level is scenegems; the layout below it is the WARA-PS one."""
    config = arduagent_modules("config", MQTT_TOPIC_ROOT="scenegems", NAME="os-265ca868").AgentConfig
    assert config.BASE_TOPIC == "scenegems/unit/surface/simulation/os-265ca868"
    assert config.COMMAND_TOPIC == "scenegems/unit/surface/simulation/os-265ca868/exec/command"
    assert config.OTHER_POSITIONS_TOPIC == "scenegems/unit/+/+/+/sensor/position"
    assert config.TOPICS.positions_root == "scenegems/unit/" and config.TOPICS.collision_avoidance_root == "scenegems/unit/surface/simulation/"
    assert not config.TOPICS.is_position("waraps/unit/surface/simulation/ts1/sensor/position"), "another root's units are not seen"


def test_named_agents_are_the_only_ones_whose_positions_are_taken(arduagent_modules):
    """The vessels of the agent's own run: two runs on one broker never see each other."""
    simulated = "scenegems/unit/surface/simulation/ts1-265ca868/sensor/position"
    real = "waraps/unit/surface/real/piraya/sensor/position"
    topics = arduagent_modules("config", MQTT_TOPIC_ROOT="scenegems", NAME="os-265ca868", OTHER_POSITIONS_TOPICS=f"{simulated}, {real}").AgentConfig.TOPICS
    assert topics.other_position_filters == (simulated, real) and topics.other_positions == simulated and topics.listed_positions
    assert topics.is_position(simulated) and topics.is_position(real)
    assert not topics.is_position("scenegems/unit/surface/simulation/ts1-99999999/sensor/position"), "another job's vessel of the same name"
    assert topics.is_collision_avoidance(simulated), "a simulated vessel of the run is avoided"
    assert not topics.is_collision_avoidance(real), "as before, only agents of the same domain and context are"


def test_without_named_agents_every_unit_under_the_root_is_taken_as_before(arduagent_modules):
    topics = arduagent_modules("agent_topics").AgentTopics.derive("surface", "simulation", "OS_0_SIM")
    assert topics.other_position_filters == ("waraps/unit/+/+/+/sensor/position",) and not topics.listed_positions
    assert topics.is_position("waraps/unit/air/real/drone/sensor/position") and not topics.is_collision_avoidance("waraps/unit/air/real/drone/sensor/position")
    assert topics.is_collision_avoidance("waraps/unit/surface/simulation/TS_1_SIM/sensor/position")


@pytest.mark.parametrize("root", ["a/b", "+", "scene#gems"])
def test_a_root_that_is_no_plain_level_is_refused(arduagent_modules, root):
    with pytest.raises(ValueError, match="MQTT_TOPIC_ROOT"):
        arduagent_modules("agent_topics").AgentTopics.derive("surface", "simulation", "os", root=root)


@pytest.mark.parametrize("topics", ["waraps/unit/+/+/+/sensor/position", "waraps/unit/surface/real/piraya"])
def test_named_agents_are_named_by_their_position_topics(arduagent_modules, topics):
    with pytest.raises(ValueError, match="OTHER_POSITIONS_TOPICS"):
        arduagent_modules("agent_topics").AgentTopics.derive("surface", "simulation", "os", other_positions_topics=topics)
