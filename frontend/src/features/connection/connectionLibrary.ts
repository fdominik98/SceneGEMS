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

export const mqttConnectionLibrary = {
  live_mqtt_connection,
  local_mqtt_connection,
} as const;

export type MqttConnectionPresetKey = keyof typeof mqttConnectionLibrary;
