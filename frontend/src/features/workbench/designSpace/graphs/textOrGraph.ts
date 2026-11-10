import { usePersistedState } from "../../../../app/usePersistedState";

export type TextOrGraph = "text" | "graph";

/** Persisted keys (stored with the `scenegems:` prefix) of the two switches of the design space exploration page. */
export const SPECIFICATION_VIEW_KEY = "design-space-specification-view";
export const FEC_VIEW_KEY = "design-space-fec-view";

/** Which of the two views a switch shows, kept per browser under `key`. */
export function useTextOrGraph(key: string, fallback: TextOrGraph): [TextOrGraph, (view: TextOrGraph) => void] {
  const [stored, setStored] = usePersistedState<TextOrGraph>(key, fallback);
  return [stored === "text" || stored === "graph" ? stored : fallback, setStored];
}
