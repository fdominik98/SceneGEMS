const DEFAULT_MONITOR_NAME = "scenario_monitor";

export function defaultMonitorTopic(name: string): string {
  return `waraps/service/virtual/real/${name}`;
}

export { DEFAULT_MONITOR_NAME };
