import { useCallback } from "react";
import { Disclosure } from "../../../components/Disclosure";
import { PageHeader } from "../../../components/PageHeader";
import {
  CONTROL_NODE_BROKER_PRESET,
  mqttConnectionLibrary,
  PRESET_LABELS,
  type MqttConnectionPresetKey,
} from "./connectionLibrary";
import { useConnectionStore } from "./connectionStore";
import { ReferenceGeofenceMap } from "./ReferenceGeofenceMap";

const PRESET_ORDER: (MqttConnectionPresetKey | "")[] = ["control_node_broker", "waraps_tls_broker", ""];

/**
 * The Connections page: the settings of a simulation that reaches outside the cluster. The MQTT
 * broker is where a real vessel's agent is found, and the reference area is where the scenario's
 * local frame lies on the map. Nothing connects from here: a simulation is a job on a worker
 * node, and an attended job with a real vessel takes the broker with it.
 */
export function MqttBrokerPanel() {
  const form = useConnectionStore();
  const { selectedPreset, geofence, setSelectedPreset, applyConnection, setGeofence } = form;
  const usesControlNode = selectedPreset === CONTROL_NODE_BROKER_PRESET;

  const choosePreset = useCallback(
    (preset: MqttConnectionPresetKey | "") => {
      setSelectedPreset(preset);
      if (preset !== "" && preset !== CONTROL_NODE_BROKER_PRESET) {
        applyConnection(mqttConnectionLibrary[preset]);
      }
    },
    [applyConnection, setSelectedPreset]
  );

  const target = `${form.agentBroker || "no broker"}:${form.port}${form.tlsConnection ? ", TLS" : ""}`;

  return (
    <div className="mqtt-broker-layout">
      <PageHeader
        title="Connections"
        description="The MQTT broker a real vessel's agent is on, and where the scenario lies on the map. A simulation job on a worker node uses them; nothing connects from this page."
      />

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
          <p className="meta">The control node's own broker: plain MQTT on the cluster's VPN. The agent of a real vessel must reach the control node over the VPN to take part.</p>
        ) : (
          <p className="meta">
            {target}. A simulation with a real vessel runs its vessels on this broker; the worker node that runs it must reach the broker.
          </p>
        )}
      </section>

      {!usesControlNode && (
        <Disclosure id="mqtt-broker:details" title="Broker address" hint="User, host, port, TLS" defaultOpen={selectedPreset === ""} headingLevel={3}>
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
        <span>Broker host (as the worker node's containers dial it)</span>
        <input
          value={form.agentBroker}
          onChange={(e) => {
            markCustom();
            form.setAgentBroker(e.target.value);
          }}
          placeholder="broker.example.org"
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
