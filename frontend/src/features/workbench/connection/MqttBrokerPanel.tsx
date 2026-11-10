import { useCallback } from "react";
import { useSelectedCluster } from "../../../domain/cluster/clusterStore";
import { Disclosure } from "../../../components/Disclosure";
import { PageHeader } from "../../../components/PageHeader";
import { usePlaybackStore } from "../../../domain/playback/playbackStore";
import type { ClientToServerMessage } from "../../../domain/simulation/wireTypes";
import {
  CONTROL_NODE_BROKER_PRESET,
  mqttConnectionLibrary,
  PRESET_LABELS,
  type MqttConnectionPresetKey,
} from "./connectionLibrary";
import { buildConnectMessage, connectionFormIsValid, useConnectionStore } from "./connectionStore";
import { useControlNodeStatus } from "../../cluster/useControlNodeStatus";
import { connectionHints, liveSessionsOffNote } from "./connectionHints";
import { ReferenceGeofenceMap } from "./ReferenceGeofenceMap";

interface MqttBrokerPanelProps {
  sendMessage: (message: ClientToServerMessage) => void;
}

const PRESET_ORDER: (MqttConnectionPresetKey | "")[] = ["control_node_broker", "waraps_tls_broker", ""];

/**
 * The Connections page: the MQTT broker the workbench's live simulations run over. Simulated
 * vessels, ArduAgent, real vessels and the live monitor meet there. Scene and trajectory
 * generation run as jobs on the active cluster and do not need it.
 */
export function MqttBrokerPanel({ sendMessage }: MqttBrokerPanelProps) {
  const streamStatus = usePlaybackStore((s) => s.streamStatus);
  const brokerStatus = usePlaybackStore((s) => s.mqttBrokerStatus);
  const controlNodeBroker = usePlaybackStore((s) => s.controlNodeBroker);
  const monitorStatus = usePlaybackStore((s) => s.monitorStatus);

  const form = useConnectionStore();
  const {
    selectedPreset,
    geofence,
    connectionAttempt,
    connectionError,
    setSelectedPreset,
    applyConnection,
    setGeofence,
    setUserDisconnected,
    beginConnectionAttempt,
    clearConnectionAttempt,
  } = form;
  const usesControlNode = selectedPreset === CONTROL_NODE_BROKER_PRESET;
  const controlNodeStatus = useControlNodeStatus(useSelectedCluster()?.operatorUrl ?? null);
  const liveSessionsOff = liveSessionsOffNote(controlNodeStatus.data?.live_sessions);

  const choosePreset = useCallback(
    (preset: MqttConnectionPresetKey | "") => {
      setSelectedPreset(preset);
      if (preset !== "" && preset !== CONTROL_NODE_BROKER_PRESET) {
        applyConnection(mqttConnectionLibrary[preset]);
      }
    },
    [applyConnection, setSelectedPreset]
  );

  const connected = brokerStatus === "connected";
  const controlNodeMissing = usesControlNode && streamStatus === "connected" && controlNodeBroker === null;
  const canConnect = streamStatus === "connected" && connectionFormIsValid(form) && !controlNodeMissing && liveSessionsOff === null;
  const target = usesControlNode ? (controlNodeBroker ?? "the control node broker") : `${form.clientBroker || "no broker"}:${form.port}${form.tlsConnection ? ", TLS" : ""}`;

  const connect = () => {
    setUserDisconnected(false);
    beginConnectionAttempt();
    sendMessage(buildConnectMessage(form));
  };
  const disconnect = () => {
    setUserDisconnected(true);
    clearConnectionAttempt();
    sendMessage({ type: "disconnect_from_mqtt_broker" });
  };

  return (
    <div className="mqtt-broker-layout">
      <PageHeader
        title="Connections"
        description="The MQTT broker live simulations run over: simulated vessels, ArduAgent, real vessels and the live monitor meet there. Scene and trajectory generation run on the cluster and do not need it."
        meta={
          <p className="mqtt-broker-status-row">
            <span className="meta">
              Server: <span className={`status-text ${streamStatus}`}>{streamStatus}</span>
            </span>
            <span className="meta">
              MQTT broker: <span className={`status-text ${brokerStatus}`}>{connected ? `connected to ${target}` : brokerStatus}</span>
            </span>
            {connected ? (
              <span className="meta">
                Live monitor: <span className={`status-text ${monitorStatus}`}>{monitorStatus}</span>
              </span>
            ) : null}
          </p>
        }
        actions={
          connected ? (
            <button disabled={streamStatus !== "connected"} onClick={disconnect}>
              Disconnect
            </button>
          ) : (
            <button className="primary-btn accent" disabled={!canConnect} onClick={connect}>
              {connectionAttempt === "connecting" ? "Connecting..." : "Connect"}
            </button>
          )
        }
      />

      {liveSessionsOff && (
        <p className="meta warning" role="status">
          {liveSessionsOff}
        </p>
      )}

      {connectionAttempt === "failed" && connectionError && (
        <div className="mqtt-broker-connection-error" role="alert">
          <p className="error">{connectionError}</p>
          <Disclosure id="mqtt-broker:error-hints" variant="link" headingLevel={null} title="What to check" openTitle="Hide the checks" defaultOpen>
            <ul className="meta">
              {connectionHints(usesControlNode, form.clientBroker, form.port, form.tlsConnection).map((hint) => (
                <li key={hint}>{hint}</li>
              ))}
            </ul>
          </Disclosure>
        </div>
      )}

      <section className="panel mqtt-broker-panel">
        <label className="field">
          <span>Broker</span>
          <select value={selectedPreset} onChange={(e) => choosePreset(e.target.value as MqttConnectionPresetKey | "")}>
            {PRESET_ORDER.map((preset) => (
              <option key={preset || "other"} value={preset}>
                {PRESET_LABELS[preset]}
              </option>
            ))}
          </select>
        </label>
        {usesControlNode ? (
          <p className="meta">
            {controlNodeBroker === null
              ? streamStatus === "connected"
                ? "This server has no control node broker. Choose another broker."
                : "The control node names its broker once the server is connected."
              : `The control node's own broker, ${controlNodeBroker}: plain MQTT on the cluster's VPN. A real vessel must reach the control node over the VPN to join.`}
          </p>
        ) : (
          <p className="meta">{target}</p>
        )}
      </section>

      {!usesControlNode && (
        <Disclosure id="mqtt-broker:details" title="Broker address" hint="User, brokers, port, TLS" defaultOpen={selectedPreset === ""} headingLevel={3}>
          <BrokerAddressFields />
        </Disclosure>
      )}

      <Disclosure
        id="mqtt-broker:geofence"
        title="Reference area (geofence)"
        hint={`${geofence.latitude.toFixed(4)}, ${geofence.longitude.toFixed(4)}, ${Math.round(geofence.radius_meters)} m`}
        headingLevel={3}
      >
        <p className="meta">Where the scenario's local frame lies on the map: vessels and agents report positions in WGS84.</p>
        <ReferenceGeofenceMap embedded geofence={geofence} onGeofenceChange={setGeofence} />
      </Disclosure>
    </div>
  );
}

function BrokerAddressFields() {
  const form = useConnectionStore();
  const markCustom = () => form.setSelectedPreset("");
  return (
    <div className="mqtt-broker-panel">
      <label className="field">
        <span>User</span>
        <input value={form.user} onChange={(e) => form.setUser(e.target.value)} placeholder="username" />
      </label>
      <label className="field">
        <span>Password</span>
        <input type="password" value={form.password} onChange={(e) => form.setPassword(e.target.value)} placeholder="password" />
      </label>
      <label className="field">
        <span>Broker host (as the server dials it)</span>
        <input
          value={form.clientBroker}
          onChange={(e) => {
            markCustom();
            form.setClientBroker(e.target.value);
          }}
          placeholder="broker.example.org"
        />
      </label>
      <label className="field">
        <span>Broker host (as the simulation's containers dial it)</span>
        <input
          value={form.agentBroker}
          onChange={(e) => {
            markCustom();
            form.setAgentBroker(e.target.value);
          }}
          placeholder="usually the same host"
        />
      </label>
      <label className="field">
        <span>Port</span>
        <input
          type="number"
          value={form.port}
          onChange={(e) => {
            markCustom();
            form.setPort(Number(e.target.value));
          }}
          min={1}
          max={65535}
        />
      </label>
      <div className="mqtt-broker-options">
        <label className="check">
          <input type="checkbox" checked={form.tlsConnection} onChange={(e) => form.setTlsConnection(e.target.checked)} />
          <span>TLS connection</span>
        </label>
        <label className="check">
          <input type="checkbox" checked={form.allowCertificates} onChange={(e) => form.setAllowCertificates(e.target.checked)} />
          <span>Allow certificates</span>
        </label>
      </div>
    </div>
  );
}
