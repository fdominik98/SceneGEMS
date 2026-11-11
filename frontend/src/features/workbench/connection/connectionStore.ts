import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { ClientToServerMessage } from "../../../domain/simulation/wireTypes";
import { CONTROL_NODE_BROKER_PRESET, type AttendedBroker, type MqttConnectionInfo, type MqttConnectionPresetKey } from "./connectionLibrary";
import { defaultReferenceGeofence, type ReferenceGeofence } from "./referenceGeofence";

export type MqttConnectionAttempt = "idle" | "connecting" | "connected" | "failed";

export interface ConnectionFormState {
  user: string;
  password: string;
  agentBroker: string;
  clientBroker: string;
  port: number;
  tlsConnection: boolean;
  allowCertificates: boolean;
  /** The profile in use; "" for a broker typed in by hand. */
  selectedPreset: MqttConnectionPresetKey | "";
  geofence: ReferenceGeofence;
  /**
   * True once the user explicitly clicked Disconnect. Not persisted: it suppresses
   * the hands-free auto-connect (including after a transient backend-socket
   * reconnect) until the user clicks Connect again.
   */
  userDisconnected: boolean;
  setUserDisconnected: (value: boolean) => void;
  /**
   * Outcome of the most recent Connect click. Not persisted: it exists so the panel
   * can report *why* a connection attempt failed, which the 1 Hz `mqtt_broker_status`
   * heartbeat cannot express (it only ever says connected or disconnected).
   */
  connectionAttempt: MqttConnectionAttempt;
  connectionError: string | null;
  beginConnectionAttempt: () => void;
  markConnectionSucceeded: () => void;
  markConnectionFailed: (error: string) => void;
  clearConnectionAttempt: () => void;
  setUser: (value: string) => void;
  setPassword: (value: string) => void;
  setAgentBroker: (value: string) => void;
  setClientBroker: (value: string) => void;
  setPort: (value: number) => void;
  setTlsConnection: (value: boolean) => void;
  setAllowCertificates: (value: boolean) => void;
  setSelectedPreset: (value: MqttConnectionPresetKey | "") => void;
  setGeofence: (value: ReferenceGeofence) => void;
  /** Apply a full preset's fields without touching the geofence. */
  applyConnection: (connection: MqttConnectionInfo) => void;
}

/** Fields written to local storage. `migrate` must return this shape, not the storage envelope. */
export type ConnectionPersisted = Pick<
  ConnectionFormState,
  | "user"
  | "password"
  | "agentBroker"
  | "clientBroker"
  | "port"
  | "tlsConnection"
  | "allowCertificates"
  | "selectedPreset"
  | "geofence"
>;

/** Profiles saved before v3, when the page was named after WARA-PS, and the profile each one is now. */
const LEGACY_PRESETS: Record<string, MqttConnectionPresetKey> = {
  // The compose broker and a host-published broker of the single-machine stack: the control node's broker took their place.
  local_mqtt_connection: "control_node_broker",
  host_mqtt_connection: "control_node_broker",
  live_mqtt_connection: "waraps_tls_broker",
};

/** The key of the control node broker's profile in v3, when the control node was called the master. */
const V3_CONTROL_NODE_BROKER_PRESET = "master_broker";

/**
 * Persisted MQTT broker form. Lives in a store (not component state) so both the
 * Connections page and the global auto-connect logic can read it.
 */
export const useConnectionStore = create<ConnectionFormState>()(
  persist(
    (set) => ({
      user: "",
      password: "",
      agentBroker: "",
      clientBroker: "",
      port: 1883,
      tlsConnection: false,
      allowCertificates: false,
      selectedPreset: CONTROL_NODE_BROKER_PRESET,
      geofence: defaultReferenceGeofence,
      userDisconnected: false,
      setUserDisconnected: (userDisconnected) => set({ userDisconnected }),
      connectionAttempt: "idle",
      connectionError: null,
      beginConnectionAttempt: () => set({ connectionAttempt: "connecting", connectionError: null }),
      markConnectionSucceeded: () => set({ connectionAttempt: "connected", connectionError: null }),
      markConnectionFailed: (connectionError) => set({ connectionAttempt: "failed", connectionError }),
      clearConnectionAttempt: () => set({ connectionAttempt: "idle", connectionError: null }),
      setUser: (user) => set({ user }),
      setPassword: (password) => set({ password }),
      setAgentBroker: (agentBroker) => set({ agentBroker }),
      setClientBroker: (clientBroker) => set({ clientBroker }),
      setPort: (port) => set({ port }),
      setTlsConnection: (tlsConnection) => set({ tlsConnection }),
      setAllowCertificates: (allowCertificates) => set({ allowCertificates }),
      setSelectedPreset: (selectedPreset) => set({ selectedPreset }),
      setGeofence: (geofence) => set({ geofence }),
      applyConnection: (connection) =>
        set({
          user: connection.user,
          password: connection.password,
          agentBroker: connection.agent_broker,
          clientBroker: connection.client_broker,
          port: connection.port,
          tlsConnection: connection.tls_connection,
          allowCertificates: connection.allow_certificates ?? false,
        }),
    }),
    {
      name: "scenegems:connection-form",
      version: 4,
      // Zustand calls this with the stored state object (already unwrapped) and merges
      // the return value onto the store. v3: the profiles of the single-machine stack are
      // gone; the control node's own broker replaces them and is the default. A hand-typed
      // address ("" profile) always survives. v4: the control node broker's profile has its
      // present key; under the v3 key the form would send the address fields left in it.
      migrate: (persistedState, version): ConnectionPersisted => {
        if (version >= 4 || !persistedState || typeof persistedState !== "object") {
          return persistedState as ConnectionPersisted;
        }
        const state = persistedState as Omit<ConnectionPersisted, "selectedPreset"> & { selectedPreset?: string };
        const preset = state.selectedPreset ?? "";
        if (version === 3) {
          const selectedPreset = preset === V3_CONTROL_NODE_BROKER_PRESET ? CONTROL_NODE_BROKER_PRESET : (preset as ConnectionPersisted["selectedPreset"]);
          return { ...state, selectedPreset };
        }
        return { ...state, selectedPreset: preset === "" ? "" : (LEGACY_PRESETS[preset] ?? CONTROL_NODE_BROKER_PRESET) };
      },
      partialize: (state): ConnectionPersisted => ({
        user: state.user,
        password: state.password,
        agentBroker: state.agentBroker,
        clientBroker: state.clientBroker,
        port: state.port,
        tlsConnection: state.tlsConnection,
        allowCertificates: state.allowCertificates,
        selectedPreset: state.selectedPreset,
        geofence: state.geofence,
      }),
    }
  )
);

type ConnectionFields = Pick<
  ConnectionFormState,
  "user" | "password" | "agentBroker" | "clientBroker" | "port" | "tlsConnection" | "allowCertificates" | "selectedPreset" | "geofence"
>;

/** Whether the form has enough to attempt a connection: the control node broker always does. */
export function connectionFormIsValid(state: ConnectionFields): boolean {
  if (state.selectedPreset === CONTROL_NODE_BROKER_PRESET) {
    return true;
  }
  return (
    state.agentBroker.trim().length > 0 &&
    state.clientBroker.trim().length > 0 &&
    Number.isInteger(state.port) &&
    state.port > 0 &&
    state.port <= 65535
  );
}

/** The connect message for the form: the control node broker by name, any other by its address. */
export function buildConnectMessage(state: ConnectionFields): ClientToServerMessage {
  return {
    type: "connect_to_mqtt_broker",
    user: state.user.trim(),
    password: state.password,
    agent_broker: state.agentBroker.trim(),
    client_broker: state.clientBroker.trim(),
    port: state.port,
    tls_connection: state.tlsConnection,
    allow_certificates: state.allowCertificates,
    geofence: state.geofence,
    use_control_node_broker: state.selectedPreset === CONTROL_NODE_BROKER_PRESET,
  };
}

/** The broker an attended run with a real vessel names in its job: none for the control node's own broker, any other by the address agents dial. */
export function attendedBroker(state: ConnectionFields): AttendedBroker | null {
  if (state.selectedPreset === CONTROL_NODE_BROKER_PRESET) {
    return null;
  }
  return {
    host: state.agentBroker.trim(),
    port: state.port,
    tls: state.tlsConnection,
    allow_certificates: state.allowCertificates,
    user: state.user.trim(),
    password: state.password,
  };
}
