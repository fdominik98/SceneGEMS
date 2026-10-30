import { create } from "zustand";
import { persist } from "zustand/middleware";
import { newEntrySeed } from "./entryConfig";

interface EntrySeedState {
  /** The base seed every new workbench entry takes, or null for a fresh random one per entry. */
  fixed: number | null;
  /** The base seed of the latest entry this browser created. */
  last: number | null;
  setFixed: (seed: number | null) => void;
}

/**
 * The base seed of the workbench pages' entries, kept per browser. An entry's case 0 runs with
 * its base seed in every step (scene generation, trajectory generation, the simulation), so the
 * same input with the same seed gives the same outputs again.
 */
export const useEntrySeedStore = create<EntrySeedState>()(
  persist(
    (set) => ({
      fixed: null,
      last: null,
      setFixed: (fixed) => set({ fixed }),
    }),
    {
      name: "scenegems:workbench-seed",
      version: 1,
      partialize: (state) => ({ fixed: state.fixed, last: state.last }),
    }
  )
);

/** The base seed of a new entry: the fixed one, or a fresh random one. It becomes the last seed. */
export function takeEntrySeed(random: () => number = Math.random): number {
  const seed = useEntrySeedStore.getState().fixed ?? newEntrySeed(random);
  useEntrySeedStore.setState({ last: seed });
  return seed;
}
