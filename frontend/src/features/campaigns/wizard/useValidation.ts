import { useCallback, useRef, useState } from "react";
import { validateCampaignConfig, type ValidationResult } from "../../../domain/cluster/campaignApi";
import { describeOperatorError, OperatorApiError, type OperatorClient } from "../../../domain/cluster/operatorApi";
import { parseReasons, type Reason } from "./reasons";

/** The control node's verdict on the config last sent to it. */
export interface ValidationState {
  /** The YAML text this state belongs to, or null before the first check. */
  yaml: string | null;
  status: "idle" | "checking" | "valid" | "invalid" | "error";
  result: ValidationResult | null;
  /** The reasons the control node gave, parsed. */
  reasons: Reason[];
  /** A message when the check itself failed (the control node is unreachable, the answer is unexpected). */
  message: string | null;
}

export const IDLE_VALIDATION: ValidationState = { yaml: null, status: "idle", result: null, reasons: [], message: null };

/** The state a refused config (HTTP 422) or a failed check leaves. */
export function validationFromError(yaml: string, error: unknown): ValidationState {
  if (error instanceof OperatorApiError && error.status === 422) {
    const reasons = parseReasons(error.reasons.length > 0 ? error.reasons : [error.message]);
    return { yaml, status: "invalid", result: null, reasons, message: error.message };
  }
  return { yaml, status: "error", result: null, reasons: [], message: describeOperatorError(error) };
}

/** Checks configs on the control node; an answer for an older text than the latest check is dropped. */
export function useValidation(client: OperatorClient | null) {
  const [state, setState] = useState<ValidationState>(IDLE_VALIDATION);
  const latest = useRef(0);

  const check = useCallback(
    async (yaml: string) => {
      if (!client) {
        return;
      }
      latest.current += 1;
      const mine = latest.current;
      setState((previous) => ({ ...previous, yaml, status: "checking" }));
      try {
        const result = await validateCampaignConfig(client, yaml);
        if (latest.current === mine) {
          setState({ yaml, status: "valid", result, reasons: [], message: null });
        }
      } catch (error) {
        if (latest.current === mine) {
          setState(validationFromError(yaml, error));
        }
      }
    },
    [client]
  );

  const adopt = useCallback((next: ValidationState) => {
    latest.current += 1;
    setState(next);
  }, []);

  const reset = useCallback(() => {
    latest.current += 1;
    setState(IDLE_VALIDATION);
  }, []);

  return { state, check, adopt, reset };
}
