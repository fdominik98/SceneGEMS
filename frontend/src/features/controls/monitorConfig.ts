import type { ClientToServerMessage } from "../../domain/simulation/wireTypes";
import { DEFAULT_MONITOR_NAME, defaultMonitorTopic } from "./monitorTopic";

const KEY_PREFIX = "scenegems:";

function readPersisted<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") {
    return fallback;
  }
  try {
    const raw = window.localStorage.getItem(KEY_PREFIX + key);
    if (raw === null) {
      return fallback;
    }
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

export interface PersistedMonitorConfig {
  scope: "internal" | "external";
  name: string;
  topic: string;
}

export function readPersistedMonitorConfig(): PersistedMonitorConfig {
  const name = readPersisted("monitor-name", DEFAULT_MONITOR_NAME);
  return {
    scope: readPersisted<"internal" | "external">("monitor-scope", "internal"),
    name,
    topic: readPersisted("monitor-topic", defaultMonitorTopic(name)),
  };
}

export function buildInitializeMonitorMessage(
  colregsConstraintsContent: string,
  config: PersistedMonitorConfig = readPersistedMonitorConfig()
): ClientToServerMessage {
  const trimmedName = config.name.trim() || DEFAULT_MONITOR_NAME;
  return {
    type: "initialize_monitor",
    scope: config.scope,
    name: trimmedName,
    topic: config.topic.trim() || defaultMonitorTopic(trimmedName),
    colregsConstraintsContent,
  };
}

export function canInitializeMonitor(
  warapsStatus: "connected" | "disconnected",
  monitorStatus: "connected" | "disconnected",
  colregsConstraintsContent: string
): boolean {
  return (
    warapsStatus === "connected" &&
    monitorStatus !== "connected" &&
    colregsConstraintsContent.trim().length > 0
  );
}
