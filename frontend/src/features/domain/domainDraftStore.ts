import { create } from "zustand";
import { DOMAIN_KEYS, normalizeNewlines, type DomainKey, type DomainPresets, type DomainTexts } from "../../domain/cluster/presetsApi";

/**
 * Unsaved edits of the domain configuration, per cluster (operator URL). They live as long as the
 * page is open, so leaving the Domain Configuration section and coming back keeps them; a reload
 * drops them, and the master's saved configuration shows again.
 */

interface DomainDraftState {
  drafts: Record<string, DomainTexts>;
  /** Sets one text of the cluster's draft, starting the draft from `base` (the saved texts) when there is none. */
  setText: (clusterUrl: string, base: DomainTexts, key: DomainKey, text: string) => void;
  setTexts: (clusterUrl: string, texts: DomainTexts) => void;
  discard: (clusterUrl: string) => void;
}

export const useDomainDraftStore = create<DomainDraftState>((set) => ({
  drafts: {},
  setText: (clusterUrl, base, key, text) =>
    set((state) => ({ drafts: { ...state.drafts, [clusterUrl]: { ...(state.drafts[clusterUrl] ?? base), [key]: text } } })),
  setTexts: (clusterUrl, texts) => set((state) => ({ drafts: { ...state.drafts, [clusterUrl]: { ...texts } } })),
  discard: (clusterUrl) =>
    set((state) => {
      const rest = { ...state.drafts };
      delete rest[clusterUrl];
      return { drafts: rest };
    }),
}));

/** Whether two domain configurations hold the same texts (line endings aside, as the master stores LF). */
export function sameTexts(a: DomainTexts, b: DomainTexts): boolean {
  return DOMAIN_KEYS.every((key) => normalizeNewlines(a[key]) === normalizeNewlines(b[key]));
}

/** The default preset of every text, or null while the presets are not known or one has no default. */
export function defaultTexts(presets: DomainPresets | undefined): DomainTexts | null {
  if (!presets) {
    return null;
  }
  const texts: Partial<DomainTexts> = {};
  for (const key of DOMAIN_KEYS) {
    const preset = presets[key].find((entry) => entry.default);
    if (!preset) {
      return null;
    }
    texts[key] = preset.content;
  }
  return texts as DomainTexts;
}
