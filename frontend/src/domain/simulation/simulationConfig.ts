const DEFAULT_WS = "ws://127.0.0.1:5174/ws/scenegems_backend_service";

export function getSimulationWsUrl(): string {
  const fromEnv = import.meta.env.VITE_WS_URL;
  return typeof fromEnv === "string" && fromEnv.length > 0 ? fromEnv : DEFAULT_WS;
}
