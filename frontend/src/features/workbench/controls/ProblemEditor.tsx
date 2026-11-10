import CodeMirror from "@uiw/react-codemirror";
import { useTheme, type Theme } from "../../../app/theme";
import { problemExtensionsFor } from "./problemEditorExtensions";

type ProblemExtensions = ReturnType<typeof problemExtensionsFor>;

/** One list per theme, so an editor reconfigures only when the theme changes. */
const EXTENSIONS: Record<Theme, ProblemExtensions> = {
  dark: problemExtensionsFor("dark"),
  light: problemExtensionsFor("light"),
};

interface ProblemEditorProps {
  value: string;
  onChange?: (value: string) => void;
  /** Shows the text without letting it be changed (an explored FEC). */
  readOnly?: boolean;
  /** The accessible name of the editor's text. */
  ariaLabel?: string;
  className?: string;
}

/**
 * An editor of a Refinery `.problem` text (a FEC specification, or the metamodel and the
 * well-formedness constraints a design space exploration starts from), set up as the scene
 * page's specification editor is, in the theme's colors.
 */
export function ProblemEditor({ value, onChange, readOnly = false, ariaLabel, className }: ProblemEditorProps) {
  const theme = useTheme();
  return (
    <CodeMirror
      className={`scene-editor-problem-codemirror${className ? ` ${className}` : ""}`}
      value={value}
      height="100%"
      theme="none"
      editable={!readOnly}
      readOnly={readOnly}
      aria-label={ariaLabel}
      extensions={EXTENSIONS[theme]}
      onChange={onChange}
    />
  );
}
