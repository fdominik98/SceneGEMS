import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import { DEFAULT_EXPLORATION_TIMEOUT_S, DEFAULT_MAX_FECS } from "../../../domain/designSpace/designSpaceConfig";

/**
 * The input of the design space exploration page, kept per browser like the scene page's
 * specification: the metamodel and the well-formedness constraints, what the page calls them,
 * the scope, and the search's limits.
 */

export interface ExplorationInput {
  specification: string;
  /** Where the text came from ("the master's default", a file name), with " (edited)" once changed; null for a text written here. */
  specificationLabel: string | null;
  scope: string;
  /** Null for every FEC. */
  maxFecs: number | null;
  timeoutSeconds: number;
}

interface ExplorationInputState extends ExplorationInput {
  /** Replaces the text (a load), with what it is called. */
  loadSpecification: (text: string, label: string | null) => void;
  /** The text as typed in the editor. */
  editSpecification: (text: string) => void;
  setScope: (scope: string) => void;
  setMaxFecs: (maxFecs: number | null) => void;
  setTimeoutSeconds: (seconds: number) => void;
}

export const EXPLORATION_INPUT_KEY = "scenegems:design-space-exploration";

export const INITIAL_EXPLORATION_INPUT: ExplorationInput = {
  specification: "",
  specificationLabel: null,
  scope: "",
  maxFecs: DEFAULT_MAX_FECS,
  timeoutSeconds: DEFAULT_EXPLORATION_TIMEOUT_S,
};

/** A loaded text's label once it is changed in the editor. */
export function editedLabel(label: string | null): string | null {
  return label === null || label.endsWith(" (edited)") ? label : `${label} (edited)`;
}

function browserStorage(): Storage | undefined {
  try {
    return typeof window === "undefined" ? undefined : window.localStorage;
  } catch {
    return undefined;
  }
}

const noStorage: Storage = {
  length: 0,
  clear: () => undefined,
  getItem: () => null,
  key: () => null,
  removeItem: () => undefined,
  setItem: () => undefined,
};

export function createExplorationInputStore(storage: () => Storage | undefined = browserStorage) {
  return create<ExplorationInputState>()(
    persist(
      (set) => ({
        ...INITIAL_EXPLORATION_INPUT,
        loadSpecification: (specification, specificationLabel) => set({ specification, specificationLabel }),
        editSpecification: (specification) => set((state) => ({ specification, specificationLabel: editedLabel(state.specificationLabel) })),
        setScope: (scope) => set({ scope }),
        setMaxFecs: (maxFecs) => set({ maxFecs }),
        setTimeoutSeconds: (timeoutSeconds) => set({ timeoutSeconds }),
      }),
      {
        name: EXPLORATION_INPUT_KEY,
        version: 1,
        storage: createJSONStorage(() => storage() ?? noStorage),
        partialize: (state) => ({
          specification: state.specification,
          specificationLabel: state.specificationLabel,
          scope: state.scope,
          maxFecs: state.maxFecs,
          timeoutSeconds: state.timeoutSeconds,
        }),
      }
    )
  );
}

export const useExplorationInputStore = createExplorationInputStore();
