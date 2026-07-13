import type { GeneratedSceneData } from "../simulation/types";

const SCENE_KEY = "scenegems:visualized-scene";

/** Loads the last generated/loaded scene so the scene-generation panel survives a refresh. */
export function loadPersistedScene(): GeneratedSceneData | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    const raw = window.localStorage.getItem(SCENE_KEY);
    if (raw === null) {
      return null;
    }
    return JSON.parse(raw) as GeneratedSceneData;
  } catch {
    return null;
  }
}

export function savePersistedScene(scene: GeneratedSceneData | null): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    if (scene === null) {
      window.localStorage.removeItem(SCENE_KEY);
    } else {
      window.localStorage.setItem(SCENE_KEY, JSON.stringify(scene));
    }
  } catch {
    // Best-effort: a large scene may exceed the localStorage quota.
  }
}
