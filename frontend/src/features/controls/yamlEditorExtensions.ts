import { yaml } from "@codemirror/lang-yaml";
import { EditorView } from "@codemirror/view";

const refineryLikeContentAttributes = EditorView.contentAttributes.of({
  spellcheck: "false",
  autocorrect: "off",
  autocapitalize: "off",
  translate: "no",
  writingsuggestions: "false",
});

export const yamlEditorExtensions = [
  yaml(),
  refineryLikeContentAttributes,
  EditorView.theme(
    {
      "&": { backgroundColor: "#020617" },
      ".cm-gutters": { backgroundColor: "#020617", borderColor: "#334155", color: "#64748b" },
      ".cm-activeLineGutter": { backgroundColor: "transparent" },
      ".cm-content": { tabSize: 4 },
    },
    { dark: true }
  ),
];
