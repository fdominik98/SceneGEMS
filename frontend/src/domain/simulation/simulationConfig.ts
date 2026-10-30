export const GATEWAY_PATH = "/ws/scenegems_backend_service";

/**
 * The workbench gateway's WebSocket URL: the active cluster's master-api serves it on its
 * operator listener, next to the job API, so the workbench follows the cluster selected in the
 * left pane. Without a selected cluster there is no gateway (null).
 */
export function gatewayWsUrl(operatorUrl: string | null): string | null {
  if (!operatorUrl) {
    return null;
  }
  return operatorUrl.replace(/\/+$/, "").replace(/^http(s?):\/\//i, (_match, secure: string) => `ws${secure}://`) + GATEWAY_PATH;
}
