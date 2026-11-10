import { useCallback, useRef, useState } from "react";

/** A functional scenario to put into the scene page's editor, and what the page calls it. */
export interface EditorLoad {
  label: string;
  text: string;
}

export interface PendingEditorLoad {
  /** What was picked (a class id or a file name), or null when it is only known once loaded (a loaded scene's scenario). */
  label: string | null;
}

/**
 * Loads into the scene page's editor (a scenario of the control node, a file, a loaded scene's scenario). They end in any
 * order: only the latest one is applied, and `cancel` (typing in the editor) drops the ones still running. While one
 * runs, `pending` names it, so the scenario list can show the pick at once and generating can wait for the text.
 */
export function useEditorLoads(apply: (loaded: EditorLoad) => void, fail: (message: string) => void) {
  const latest = useRef(0);
  const [pending, setPending] = useState<PendingEditorLoad | null>(null);

  const load = useCallback(
    (label: string | null, run: () => Promise<EditorLoad | null>, failure: string) => {
      const token = ++latest.current;
      setPending({ label });
      void run()
        .then((loaded) => {
          if (token === latest.current && loaded !== null) {
            apply(loaded);
          }
        })
        .catch((error: unknown) => {
          if (token === latest.current) {
            fail(`${failure}: ${error instanceof Error ? error.message : String(error)}`);
          }
        })
        .finally(() => {
          if (token === latest.current) {
            setPending(null);
          }
        });
    },
    [apply, fail]
  );

  const cancel = useCallback(() => {
    latest.current += 1;
    setPending(null);
  }, []);

  return { pending, load, cancel };
}
