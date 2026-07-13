import paho.mqtt.enums as mqtt_enums
from dronekit import (  # type: ignore  # noqa: PGH003
    Vehicle,
    connect,
)
from paho.mqtt.client import Client as PahoClient

from config import MqttConfig, PixhawkConfig


class MqttConnection:
    def __init__(self) -> None:
        self.broker: str = MqttConfig.BROKER
        self.port: int = MqttConfig.PORT

        is_tls_connection: bool = self.port > 8800
        tls_cert: str = MqttConfig.TLS_CERTIFICE

        user: str = MqttConfig.MQTT_USER
        password: str = MqttConfig.MQTT_PASSWORD

        self.client: PahoClient = PahoClient(mqtt_enums.CallbackAPIVersion.VERSION1)

        if len(user) > 0 and len(password) > 0:
            self.client.username_pw_set(user, password)
        else:
            print("################################################################")
            print("No password or username, trying to connect to broker anyways...")
            print("################################################################")

        if is_tls_connection:
            self.client.tls_set(cert_reqs=tls_cert)
            self.client.tls_insecure_set(True)

        self.connect()

    def connect(self) -> None:
        self.client.connect(self.broker, self.port, 60)
        self.client.loop_start()

    def disconnect(self) -> None:
        self.client.disconnect()
        self.client.loop_stop()

    def on_connect(self, client, userdata, flags, rc) -> None:
        if rc == 0:
            print(
                f"Connected to MQTT Broker: {self.connection.broker}:{self.connection.port}"
            )
        elif rc == 5:
            print(
                f"Wrong Credentials for {self.connection.broker}:{self.connection.port}"
            )
        else:
            print(f"Error to connect : {rc}")


class MAVLinkConnection:
    def __init__(self) -> None:
        # self.connection_string: str = PixhawkConfig.CONNECTION_STRING
        # self.baud_rate: int = PixhawkConfig.BAUD_RATE

        self.connection_string = PixhawkConfig.CONNECTION_STRING
        self.baud_rate = PixhawkConfig.BAUD_RATE

        # Connect to the Vehicle.
        print(f"Connecting to vehicle on: {self.connection_string}")
        self.vehicle : Vehicle = connect(
            self.connection_string, wait_ready=True, baud=self.baud_rate
        )
