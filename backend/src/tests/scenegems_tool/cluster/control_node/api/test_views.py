"""What the operator API shows of a job: its payload without the secrets in it."""

from scenegems_tool.cluster.control_node.api.views import MASKED, payload_without_secrets


def test_the_password_of_an_attended_runs_broker_is_not_shown():
    broker = {"host": "broker.waraps.org", "port": 8883, "tls": True, "user": "lab", "password": "secret"}
    payload = {"runner": "attended", "simulation": {"simulatorType": "ArduPilot Sim"}, "broker": broker}
    shown = payload_without_secrets(payload)
    assert shown["broker"] == {**broker, "password": MASKED} and shown["simulation"] == payload["simulation"]
    assert payload["broker"]["password"] == "secret", "the job keeps what it was given"


def test_a_payload_without_a_broker_password_is_shown_as_it_is():
    for payload in ({"runner": "kinematic", "seed": 1}, {"runner": "attended", "broker": {"host": "broker", "port": 1883, "password": ""}}, {"broker": None}, None):
        assert payload_without_secrets(payload) is payload
