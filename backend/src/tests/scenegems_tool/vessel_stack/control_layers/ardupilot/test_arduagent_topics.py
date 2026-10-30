"""ArduAgent's topics (deploy/images/arduagent/app): every topic from the effective base, under the optional prefix.

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
        for key in ("BASE_TOPIC", "OTHER_POSITIONS_TOPIC", "MQTT_TOPIC_PREFIX", "UUID"):
            monkeypatch.delenv(key, raising=False)
        for key, value in {**AGENT_ENVIRONMENT, **environment}.items():
            monkeypatch.setenv(key, value)
        sys.modules.pop(name, None)
        return importlib.import_module(name)

    yield load
    for name in ("agent_topics", "config"):
        sys.modules.pop(name, None)


def test_without_a_prefix_the_topics_are_the_unscoped_wara_ps_topics(arduagent_modules):
    config = arduagent_modules("config").AgentConfig
    assert config.TOPIC_PREFIX == ""
    assert config.BASE_TOPIC == "waraps/unit/surface/simulation/OS_0_SIM"
    assert config.COMMAND_TOPIC == "waraps/unit/surface/simulation/OS_0_SIM/exec/command"
    assert config.POSITION_TOPIC == "waraps/unit/surface/simulation/OS_0_SIM/sensor/position"
    assert config.OBSTACLE_DISTANCES_TOPIC == "waraps/unit/surface/simulation/OS_0_SIM/sensor/obstacle_distances"
    assert config.RC_OVERRIDE_TOPIC == "waraps/unit/surface/simulation/OS_0_SIM/sensor/rc_override"
    assert config.OTHER_POSITIONS_TOPIC == "waraps/unit/+/+/+/sensor/position"
    assert config.TOPICS.positions_root == "waraps/unit/"
    assert config.TOPICS.collision_avoidance_root == "waraps/unit/surface/simulation/"


def test_a_scoped_agent_publishes_and_subscribes_under_its_prefix(arduagent_modules):
    prefix = "scenegems/m1/workbench/live-ab12cd34/"
    config = arduagent_modules("config", MQTT_TOPIC_PREFIX=prefix).AgentConfig
    assert config.TOPIC_PREFIX == prefix
    assert config.BASE_TOPIC == f"{prefix}waraps/unit/surface/simulation/OS_0_SIM"
    assert config.COMMAND_TOPIC == f"{prefix}waraps/unit/surface/simulation/OS_0_SIM/exec/command"
    assert config.POSITION_TOPIC == f"{prefix}waraps/unit/surface/simulation/OS_0_SIM/sensor/position"
    assert config.OTHER_POSITIONS_TOPIC == f"{prefix}waraps/unit/+/+/+/sensor/position", "other agents' positions come from the same scope"
    assert config.TOPICS.is_position(f"{prefix}waraps/unit/surface/simulation/TS_1_SIM/sensor/position")
    assert not config.TOPICS.is_position("waraps/unit/surface/simulation/TS_1_SIM/sensor/position"), "another session's or WARA-PS's agents are not seen"


def test_the_base_topic_override_moves_every_topic_with_it(arduagent_modules):
    config = arduagent_modules("config", BASE_TOPIC="lab/boat").AgentConfig
    assert config.BASE_TOPIC == "lab/boat"
    assert config.COMMAND_TOPIC == "lab/boat/exec/command", "was computed from the default base before the override"
    assert config.POSITION_TOPIC == "lab/boat/sensor/position"
    assert config.OBSTACLE_DISTANCES_TOPIC == "lab/boat/sensor/obstacle_distances"
    assert config.RC_OVERRIDE_TOPIC == "lab/boat/sensor/rc_override"


def test_the_prefix_also_scopes_the_overrides(arduagent_modules):
    config = arduagent_modules("config", BASE_TOPIC="lab/boat", OTHER_POSITIONS_TOPIC="lab/+/sensor/position", MQTT_TOPIC_PREFIX="p/").AgentConfig
    assert config.COMMAND_TOPIC == "p/lab/boat/exec/command"
    assert config.OTHER_POSITIONS_TOPIC == "p/lab/+/sensor/position"


def test_the_uuid_override_is_kept(arduagent_modules):
    assert arduagent_modules("config", UUID="fixed").AgentConfig.UUID == "fixed"


def test_an_agent_whose_name_extends_this_one_is_not_this_agent(arduagent_modules):
    topics = arduagent_modules("agent_topics").AgentTopics.derive("surface", "simulation", "TS_1_SIM")
    assert topics.is_own("waraps/unit/surface/simulation/TS_1_SIM/sensor/position")
    assert not topics.is_own("waraps/unit/surface/simulation/TS_1_SIM2/sensor/position")


@pytest.mark.parametrize("prefix", ["no-slash", "/absolute/", "a/+/", "a/#/"])
def test_a_prefix_that_is_no_plain_topic_path_is_refused(arduagent_modules, prefix):
    agent_topics = arduagent_modules("agent_topics")
    with pytest.raises(ValueError, match="MQTT_TOPIC_PREFIX"):
        agent_topics.AgentTopics.derive("surface", "simulation", "OS_0_SIM", prefix=prefix)


def test_the_prefix_rule_matches_the_backend_topic_scope(arduagent_modules):
    """The backend hands ArduAgent the session's MQTT_TOPIC_PREFIX; both sides accept the same prefixes."""
    from scenegems_tool.messaging.topic_scope import TopicScope

    agent_topics = arduagent_modules("agent_topics")
    prefix = "scenegems/m1/workbench/live-ab12cd34/"
    assert agent_topics.AgentTopics.derive("surface", "simulation", "OS_0_SIM", prefix=prefix).base == TopicScope(prefix).apply("waraps/unit/surface/simulation/OS_0_SIM")
