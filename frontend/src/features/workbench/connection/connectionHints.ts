/**
 * What the Connections page says when the selected control node runs without live sessions (its
 * `/cluster/status` reports `live_sessions: false`): it refuses to connect to a broker. Null when
 * they are on, or unknown (an older control node, or the status not loaded yet).
 */
export function liveSessionsOffNote(liveSessions: boolean | undefined): string | null {
  if (liveSessions !== false) {
    return null;
  }
  return (
    "Live sessions are off on this control node: it runs without the Docker socket (its COMPOSE_FILE leaves out " +
    "docker-compose.live-sessions.yml), so it cannot connect to a broker or start live simulations and monitors. " +
    "Campaigns and cluster jobs still run; select a control node with live sessions on for live work."
  );
}

/**
 * Turn the attempted endpoint into the checks that actually resolve a failed connect.
 * The server already says what went wrong; these say what to do about it.
 */
export function connectionHints(usesControlNode: boolean, clientBroker: string, port: number, tlsConnection: boolean): string[] {
  if (usesControlNode) {
    return [
      "The control node's broker runs as the cluster-broker service of the control node's stack: check that it is up with docker ps on the control node's machine.",
      "Pick another broker if this control node was started without one.",
    ];
  }
  const host = clientBroker.trim().toLowerCase();
  const hints: string[] = [];
  if (host === "localhost" || host === "127.0.0.1") {
    hints.push(`The server resolves localhost to its Docker host, so the broker must be published on port ${port} of the control node's machine.`);
  }
  hints.push(`Confirm something listens on ${clientBroker || "the broker host"}:${port} and that the control node's machine can reach it.`);
  if (tlsConnection) {
    hints.push("TLS is on: the port must speak MQTT over TLS (8883 for broker.waraps.org) and the credentials must be valid.");
  } else {
    hints.push("TLS is off: the port must speak plain MQTT (usually 1883).");
  }
  return hints;
}
