import {
  useCallback,
  useMemo,
  useRef,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import { useUiStore } from "../../app/uiStore";
import { usePlaybackStore } from "../../domain/playback/playbackStore";
import { framesAtOrBeforeCursor } from "../../domain/playback/playbackFrameResolve";
import type { SimulationFrame } from "../../domain/simulation/types";
import { MetricsView } from "../metrics/MetricsView";
import { pickDefaultRelationId } from "../metrics/metricsRelations";
import { BasicActorInfoPanel } from "../monitor/BasicActorInfoPanel";
import { ActorVisibilityPanel } from "./ActorVisibilityPanel";

function TrajectoryColumnChrome({
  title,
  subtitle,
  onExport,
  onHide,
  children,
  showExport = true,
}: {
  title: string;
  subtitle: string;
  onExport?: () => void;
  onHide: () => void;
  children: ReactNode;
  showExport?: boolean;
}) {
  return (
    <>
      <header className="right-trajectory-column-header">
        <div className="right-trajectory-column-heading">
          <h3 className="right-trajectory-column-title">{title}</h3>
          <p className="right-trajectory-column-sub">{subtitle}</p>
        </div>
        {showExport && onExport ? (
          <button type="button" className="right-trajectory-hide-btn" onClick={onExport}>
            Export
          </button>
        ) : null}
        <button
          type="button"
          className="right-trajectory-hide-btn"
          onClick={onHide}
          aria-label={`Hide ${title}`}
          title="Hide panel"
        >
          Hide
        </button>
      </header>
      <div className="right-trajectory-column-scroll">{children}</div>
    </>
  );
}

function RevealStrip({
  label,
  onShow,
}: {
  label: string;
  onShow: () => void;
}) {
  return (
    <button type="button" className="right-trajectory-reveal-strip" onClick={onShow}>
      <span className="right-trajectory-reveal-label">{label}</span>
      <span className="right-trajectory-reveal-hint" aria-hidden>
        ▶
      </span>
    </button>
  );
}

function exportTrajectoryFrames(
  stream: "preview" | "simulation",
  scenarioId: string | null,
  frames: SimulationFrame[]
) {
  const sortedFrames = [...frames].sort((a, b) => a.timestamp - b.timestamp);
  const payload = {
    stream,
    scenarioId,
    exportedAt: new Date().toISOString(),
    frameCount: sortedFrames.length,
    frames: sortedFrames,
  };
  const prettyJson = JSON.stringify(payload, null, 2);
  const blob = new Blob([prettyJson], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${stream}_trajectory_${stamp}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function MonitorStreamCluster({
  previewColumn,
  simulationColumn,
}: {
  previewColumn: ReactNode;
  simulationColumn: ReactNode;
}) {
  const previewVisible = useUiStore((s) => s.rightTrajectoryPreviewVisible);
  const simulationVisible = useUiStore((s) => s.rightTrajectorySimulationVisible);
  const setPreviewVisible = useUiStore((s) => s.setRightTrajectoryPreviewVisible);
  const setSimulationVisible = useUiStore((s) => s.setRightTrajectorySimulationVisible);
  const splitPercent = useUiStore((s) => s.rightTrajectorySplitPercent);
  const setSplitPercent = useUiStore((s) => s.setRightTrajectorySplitPercent);

  const clusterRef = useRef<HTMLDivElement | null>(null);
  const splitDragRef = useRef<{ startX: number; startSplit: number; width: number } | null>(null);

  const onSplitResizeStart = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      event.preventDefault();
      const el = clusterRef.current;
      if (!el) {
        return;
      }
      const width = el.getBoundingClientRect().width;
      splitDragRef.current = { startX: event.clientX, startSplit: splitPercent, width };

      const onPointerMove = (moveEvent: PointerEvent) => {
        const drag = splitDragRef.current;
        if (!drag) {
          return;
        }
        const delta = moveEvent.clientX - drag.startX;
        const deltaPct = (delta / drag.width) * 100;
        setSplitPercent(drag.startSplit + deltaPct);
      };

      const onPointerUp = () => {
        splitDragRef.current = null;
        window.removeEventListener("pointermove", onPointerMove);
        window.removeEventListener("pointerup", onPointerUp);
      };

      window.addEventListener("pointermove", onPointerMove);
      window.addEventListener("pointerup", onPointerUp, { once: true });
    },
    [splitPercent, setSplitPercent]
  );

  const bothVisible = previewVisible && simulationVisible;

  return (
    <div
      ref={clusterRef}
      className={`right-trajectory-cluster${bothVisible ? " right-trajectory-cluster--split" : ""}`}
    >
      {previewVisible ? (
        <div
          className="right-trajectory-column"
          style={
            bothVisible
              ? { flex: `0 0 ${splitPercent}%`, minWidth: 0 }
              : { flex: "1 1 auto", minWidth: 0 }
          }
        >
          {previewColumn}
        </div>
      ) : (
        <RevealStrip label="Preview" onShow={() => setPreviewVisible(true)} />
      )}

      {bothVisible && (
        <div
          className="right-trajectory-split-resizer"
          onPointerDown={onSplitResizeStart}
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize preview and simulation panels"
        />
      )}

      {simulationVisible ? (
        <div
          className="right-trajectory-column"
          style={
            bothVisible ? { flex: "1 1 0%", minWidth: 0 } : { flex: "1 1 auto", minWidth: 0 }
          }
        >
          {simulationColumn}
        </div>
      ) : (
        <RevealStrip label="Simulation" onShow={() => setSimulationVisible(true)} />
      )}
    </div>
  );
}

export function TrajectoryMonitorSidebar() {
  const monitorPanelView = useUiStore((s) => s.monitorPanelView);
  const setMonitorPanelView = useUiStore((s) => s.setMonitorPanelView);
  const selectedMetricsRelationId = useUiStore((s) => s.selectedMetricsRelationId);
  const setSelectedMetricsRelationId = useUiStore((s) => s.setSelectedMetricsRelationId);
  const setRightPaneVisible = useUiStore((s) => s.setRightPaneVisible);
  const setPreviewVisible = useUiStore((s) => s.setRightTrajectoryPreviewVisible);
  const setSimulationVisible = useUiStore((s) => s.setRightTrajectorySimulationVisible);
  const activeScenarioId = usePlaybackStore((s) => s.activeScenarioId);
  const previewFrames = usePlaybackStore((s) => s.frames);
  const simulationFrames = usePlaybackStore((s) => s.simulationFrames);
  const playbackCursor = usePlaybackStore((s) => s.playbackCursor);
  const sortedPreviewFrames = useMemo(
    () => [...previewFrames].sort((a, b) => a.timestamp - b.timestamp),
    [previewFrames]
  );
  const sortedSimulationFrames = useMemo(
    () => [...simulationFrames].sort((a, b) => a.timestamp - b.timestamp),
    [simulationFrames]
  );
  const previewMetricsFrames = useMemo(
    () => framesAtOrBeforeCursor(sortedPreviewFrames, playbackCursor),
    [sortedPreviewFrames, playbackCursor]
  );
  const simulationMetricsFrames = useMemo(
    () => framesAtOrBeforeCursor(sortedSimulationFrames, playbackCursor),
    [sortedSimulationFrames, playbackCursor]
  );

  const defaultRelation = pickDefaultRelationId([
    ...previewMetricsFrames,
    ...simulationMetricsFrames,
  ]);
  const activeRelation = selectedMetricsRelationId ?? defaultRelation;

  return (
    <aside className="right-pane right-pane-trajectory">
      <header className="right-pane-toolbar">
        <label className="right-pane-view-select">
          <span className="right-pane-toolbar-title">View</span>
          <select
            value={monitorPanelView}
            onChange={(e) =>
              setMonitorPanelView(e.target.value as "runtime_data" | "overall_analysis")
            }
            aria-label="Monitoring panel view"
          >
            <option value="runtime_data">Runtime data</option>
            <option value="overall_analysis">Overall analysis</option>
          </select>
        </label>
        <button
          type="button"
          className="right-pane-hide-btn"
          onClick={() => setRightPaneVisible(false)}
          aria-label="Hide monitoring panel"
          title="Hide monitoring panel"
        >
          Hide panel ▶
        </button>
      </header>

      {monitorPanelView === "runtime_data" ? (
        <MonitorStreamCluster
          previewColumn={
            <TrajectoryColumnChrome
              title="Preview trajectory"
              subtitle="Monitor and layer controls"
              onExport={() =>
                exportTrajectoryFrames("preview", activeScenarioId, sortedPreviewFrames)
              }
              onHide={() => setPreviewVisible(false)}
            >
              <ActorVisibilityPanel stream="animation" />
              <BasicActorInfoPanel stream="animation" />
            </TrajectoryColumnChrome>
          }
          simulationColumn={
            <TrajectoryColumnChrome
              title="Simulation trajectory"
              subtitle="Monitor and layer controls"
              onExport={() =>
                exportTrajectoryFrames("simulation", activeScenarioId, sortedSimulationFrames)
              }
              onHide={() => setSimulationVisible(false)}
            >
              <ActorVisibilityPanel stream="simulation" />
              <BasicActorInfoPanel stream="simulation" />
            </TrajectoryColumnChrome>
          }
        />
      ) : (
        <MonitorStreamCluster
          previewColumn={
            <TrajectoryColumnChrome
              title="Preview metrics"
              subtitle="Distance, DCPA, TCPA, and danger sector"
              onHide={() => setPreviewVisible(false)}
              showExport={false}
            >
              <MetricsView
                frames={previewMetricsFrames}
                relationId={activeRelation}
                onRelationIdChange={setSelectedMetricsRelationId}
              />
            </TrajectoryColumnChrome>
          }
          simulationColumn={
            <TrajectoryColumnChrome
              title="Simulation metrics"
              subtitle="Distance, DCPA, TCPA, and danger sector"
              onHide={() => setSimulationVisible(false)}
              showExport={false}
            >
              <MetricsView
                frames={simulationMetricsFrames}
                relationId={activeRelation}
                onRelationIdChange={setSelectedMetricsRelationId}
              />
            </TrajectoryColumnChrome>
          }
        />
      )}
    </aside>
  );
}
