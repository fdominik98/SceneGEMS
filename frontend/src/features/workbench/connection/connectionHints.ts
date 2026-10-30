/**
 * What the Connections page says when the selected master runs without live sessions (its
 * `/cluster/status` reports `live_sessions: false`): it refuses to connect to a broker. Null when
 * they are on, or unknown (an older master, or the status not loaded yet).
 */
export function liveSessionsOffNote(liveSessions: boolean | undefined): string | null {
  if (liveSessions !== false) {
    return null;
  }
  return (
    "Live sessions are off on this master: it runs without the Docker socket (its COMPOSE_FILE leaves out " +
    "docker-compose.live-sessions.yml), so it cannot connect to a broker or start live simulations and monitors. " +
    "Campaigns and cluster jobs still run; select a master with live sessions on for live work."
  );
}

/**
 * Turn the attempted endpoint into the checks that actually resolve a failed connect.
 * The server already says what went wrong; these say what to do about it.
 */
export function connectionHints(usesMaster: boolean, clientBroker: string, port: number, tlsConnection: boolean): string[] {
  if (usesMaster) {
    return [
      "The master's broker runs as the cluster-broker service of the master's stack: check that it is up with docker ps on the master's machine.",
      "Pick another broker if this master was started without one.",
    ];
  }
  const host = clientBroker.trim().toLowerCase();
  const hints: string[] = [];
  if (host === "localhost" || host === "127.0.0.1") {
    hints.push(`The server resolves localhost to its Docker host, so the broker must be published on port ${port} of the master's machine.`);
  }
  hints.push(`Confirm something listens on ${clientBroker || "the broker host"}:${port} and that the master's machine can reach it.`);
  if (tlsConnection) {
    hints.push("TLS is on: the port must speak MQTT over TLS (8883 for broker.waraps.org) and the credentials must be valid.");
  } else {
    hints.push("TLS is off: the port must speak plain MQTT (usually 1883).");
  }
  return hints;
}
