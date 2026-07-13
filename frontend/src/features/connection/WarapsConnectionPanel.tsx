import { useEffect } from "react";
import { useUiStore } from "../../app/uiStore";
import {
  getCurrentFrame,
  usePlaybackStore,
} from "../../domain/playback/playbackStore";
import type { ClientToServerMessage } from "../../domain/simulation/wireTypes";
import { mqttConnectionLibrary, type MqttConnectionPresetKey } from "./connectionLibrary";
import { useConnectionStore } from "./connectionStore";
import { ReferenceGeofenceMap } from "./ReferenceGeofenceMap";

interface WarapsConnectionPanelProps {
  sendMessage: (message: ClientToServerMessage) => void;
}

export function WarapsConnectionPanel({ sendMessage }: WarapsConnectionPanelProps) {
  const previewFrame = usePlaybackStore((s) => getCurrentFrame(s));
  const streamStatus = usePlaybackStore((s) => s.streamStatus);
  const warapsStatus = usePlaybackStore((s) => s.warapsStatus);

  const user = useConnectionStore((s) => s.user);
  const password = useConnectionStore((s) => s.password);
  const agentBroker = useConnectionStore((s) => s.agentBroker);
  const clientBroker = useConnectionStore((s) => s.clientBroker);
  const port = useConnectionStore((s) => s.port);
  const tlsConnection = useConnectionStore((s) => s.tlsConnection);
  const allowCertificates = useConnectionStore((s) => s.allowCertificates);
  const selectedPreset = useConnectionStore((s) => s.selectedPreset);
  const geofence = useConnectionStore((s) => s.geofence);
  const setUser = useConnectionStore((s) => s.setUser);
  const setPassword = useConnectionStore((s) => s.setPassword);
  const setAgentBroker = useConnectionStore((s) => s.setAgentBroker);
  const setClientBroker = useConnectionStore((s) => s.setClientBroker);
  const setPort = useConnectionStore((s) => s.setPort);
  const setTlsConnection = useConnectionStore((s) => s.setTlsConnection);
  const setAllowCertificates = useConnectionStore((s) => s.setAllowCertificates);
  const setSelectedPreset = useConnectionStore((s) => s.setSelectedPreset);
  const setGeofence = useConnectionStore((s) => s.setGeofence);
  const applyConnection = useConnectionStore((s) => s.applyConnection);

  const setReferenceGeofence = useUiStore((s) => s.setReferenceGeofence);
  useEffect(() => {
    setReferenceGeofence(geofence);
  }, [geofence, setReferenceGeofence]);

  const canSubmit =
    streamStatus === "connected" &&
    agentBroker.trim().length > 0 &&
    clientBroker.trim().length > 0 &&
    Number.isInteger(port) &&
    port > 0 &&
    port <= 65535;

  return (
    <div className="waraps-layout">
      <div className="waraps-layout__form">
      <section className="panel waraps-panel">
        <h3>Connect to WARA-PS</h3>
        <div className="waraps-status-row">
          <p className="meta">
            Backend socket:{" "}
            <span className={`status-text ${streamStatus}`}>{streamStatus}</span>
          </p>
          <p className="meta">
            WARA-PS status:{" "}
            <span className={`status-text ${warapsStatus}`}>{warapsStatus}</span>
          </p>
        </div>
        <label className="field">
          <span>Connection profile</span>
          <select
            value={selectedPreset}
            onChange={(e) => {
              const preset = e.target.value as MqttConnectionPresetKey | "";
              setSelectedPreset(preset);
              if (!preset) {
                return;
              }
              applyConnection(mqttConnectionLibrary[preset]);
            }}
          >
            <option value="">Custom</option>
            <option value="live_mqtt_connection">Live MQTT</option>
            <option value="local_mqtt_connection">Local MQTT</option>
          </select>
        </label>

        <label className="field">
          <span>User</span>
          <input value={user} onChange={(e) => setUser(e.target.value)} placeholder="username" />
        </label>

        <label className="field">
          <span>Password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="password"
          />
        </label>

        <label className="field">
          <span>Agent broker</span>
          <input
            value={agentBroker}
            onChange={(e) => setAgentBroker(e.target.value)}
            placeholder="mqtt://agent-broker"
          />
        </label>

        <label className="field">
          <span>Client broker</span>
          <input
            value={clientBroker}
            onChange={(e) => setClientBroker(e.target.value)}
            placeholder="mqtt://client-broker"
          />
        </label>

        <label className="field">
          <span>Port</span>
          <input
            type="number"
            value={port}
            onChange={(e) => setPort(Number(e.target.value))}
            min={1}
            max={65535}
          />
        </label>

        <div className="waraps-options">
          <label className="check">
            <input
              type="checkbox"
              checked={tlsConnection}
              onChange={(e) => setTlsConnection(e.target.checked)}
            />
            <span>TLS connection</span>
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={allowCertificates}
              onChange={(e) => setAllowCertificates(e.target.checked)}
            />
            <span>Allow certificates</span>
          </label>
        </div>

        <div className="toolbar-row waraps-actions">
          <button
            className="primary-btn accent"
            disabled={!canSubmit}
            onClick={() =>
              sendMessage({
                type: "connect_to_waraps",
                user: user.trim(),
                password,
                agent_broker: agentBroker.trim(),
                client_broker: clientBroker.trim(),
                port,
                tls_connection: tlsConnection,
                allow_certificates: allowCertificates,
                geofence,
              })
            }
          >
            Connect
          </button>
          <button
            disabled={streamStatus !== "connected" || warapsStatus !== "connected"}
            onClick={() => sendMessage({ type: "disconnect_from_waraps" })}
          >
            Disconnect
          </button>
        </div>
      </section>
      {previewFrame && (() => {
        const own = previewFrame.actors.find((a) => a.isOwnShip);
        const state = own ? previewFrame.statesByActorId[own.id] : undefined;
        return state ? (
          <p className="meta geofence-own-ship-hint">
            Preview own-ship position (scenario frame): x={state.x.toFixed(0)} m, y={state.y.toFixed(0)}{" "}
            m: use geofence map for WGS84 reference area.
          </p>
        ) : null;
      })()}
      </div>
      <div className="waraps-layout__map">
        <ReferenceGeofenceMap
          geofence={geofence}
          onGeofenceChange={(nextGeofence) => {
            setGeofence(nextGeofence);
            setReferenceGeofence(nextGeofence);
          }}
        />
      </div>
    </div>
  );
}
