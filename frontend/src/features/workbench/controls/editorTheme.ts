import { EditorView } from "@codemirror/view";
import type { Extension } from "@uiw/react-codemirror";
import type { Theme } from "../../../app/theme";

/** The surface of a code editor, the same for each language; `dark` picks CodeMirror's own defaults (cursor, selection). */
export function editorSurface(theme: Theme): Extension {
  return EditorView.theme(
    {
      "&": { backgroundColor: "var(--bg-inset)" },
      ".cm-gutters": { backgroundColor: "var(--bg-inset)", borderColor: "var(--border)", color: "var(--text-dim)" },
      ".cm-activeLineGutter": { backgroundColor: "transparent" },
      ".cm-content": { tabSize: 4 },
    },
    { dark: theme === "dark" }
  );
}
