import { useRef } from "react";
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

/**
 * A button that opens the file picker, uploads each chosen file to the control node as an artifact and lists the
 * ones that failed. The browser's own file field stays hidden, as on every other page that opens a file.
 */
export function UploadControl({ client, kind, label, accept, onUploaded }: UploadControlProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const { attempts, upload, dismiss } = useArtifactUpload(client, kind, onUploaded);
  return (
    <div className="wiz-upload">
      <input
        ref={inputRef}
        hidden
        type="file"
        multiple
        accept={accept}
        aria-label={label}
        disabled={!client}
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          event.target.value = "";
          void upload(files);
        }}
      />
      <div>
        <button type="button" disabled={!client} onClick={() => inputRef.current?.click()}>
          {label}...
        </button>
      </div>
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
