import { parseServerMessage } from "./protocol";
import type { ParsedServerMessage } from "./protocol";
import type { ClientToServerMessage } from "./wireTypes";

type SocketOutboundMessage = ClientToServerMessage | { type: string; [key: string]: unknown };

export interface BackendWsHandlers {
  onServerMessage: (message: ParsedServerMessage) => void;
  onStatus: (status: "connecting" | "connected" | "disconnected" | "error") => void;
  onError: (message: string) => void;
}

export class BackendWsClient {
  private socket: WebSocket | null = null;
  private reconnectTimeout: number | null = null;
  private manuallyClosed = false;
  private readonly url: string;
  private readonly handlers: BackendWsHandlers;

  constructor(url: string, handlers: BackendWsHandlers) {
    this.url = url;
    this.handlers = handlers;
  }

  connect() {
    this.manuallyClosed = false;
    this.handlers.onStatus("connecting");
    this.socket = new WebSocket(this.url);

    this.socket.onopen = () => {
      this.handlers.onStatus("connected");
    };

    this.socket.onmessage = (event) => {
      try {
        if (import.meta.env.DEV) {
          console.log("[BackendWsClient] RAW_IN", event.data);
        }
        const data = JSON.parse(event.data) as unknown;
        const message = parseServerMessage(data);
        if (import.meta.env.DEV) {
          console.log("[BackendWsClient] IN", { type: message.kind });
        }
        this.handlers.onServerMessage(message);
      } catch (error) {
        console.error("[BackendWsClient] PARSE_ERROR", error, event.data);
        // A single unparseable message must not tear down the session: only flag a
        // transport "error" when the socket is actually gone. While the socket is
        // still OPEN, surface the message but keep streamStatus === "connected" so
        // subsequent valid frames (and the active scenario id) keep flowing.
        const socketOpen = this.socket?.readyState === WebSocket.OPEN;
        if (!socketOpen) {
          this.handlers.onStatus("error");
        }
        this.handlers.onError(
          error instanceof Error ? error.message : "Invalid frame payload."
        );
      }
    };

    this.socket.onerror = () => {
      const isOpen = this.socket?.readyState === WebSocket.OPEN;
      if (!isOpen) {
        this.handlers.onStatus("error");
      }
      this.handlers.onError("WebSocket transport issue.");
    };

    this.socket.onclose = () => {
      this.handlers.onStatus("disconnected");
      this.socket = null;
      if (!this.manuallyClosed) {
        this.scheduleReconnect();
      }
    };
  }

  disconnect() {
    this.manuallyClosed = true;
    if (this.reconnectTimeout) {
      window.clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }
    this.socket?.close();
    this.socket = null;
    this.handlers.onStatus("disconnected");
  }

  send(message: SocketOutboundMessage) {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      this.handlers.onError("Cannot send command: socket is not open.");
      return;
    }
    console.log("[BackendWsClient] OUT", {
      type: message.type,
    });
    this.socket.send(JSON.stringify(message));
  }

  private scheduleReconnect() {
    if (this.reconnectTimeout) {
      return;
    }
    this.reconnectTimeout = window.setTimeout(() => {
      this.reconnectTimeout = null;
      this.connect();
    }, 1500);
  }
}

