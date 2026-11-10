import { create } from "zustand";
import { useUiStore } from "../../../app/uiStore";
import { useBatchGenerationStore } from "../../../domain/sceneGeneration/batchGenerationStore";

/**
 * A FEC specification on its way into the scene page's editor: an explored FEC from the design
 * space exploration page or from Campaign History. The scene page's editor state lives in the
 * workbench section, so the sender queues the text here and shows the page; the workbench takes it
 * and loads it into the editor (the latest load wins, as with any other load). Not persisted.
 */

export interface SceneSpecificationLoad {
  /** What the scene page calls the specification (`explored/00003`). */
  label: string;
  /** The text, fetched when the scene page takes it. */
  text: () => Promise<string>;
}

interface SceneSpecificationHandoffState {
  pending: SceneSpecificationLoad | null;
  queue: (load: SceneSpecificationLoad) => void;
  take: () => SceneSpecificationLoad | null;
}

export const useSceneSpecificationHandoff = create<SceneSpecificationHandoffState>()((set, get) => ({
  pending: null,
  queue: (pending) => set({ pending }),
  take: () => {
    const pending = get().pending;
    if (pending !== null) {
      set({ pending: null });
    }
    return pending;
  },
}));

/**
 * Queues a specification for the scene page's editor and shows the scene page. The editor shows
 * only while no FEC of the catalog is selected, so the selection is cleared.
 */
export function sendToScenePage(load: SceneSpecificationLoad): void {
  useSceneSpecificationHandoff.getState().queue(load);
  useBatchGenerationStore.getState().clearSelectedClassIds();
  const ui = useUiStore.getState();
  ui.setSceneGenerationPaneView("specification");
  ui.setWorkbenchView("sceneGeneration");
  ui.setSection("workbench");
}
