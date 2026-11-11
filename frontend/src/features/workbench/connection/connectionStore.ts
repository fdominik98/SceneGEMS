import { create } from "zustand";
import { persist } from "zustand/middleware";
import { CONTROL_NODE_BROKER_PRESET, type AttendedBroker, type MqttConnectionInfo, type MqttConnectionPresetKey } from "./connectionLibrary";
import { defaultReferenceGeofence, type ReferenceGeofence } from "./referenceGeofence";

export interface ConnectionFormState {
  user: string;
  password: string;
  /** The broker's host as the containers of a simulation on a worker node dial it. */
  agentBroker: string;
  port: number;
  tlsConnection: boolean;
  allowCertificates: boolean;
  /** The profile in use; "" for a broker typed in by hand. */
  selectedPreset: MqttConnectionPresetKey | "";
  geofence: ReferenceGeofence;
  setUser: (value: string) => void;
  setPassword: (value: string) => void;
  setAgentBroker: (value: string) => void;
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
  "user" | "password" | "agentBroker" | "port" | "tlsConnection" | "allowCertificates" | "selectedPreset" | "geofence"
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

/** What versions before v5 stored: also the broker's host as the control node dialled it, which nothing dials any more. */
type StoredBeforeV5 = Omit<ConnectionPersisted, "selectedPreset"> & { selectedPreset?: string; clientBroker?: string };

/** The profile a stored key names today. */
function presetOf(version: number, preset: string): ConnectionPersisted["selectedPreset"] {
  if (version >= 4) {
    return preset as ConnectionPersisted["selectedPreset"];
  }
  if (version === 3) {
    return preset === V3_CONTROL_NODE_BROKER_PRESET ? CONTROL_NODE_BROKER_PRESET : (preset as ConnectionPersisted["selectedPreset"]);
  }
  return preset === "" ? "" : (LEGACY_PRESETS[preset] ?? CONTROL_NODE_BROKER_PRESET);
}

/**
 * The MQTT broker and the reference area of the simulations an operator sets up, persisted. Nothing
 * connects from the console: an attended simulation job with a real vessel names the broker
 * (`attendedBroker`), and every simulation job takes the reference area.
 */
export const useConnectionStore = create<ConnectionFormState>()(
  persist(
    (set) => ({
      user: "",
      password: "",
      agentBroker: "",
      port: 1883,
      tlsConnection: false,
      allowCertificates: false,
      selectedPreset: CONTROL_NODE_BROKER_PRESET,
      geofence: defaultReferenceGeofence,
      setUser: (user) => set({ user }),
      setPassword: (password) => set({ password }),
      setAgentBroker: (agentBroker) => set({ agentBroker }),
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
          port: connection.port,
          tlsConnection: connection.tls_connection,
          allowCertificates: connection.allow_certificates ?? false,
        }),
    }),
    {
      name: "scenegems:connection-form",
      version: 5,
      // Zustand calls this with the stored state object (already unwrapped) and merges
      // the return value onto the store. v3: the profiles of the single-machine stack are
      // gone; the control node's own broker replaces them and is the default. A hand-typed
      // address ("" profile) always survives. v4: the control node broker's profile has its
      // present key. v5: the host as the control node dialled it is gone (the control node
      // connects to no broker for the console); it becomes the containers' host where that was empty.
      migrate: (persistedState, version): ConnectionPersisted => {
        if (version >= 5 || !persistedState || typeof persistedState !== "object") {
          return persistedState as ConnectionPersisted;
        }
        const { clientBroker, selectedPreset, ...state } = persistedState as StoredBeforeV5;
        const agentBroker = (state.agentBroker ?? "").trim().length > 0 ? state.agentBroker : (clientBroker ?? "");
        return { ...state, agentBroker, selectedPreset: presetOf(version, selectedPreset ?? "") };
      },
      partialize: (state): ConnectionPersisted => ({
        user: state.user,
        password: state.password,
        agentBroker: state.agentBroker,
        port: state.port,
        tlsConnection: state.tlsConnection,
        allowCertificates: state.allowCertificates,
        selectedPreset: state.selectedPreset,
        geofence: state.geofence,
      }),
    }
  )
);

type ConnectionFields = Pick<ConnectionFormState, "user" | "password" | "agentBroker" | "port" | "tlsConnection" | "allowCertificates" | "selectedPreset">;

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
