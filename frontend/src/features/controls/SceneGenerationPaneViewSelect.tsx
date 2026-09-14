import { useUiStore, type SceneGenerationPaneView } from "../../app/uiStore";

/** View switch at the top of the scene generation right pane. */
export function SceneGenerationPaneViewSelect() {
  const view = useUiStore((s) => s.sceneGenerationPaneView);
  const setView = useUiStore((s) => s.setSceneGenerationPaneView);

  return (
    <header className="right-pane-toolbar">
      <label className="right-pane-view-select">
        <span className="right-pane-toolbar-title">View</span>
        <select
          value={view}
          onChange={(e) => setView(e.target.value as SceneGenerationPaneView)}
          aria-label="Scene generation panel view"
        >
          <option value="specification">Scene specification</option>
          <option value="monitor">Monitor preview</option>
        </select>
      </label>
    </header>
  );
}
