import { useCallback } from "react";
import { DesignSpaceSpecificationEditor } from "./DesignSpaceSpecificationEditor";
import { useExplorationInputStore } from "./explorationInputStore";
import { DESIGN_SPACE_EDITOR_ID } from "./explorationModel";
import "./designSpace.css";

/**
 * The right pane of the design space exploration page: the specification it explores, the
 * metamodel and the well-formedness constraints, kept per browser.
 */
export function DesignSpaceSidebar({ disabled = false }: { disabled?: boolean }) {
  const specification = useExplorationInputStore((s) => s.specification);
  const label = useExplorationInputStore((s) => s.specificationLabel);
  const editSpecification = useExplorationInputStore((s) => s.editSpecification);
  const loadSpecification = useExplorationInputStore((s) => s.loadSpecification);
  const setScope = useExplorationInputStore((s) => s.setScope);
  // The master's scope comes with its default only where no scope was entered yet.
  const takeDefaultScope = useCallback(
    (scope: string) => {
      if (useExplorationInputStore.getState().scope.trim().length === 0) {
        setScope(scope);
      }
    },
    [setScope]
  );
  return (
    <aside className="right-pane scene-generation-sidebar design-space-sidebar" id={DESIGN_SPACE_EDITOR_ID} aria-label="Specification">
      <div className="scene-editor-panel">
        <h3>Metamodel and well-formedness constraints</h3>
        <p className="meta">
          The first part of a FEC specification: the classes and relations, the error constraints every scene must satisfy, and the lines that pin the own ship.
          Every model of it within the scope is one FEC.
        </p>
        <DesignSpaceSpecificationEditor
          value={specification}
          label={label}
          onEdit={editSpecification}
          onLoad={loadSpecification}
          onDefaultScope={takeDefaultScope}
          autoLoadDefault
          disabled={disabled}
        />
      </div>
    </aside>
  );
}
