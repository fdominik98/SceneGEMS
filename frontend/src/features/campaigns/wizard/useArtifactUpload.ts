import { useCallback, useRef, useState } from "react";
import { describeOperatorError, type OperatorClient } from "../../../domain/cluster/operatorApi";
import { uploadArtifact, type UploadKind } from "../../../domain/cluster/historyApi";
import type { ArtifactRef } from "../../../domain/cluster/schemas";

/** One file on its way to the control node or refused. */
export interface UploadAttempt {
  id: number;
  fileName: string;
  state: "uploading" | "failed";
  message: string | null;
}

/** Whether a file of this kind has to be JSON (scenes and trajectories are; functional scenarios are text). */
export function mustBeJson(kind: UploadKind): boolean {
  return kind !== "functional_scenario";
}

/** The problem with a file's text before it is sent, or null. */
export function fileProblem(text: string, kind: UploadKind): string | null {
  if (text.trim().length === 0) {
    return "The file is empty.";
  }
  if (mustBeJson(kind)) {
    try {
      JSON.parse(text);
    } catch {
      return "The file is not valid JSON.";
    }
  }
  return null;
}

/** The content type an upload of this kind is sent as. */
export function contentTypeOf(kind: UploadKind): string {
  return mustBeJson(kind) ? "application/json" : "text/plain";
}

/**
 * Uploads picked files one after the other as artifacts of `kind` and hands each reference to
 * `onUploaded`. A file that is empty, not JSON where JSON is needed, or refused by the control node stays
 * in `attempts` as failed, with the reason, until dismissed.
 */
export function useArtifactUpload(client: OperatorClient | null, kind: UploadKind, onUploaded: (fileName: string, ref: ArtifactRef) => void) {
  const [attempts, setAttempts] = useState<UploadAttempt[]>([]);
  const nextId = useRef(0);

  const upload = useCallback(
    async (files: Iterable<File>) => {
      for (const file of files) {
        nextId.current += 1;
        const id = nextId.current;
        const settle = (change: Partial<UploadAttempt> | null) =>
          setAttempts((current) => (change === null ? current.filter((attempt) => attempt.id !== id) : current.map((attempt) => (attempt.id === id ? { ...attempt, ...change } : attempt))));
        setAttempts((current) => [...current, { id, fileName: file.name, state: "uploading", message: null }]);
        if (!client) {
          settle({ state: "failed", message: "No cluster is selected." });
          continue;
        }
        try {
          const text = await file.text();
          const problem = fileProblem(text, kind);
          if (problem) {
            settle({ state: "failed", message: problem });
            continue;
          }
          const ref = await uploadArtifact(client, text, kind, contentTypeOf(kind));
          settle(null);
          onUploaded(file.name, ref);
        } catch (error) {
          settle({ state: "failed", message: describeOperatorError(error) });
        }
      }
    },
    [client, kind, onUploaded]
  );

  const dismiss = useCallback((id: number) => setAttempts((current) => current.filter((attempt) => attempt.id !== id)), []);
  return { attempts, upload, dismiss, busy: attempts.some((attempt) => attempt.state === "uploading") };
}
