import { useId } from "react";
import type { OperatorClient } from "../../../domain/cluster/operatorApi";
import type { UploadKind } from "../../../domain/cluster/historyApi";
import type { ArtifactRef } from "../../../domain/cluster/schemas";
import { useArtifactUpload } from "./useArtifactUpload";

export interface UploadControlProps {
  client: OperatorClient | null;
  kind: UploadKind;
  /** The label of the file picker. */
  label: string;
  /** The `accept` attribute of the picker (file types the browser offers). */
  accept?: string;
  onUploaded: (fileName: string, ref: ArtifactRef) => void;
}

/** A file picker that uploads each chosen file to the control node as an artifact and lists the ones that failed. */
export function UploadControl({ client, kind, label, accept, onUploaded }: UploadControlProps) {
  const inputId = useId();
  const { attempts, upload, dismiss } = useArtifactUpload(client, kind, onUploaded);
  return (
    <div className="wiz-upload">
      <label htmlFor={inputId} className="wiz-label">
        {label}
      </label>
      <input
        id={inputId}
        type="file"
        multiple
        accept={accept}
        disabled={!client}
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          event.target.value = "";
          void upload(files);
        }}
      />
      {!client && <p className="wiz-hint wiz-hint--warn">Select a cluster to upload files.</p>}
      {attempts.length > 0 && (
        <ul className="wiz-uploads" aria-label="Uploads">
          {attempts.map((attempt) => (
            <li key={attempt.id} className={`wiz-upload-row wiz-upload-row--${attempt.state}`} role={attempt.state === "failed" ? "alert" : "status"}>
              <span>
                <strong>{attempt.fileName}</strong>
                {attempt.state === "uploading" ? " uploading..." : `: ${attempt.message}`}
              </span>
              {attempt.state === "failed" && (
                <button type="button" onClick={() => dismiss(attempt.id)}>
                  Dismiss
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
