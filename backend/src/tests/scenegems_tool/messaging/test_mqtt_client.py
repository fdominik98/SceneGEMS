import ssl

import paho.mqtt.client as mqtt
import pytest

from scenegems_tool.messaging import mqtt_client
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo, resolve_mqtt_broker_endpoints


class _RecordingClient:
    """Stands in for a paho client and records the connection setup calls."""

    def __init__(self):
        self.calls = []

    def username_pw_set(self, username, password):
        self.calls.append(("username_pw_set", username, password))

    def tls_set(self, **kwargs):
        self.calls.append(("tls_set", kwargs))

    def tls_insecure_set(self, value):
        self.calls.append(("tls_insecure_set", value))


def _info(**overrides):
    values = dict(user="", password="", agent_broker="broker", client_broker="broker", port=1883, tls_connection=False, allow_certificates=False)
    values.update(overrides)
    return MQttConnectionInfo(**values)


def test_plain_anonymous_connection_sets_nothing():
    client = _RecordingClient()
    _info().apply_to(client)
    assert client.calls == []


def test_credentials_are_set_when_given():
    client = _RecordingClient()
    _info(user="lab-1", password="pw").apply_to(client)
    assert client.calls == [("username_pw_set", "lab-1", "pw")]


def test_cluster_tls_verifies_the_broker_against_the_ca():
    client = _RecordingClient()
    _info(user="lab-1", password="pw", port=8883, tls_connection=True, ca_certificate_path="/var/lib/scenegems/ca.pem").apply_to(client)
    assert client.calls == [("username_pw_set", "lab-1", "pw"), ("tls_set", {"ca_certs": "/var/lib/scenegems/ca.pem", "cert_reqs": ssl.CERT_REQUIRED})]


@pytest.mark.parametrize("allow_certificates,requirement", [(False, ssl.CERT_REQUIRED), (True, ssl.CERT_NONE)])
def test_tls_without_a_ca_keeps_the_workbench_behaviour(allow_certificates, requirement):
    client = _RecordingClient()
    _info(port=8883, tls_connection=True, allow_certificates=allow_certificates).apply_to(client)
    assert client.calls == [("tls_set", {"cert_reqs": requirement}), ("tls_insecure_set", True)]


def _self_signed_ca_pem() -> bytes:
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "lab-ca")])
    now = datetime.datetime.now(datetime.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return certificate.public_bytes(serialization.Encoding.PEM)


def test_ca_on_a_real_paho_client_enables_host_name_checks(tmp_path):
    ca_path = tmp_path / "ca.pem"
    ca_path.write_bytes(_self_signed_ca_pem())
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="t")
    _info(tls_connection=True, ca_certificate_path=str(ca_path)).apply_to(client)
    context = client._ssl_context
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname


def test_from_environment_reads_the_subsystem_variables():
    info = MQttConnectionInfo.from_environment({"MQTT_BROKER": "192.168.1.10", "MQTT_PORT": "8883", "MQTT_USER": "lab-1", "MQTT_PASSWORD": "pw", "MQTT_TLS": "true", "MQTT_CA_CERTIFICATE": "/ca.pem"})
    assert (info.client_broker, info.agent_broker, info.port, info.user, info.password) == ("192.168.1.10", "192.168.1.10", 8883, "lab-1", "pw")
    assert info.tls_connection and not info.allow_certificates and info.ca_certificate_path == "/ca.pem"


def test_from_environment_defaults_to_plain_without_ca():
    info = MQttConnectionInfo.from_environment({"MQTT_BROKER": "broker", "MQTT_PORT": "1883"})
    assert not info.tls_connection and info.ca_certificate_path is None and info.user == ""


def test_repr_hides_the_password():
    assert "secret-pw" not in repr(_info(password="secret-pw"))


@pytest.fixture
def in_container(monkeypatch):
    monkeypatch.setattr(mqtt_client, "_running_in_container", lambda: True)


@pytest.mark.parametrize("loopback", ["localhost", "127.0.0.1", "::1", " LocalHost "])
def test_a_loopback_broker_is_the_master_machine_from_its_container(in_container, loopback):
    assert resolve_mqtt_broker_endpoints(loopback, loopback, 1882, tls_connection=False) == ("host.docker.internal", "host.docker.internal", 1882)


def test_other_brokers_and_the_port_stay_as_typed(in_container):
    assert resolve_mqtt_broker_endpoints(" 10.0.0.5 ", "broker", 1883, tls_connection=False) == ("10.0.0.5", "broker", 1883)


def test_a_tls_broker_keeps_its_name(in_container):
    assert resolve_mqtt_broker_endpoints("localhost", "localhost", 8883, tls_connection=True) == ("localhost", "localhost", 8883)


def test_outside_a_container_loopback_stays(monkeypatch):
    monkeypatch.setattr(mqtt_client, "_running_in_container", lambda: False)
    assert resolve_mqtt_broker_endpoints("localhost", "127.0.0.1", 1883, tls_connection=False) == ("localhost", "127.0.0.1", 1883)
