import { syntaxHighlighting } from "@codemirror/language";
import { oneDarkTheme } from "@codemirror/theme-one-dark";
import { classHighlighter } from "@lezer/highlight";
import { EditorView } from "@codemirror/view";
import type { Theme } from "../../../app/theme";
import problemLanguageSupport from "../../../language/refineryProblem/problemLanguageSupport";
import { editorSurface } from "./editorTheme";

const refineryLikeContentAttributes = EditorView.contentAttributes.of({
  spellcheck: "false",
  autocorrect: "off",
  autocapitalize: "off",
  translate: "no",
  writingsuggestions: "false",
});

/** The Refinery `.problem` language with its highlighting, the theme's colors and the editor surface. */
export function problemExtensionsFor(theme: Theme) {
  return [
    problemLanguageSupport(),
    syntaxHighlighting(classHighlighter),
    ...(theme === "dark" ? [oneDarkTheme] : []),
    refineryLikeContentAttributes,
    editorSurface(theme),
  ];
}
