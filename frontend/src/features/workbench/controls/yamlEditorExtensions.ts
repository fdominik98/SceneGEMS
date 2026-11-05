import { yaml } from "@codemirror/lang-yaml";
import { EditorView } from "@codemirror/view";
import type { Extension } from "@uiw/react-codemirror";
import type { Theme } from "../../../app/theme";
import { editorSurface } from "./editorTheme";

const refineryLikeContentAttributes = EditorView.contentAttributes.of({
  spellcheck: "false",
  autocorrect: "off",
  autocapitalize: "off",
  translate: "no",
  writingsuggestions: "false",
});

function extensionsFor(theme: Theme): Extension[] {
  return [yaml(), refineryLikeContentAttributes, editorSurface(theme)];
}

/** One list per theme, so an editor reconfigures only when the theme changes. */
export const yamlEditorExtensions: Record<Theme, Extension[]> = {
  dark: extensionsFor("dark"),
  light: extensionsFor("light"),
};
