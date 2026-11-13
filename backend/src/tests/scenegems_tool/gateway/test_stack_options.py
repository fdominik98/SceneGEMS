"""stack_options: every resolver triple with the workbench label, availability, reason and capabilities, as plain JSON."""

import json

import pytest

from scenegems_tool.gateway.stack_options import stack_options_message


@pytest.fixture(scope="module")
def options():
    return stack_options_message()


def entry(options, simulator, asv, control):
    (found,) = [item for item in options["combinations"] if (item["simulatorType"], item["asvSystem"], item["controlLayer"]) == (simulator, asv, control)]
    return found


def test_every_triple_is_listed_once_with_the_choices(options):
    assert len(options["combinations"]) == 80
    assert options["simulatorTypes"] == ["Kinematic", "Gazebo", "ArduPilot Sim"]
    assert options["asvSystem"] == ["replay", "usv_navigation", "moos_ivp", "mission_planner", "on_board"]
    assert options["controlLayers"] == ["ardupilot", "custom", "none", "real_vessel"]


def test_a_real_vessel_offers_replay_mission_planner_and_on_board_software(options):
    real = {item["asvSystem"]: item for item in options["combinations"] if item["simulatorType"] == "Real vessel" and item["controlLayer"] == "real_vessel"}
    assert sorted(software for software, item in real.items() if item["available"]) == ["mission_planner", "on_board", "replay"]
    assert all(real[software]["interactiveOnly"] for software in ("mission_planner", "on_board", "replay"))
    assert "ArduAgent" in real["usv_navigation"]["reason"] and "ArduAgent" in real["moos_ivp"]["reason"]


def test_an_available_combination_carries_its_capabilities(options):
    item = entry(options, "Gazebo", "usv_navigation", "custom")
    assert item["available"] and item["status"] == "available" and item["reason"] == ""
    assert item["repeatabilityTier"] in ("exact", "bounded")


def test_moos_ivp_is_offered_where_usv_navigation_is(options):
    for simulator, control in (("Kinematic", "none"), ("Gazebo", "custom"), ("Gazebo", "ardupilot"), ("ArduPilot Sim", "ardupilot")):
        item = entry(options, simulator, "moos_ivp", control)
        assert item["available"] and not item["interactiveOnly"], (simulator, control)


def test_a_ruled_out_combination_carries_the_resolver_reason(options):
    item = entry(options, "Kinematic", "replay", "ardupilot")
    assert not item["available"]
    assert "integrates control internally" in item["reason"]
    assert item["repeatabilityTier"] is None


def test_mission_planner_is_marked_interactive(options):
    assert entry(options, "ArduPilot Sim", "mission_planner", "ardupilot")["interactiveOnly"]


def test_no_speed_limit_is_sent_as_unlimited_not_as_infinity(options):
    item = entry(options, "Kinematic", "replay", "none")
    assert item["maxSpeedup"] is None and item["speedupUnlimited"]
    json.dumps(options, allow_nan=False)
