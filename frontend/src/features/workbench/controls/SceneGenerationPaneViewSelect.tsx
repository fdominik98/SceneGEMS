import { useUiStore, type SceneGenerationPaneView } from "../../../app/uiStore";

const VIEWS: { id: SceneGenerationPaneView; label: string }[] = [
  { id: "specification", label: "FEC specification" },
  { id: "monitor", label: "Monitor preview" },
];

/** View switch at the top of the scene generation right pane: the specification or the monitor preview of the scene. */
export function SceneGenerationPaneViewSelect() {
  const view = useUiStore((s) => s.sceneGenerationPaneView);
  const setView = useUiStore((s) => s.setSceneGenerationPaneView);

  return (
    <div className="scene-gen-tabs" role="tablist" aria-label="Scene generation panel view">
      {VIEWS.map(({ id, label }) => (
        <button
          key={id}
          type="button"
          role="tab"
          aria-selected={view === id}
          className={`scene-gen-tab${view === id ? " active" : ""}`}
          onClick={() => setView(id)}
        >
          {label}
        </button>
      ))}
    </div>
  );
}
