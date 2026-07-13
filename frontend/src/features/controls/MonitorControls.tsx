import { usePersistedState } from "../../app/usePersistedState";
import { usePlaybackStore } from "../../domain/playback/playbackStore";
import { DEFAULT_MONITOR_NAME, defaultMonitorTopic } from "./monitorTopic";
import { buildInitializeMonitorMessage } from "./monitorConfig";
import type { SimulationStreamControls } from "./types";

interface Props {
  streamControls: SimulationStreamControls;
  colregsConstraintsContent: string;
}

export function MonitorControls({ streamControls, colregsConstraintsContent }: Props) {
  const warapsStatus = usePlaybackStore((s) => s.warapsStatus);
  const monitorStatus = usePlaybackStore((s) => s.monitorStatus);

  const [scope, setScope] = usePersistedState<"internal" | "external">("monitor-scope", "internal");
  const [name, setName] = usePersistedState("monitor-name", DEFAULT_MONITOR_NAME);
  const [topic, setTopic] = usePersistedState("monitor-topic", () =>
    defaultMonitorTopic(DEFAULT_MONITOR_NAME)
  );

  const hasColregsConfig = colregsConstraintsContent.trim().length > 0;
  const initializeDisabled =
    warapsStatus !== "connected" || monitorStatus === "connected" || !hasColregsConfig;
  const shutDownDisabled = monitorStatus === "disconnected";

  return (
    <>
      <div className="toolbar-row monitor-controls-fields" style={{ marginTop: 8, alignItems: "flex-end" }}>
        <label className="field monitor-field-compact">
          <span>Scope</span>
          <select value={scope} onChange={(e) => setScope(e.target.value as "internal" | "external")}>
            <option value="internal">Internal</option>
            <option value="external">External</option>
          </select>
        </label>
        <label className="field monitor-field-compact">
          <span>Name</span>
          <input
            type="text"
            value={name}
            onChange={(e) => {
              const next = e.target.value;
              setName(next);
              setTopic(defaultMonitorTopic(next));
            }}
            autoComplete="off"
          />
        </label>
        <label className="field monitor-field-grow">
          <span>Topic</span>
          <input
            type="text"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            autoComplete="off"
          />
        </label>
      </div>
      <div className="toolbar-row" style={{ marginTop: 10 }}>
        <button
          className="primary-btn"
          type="button"
          disabled={initializeDisabled}
          onClick={() =>
            streamControls.sendMessage(
              buildInitializeMonitorMessage(colregsConstraintsContent, { scope, name, topic })
            )
          }
        >
          Initialize Monitor
        </button>
        <button type="button" disabled={shutDownDisabled} onClick={() => streamControls.sendMessage({ type: "shut_down_monitor" })}>
          Shut Down
        </button>
      </div>
      <p className="meta" style={{ marginTop: 10 }}>
        Status: <span className={`status-text ${monitorStatus}`}>{monitorStatus}</span>
      </p>
      <p className="meta" style={{ marginTop: 6 }}>
        Requirements: WARA-PS status={warapsStatus} | monitor not connected=
        {monitorStatus === "connected" ? "no" : "yes"}
      </p>
    </>
  );
}
