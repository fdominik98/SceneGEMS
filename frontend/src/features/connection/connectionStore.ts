import { create } from "zustand";
import { persist } from "zustand/middleware";
import {
  local_mqtt_connection,
  type MqttConnectionInfo,
  type MqttConnectionPresetKey,
} from "./connectionLibrary";
import { defaultReferenceGeofence, type ReferenceGeofence } from "./referenceGeofence";

const DEFAULT_PRESET: MqttConnectionPresetKey = "local_mqtt_connection";

export interface ConnectionFormState {
  user: string;
  password: string;
  agentBroker: string;
  clientBroker: string;
  port: number;
  tlsConnection: boolean;
  allowCertificates: boolean;
  selectedPreset: MqttConnectionPresetKey | "";
  geofence: ReferenceGeofence;
  /**
   * True once the user explicitly clicked Disconnect. Not persisted: it suppresses
   * the hands-free auto-connect (including after a transient backend-socket
   * reconnect) until the user clicks Connect again.
   */
  userDisconnectedWaraps: boolean;
  setUserDisconnectedWaraps: (value: boolean) => void;
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

/**
 * Persisted WARA-PS connection form. Lives in a store (not component state) so
 * both the connection panel and the global auto-connect logic can read it.
 */
export const useConnectionStore = create<ConnectionFormState>()(
  persist(
    (set) => ({
      user: local_mqtt_connection.user,
      password: local_mqtt_connection.password,
      agentBroker: local_mqtt_connection.agent_broker,
      clientBroker: local_mqtt_connection.client_broker,
      port: local_mqtt_connection.port,
      tlsConnection: local_mqtt_connection.tls_connection,
      allowCertificates: local_mqtt_connection.allow_certificates ?? false,
      selectedPreset: DEFAULT_PRESET,
      geofence: defaultReferenceGeofence,
      userDisconnectedWaraps: false,
      setUserDisconnectedWaraps: (userDisconnectedWaraps) => set({ userDisconnectedWaraps }),
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
      version: 2,
      migrate: (persistedState, version) => {
        if (version >= 2 || !persistedState || typeof persistedState !== "object") {
          return persistedState as ConnectionFormState;
        }
        const envelope = persistedState as { state?: ConnectionFormState };
        const state = envelope.state ?? (persistedState as ConnectionFormState);
        const staleLocal =
          state.clientBroker === "localhost" ||
          state.clientBroker === "host.docker.internal" ||
          state.agentBroker === "host.docker.internal" ||
          state.port === 1882;
        if (!staleLocal && state.selectedPreset !== "local_mqtt_connection") {
          return persistedState as ConnectionFormState;
        }
        const migrated = {
          ...state,
          agentBroker: local_mqtt_connection.agent_broker,
          clientBroker: local_mqtt_connection.client_broker,
          port: local_mqtt_connection.port,
          tlsConnection: local_mqtt_connection.tls_connection,
        };
        return envelope.state !== undefined ? { ...envelope, state: migrated } : migrated;
      },
      partialize: (state) => ({
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

/** Whether the current form has enough info to attempt a WARA-PS connection. */
export function connectionFormIsValid(state: ConnectionFormState): boolean {
  return (
    state.agentBroker.trim().length > 0 &&
    state.clientBroker.trim().length > 0 &&
    Number.isInteger(state.port) &&
    state.port > 0 &&
    state.port <= 65535
  );
}
