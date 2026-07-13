import type { EvaluationData } from "../simulation/types";

export function parseEvaluationTimeSeconds(
  evaluationData: EvaluationData | undefined | null
): number | null {
  if (!evaluationData || typeof evaluationData !== "object" || Array.isArray(evaluationData)) {
    return null;
  }
  const raw = evaluationData.evaluation_time ?? evaluationData.evaluationTime;
  if (typeof raw !== "number" || !Number.isFinite(raw) || raw < 0) {
    return null;
  }
  return raw;
}

export function parseEvaluationTimeoutSeconds(
  evaluationData: EvaluationData | undefined | null,
  fallbackTimeoutSeconds: number
): number {
  if (!evaluationData || typeof evaluationData !== "object" || Array.isArray(evaluationData)) {
    return fallbackTimeoutSeconds;
  }
  const raw = evaluationData.timeout ?? evaluationData.Timeout;
  if (typeof raw === "number" && Number.isFinite(raw) && raw > 0) {
    return raw;
  }
  return fallbackTimeoutSeconds;
}

export function hasExceededEvaluationTimeout(
  evaluationData: EvaluationData | undefined | null,
  fallbackTimeoutSeconds: number,
  baselineSeconds = 0
): boolean {
  const evaluationTimeSeconds = parseEvaluationTimeSeconds(evaluationData);
  if (evaluationTimeSeconds === null) {
    return false;
  }
  const limitSeconds = parseEvaluationTimeoutSeconds(evaluationData, fallbackTimeoutSeconds);
  return evaluationTimeSeconds - baselineSeconds >= limitSeconds;
}

export function evaluationTimeBaseline(
  evaluationData: EvaluationData | undefined | null
): number {
  return parseEvaluationTimeSeconds(evaluationData) ?? 0;
}
