export interface MqttConnectionInfo {
  user: string;
  password: string;
  /** The broker's host as the containers of a simulation dial it. */
  agent_broker: string;
  port: number;
  tls_connection: boolean;
  allow_certificates?: boolean;
}

/**
 * The broker profiles of the Connections page. The control node's own broker is the default: a
 * simulation job on a worker node already knows it, so a job names no broker then. Any other
 * broker is an external one, which an attended job with a real vessel names by its address.
 */
export type MqttConnectionPresetKey = "control_node_broker" | "waraps_tls_broker";

export const CONTROL_NODE_BROKER_PRESET = "control_node_broker" satisfies MqttConnectionPresetKey;

/** The public broker of broker.waraps.org, over TLS, where real vessels and external agents meet. */
export const waraps_tls_broker: MqttConnectionInfo = {
  user: "mqtt",
  password: "",
  agent_broker: "broker.waraps.org",
  port: 8883,
  tls_connection: true,
};

/** The fields a profile fills in; the control node broker has none of its own. */
export const mqttConnectionLibrary: Record<Exclude<MqttConnectionPresetKey, "control_node_broker">, MqttConnectionInfo> = {
  waraps_tls_broker,
};

export const PRESET_LABELS: Record<MqttConnectionPresetKey | "", string> = {
  control_node_broker: "Control node broker (default)",
  waraps_tls_broker: "broker.waraps.org over TLS",
  "": "Other broker",
};

/**
 * The broker of an attended run with a real vessel, as the job's payload names it (`attended_runner.BrokerPayload`): the
 * address the vessels' agents dial. A run on the control node's own broker names none.
 */
export interface AttendedBroker {
  host: string;
  port: number;
  tls: boolean;
  allow_certificates: boolean;
  user: string;
  password: string;
}
