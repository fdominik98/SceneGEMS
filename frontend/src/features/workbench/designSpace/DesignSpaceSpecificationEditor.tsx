import { useEffect, useRef } from "react";
import { IconButton } from "../../../components/IconButton";
import { DownloadIcon } from "../../../components/icons";
import { saveBlob } from "../../../components/saveBlob";
import { describeOperatorError } from "../../../domain/cluster/operatorApi";
import { normalizeNewlines } from "../../../domain/cluster/presetsApi";
import { useDesignSpaceDefault } from "../../campaigns/useCampaignData";
import { ProblemEditor } from "../controls/ProblemEditor";
import { MetamodelGraph } from "./graphs/MetamodelGraph";
import { SPECIFICATION_VIEW_KEY, useTextOrGraph } from "./graphs/textOrGraph";
import { ViewSwitch } from "./graphs/ViewSwitch";
import "./designSpace.css";

/** What the editor calls the control node's default text. */
export const DEFAULT_SPECIFICATION_LABEL = "the control node's default";

interface Props {
  value: string;
  /** Where the text came from, null for one written here. */
  label: string | null;
  /** The text as typed. */
  onEdit: (text: string) => void;
  /** A loaded text (the control node's default, a file) replaces the editor's. */
  onLoad: (text: string, label: string) => void;
  /** The scope the control node ships with its default, for a caller whose scope is still empty. */
  onDefaultScope?: (scope: string) => void;
  /** Loads the control node's default into an empty editor on its own. */
  autoLoadDefault?: boolean;
  disabled?: boolean;
  /** The file name of an export. */
  exportName?: string;
}

/**
 * The editor of a design space's specification: the metamodel and the well-formedness constraints
 * (the first part of a FEC specification), with the control node's default, a file and an export. The
 * workbench's design space exploration page and the campaign wizard use the same one. "Graph" shows
 * the metamodel of the text as a class diagram instead of the editor (the choice is kept per browser);
 * the editor stays mounted meanwhile, so its undo history survives the switch.
 */
export function DesignSpaceSpecificationEditor({ value, label, onEdit, onLoad, onDefaultScope, autoLoadDefault = false, disabled = false, exportName = "design_space.problem" }: Props) {
  const fileInput = useRef<HTMLInputElement | null>(null);
  const defaults = useDesignSpaceDefault();
  const shipped = defaults.data ?? null;
  const missing = defaults.isSuccess && shipped === null;
  const empty = value.trim().length === 0;
  const [view, setView] = useTextOrGraph(SPECIFICATION_VIEW_KEY, "text");

  const loadDefault = (ask: boolean) => {
    if (shipped === null) {
      return;
    }
    const unchanged = label === DEFAULT_SPECIFICATION_LABEL && normalizeNewlines(value) === normalizeNewlines(shipped.specification);
    if (ask && !empty && !unchanged && !window.confirm("Replace the text in the editor with the control node's default?")) {
      return;
    }
    onLoad(normalizeNewlines(shipped.specification), DEFAULT_SPECIFICATION_LABEL);
    onDefaultScope?.(shipped.scope);
  };

  // An empty editor starts from the control node's default, once it is known.
  const autoLoaded = useRef(false);
  useEffect(() => {
    if (!autoLoadDefault || autoLoaded.current || shipped === null || !empty) {
      return;
    }
    autoLoaded.current = true;
    onLoad(normalizeNewlines(shipped.specification), DEFAULT_SPECIFICATION_LABEL);
    onDefaultScope?.(shipped.scope);
  }, [autoLoadDefault, empty, onDefaultScope, onLoad, shipped]);

  return (
    <div className="design-space-editor">
      <div className="toolbar-row">
        <ViewSwitch label="Show the specification as" value={view} onChange={setView} />
        <button
          type="button"
          disabled={disabled || shipped === null}
          title={shipped === null ? (missing ? "This control node ships no default design space" : "Reading the control node's default...") : "Put the control node's default metamodel, constraints and scope into the editor"}
          onClick={() => loadDefault(true)}
        >
          Load the default
        </button>
        <input
          ref={fileInput}
          hidden
          type="file"
          accept=".problem,text/plain"
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file) {
              void file.text().then((text) => onLoad(normalizeNewlines(text), file.name));
            }
          }}
        />
        <button type="button" disabled={disabled} onClick={() => fileInput.current?.click()}>
          Open file...
        </button>
        <IconButton
          label="Export the specification (.problem)"
          icon={<DownloadIcon />}
          disabled={empty}
          onClick={() => saveBlob(new Blob([value], { type: "text/plain" }), exportName)}
        />
      </div>
      {missing && empty ? (
        <p className="meta" role="status">
          This control node ships no default design space (it is older than the design space exploration). Write the metamodel and the constraints here, or open a
          .problem file.
        </p>
      ) : null}
      {defaults.isError ? (
        <p className="meta warning" role="status">
          The control node's default could not be read: {describeOperatorError(defaults.error)}
        </p>
      ) : null}
      <div className="design-space-editor-body" hidden={view !== "text"}>
        <ProblemEditor value={value} onChange={disabled ? undefined : onEdit} readOnly={disabled} ariaLabel="Metamodel and well-formedness constraints" />
      </div>
      {view === "graph" ? <MetamodelGraph text={value} /> : null}
    </div>
  );
}
