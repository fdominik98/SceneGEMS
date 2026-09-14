export interface MqttConnectionInfo {
  user: string;
  password: string;
  agent_broker: string;
  client_broker: string;
  port: number;
  tls_connection: boolean;
  allow_certificates?: boolean;
}

export const live_mqtt_connection: MqttConnectionInfo = {
  user: "mqtt",
  password: "",
  agent_broker: "broker.waraps.org",
  client_broker: "broker.waraps.org",
  port: 8883,
  tls_connection: true,
};

export const local_mqtt_connection: MqttConnectionInfo = {
  user: "",
  password: "",
  agent_broker: "broker",
  client_broker: "broker",
  port: 1883,
  tls_connection: false,
};

/**
 * A broker published on the host rather than run inside the SceneGEMS compose project,
 * such as the `Local_Broker` container of the OTG stack (host port 1882). The backend
 * resolves `localhost` to the Docker host gateway, so this works from the container too.
 */
export const host_mqtt_connection: MqttConnectionInfo = {
  user: "",
  password: "",
  agent_broker: "localhost",
  client_broker: "localhost",
  port: 1882,
  tls_connection: false,
};

export const mqttConnectionLibrary = {
  live_mqtt_connection,
  local_mqtt_connection,
  host_mqtt_connection,
} as const;

export type MqttConnectionPresetKey = keyof typeof mqttConnectionLibrary;
