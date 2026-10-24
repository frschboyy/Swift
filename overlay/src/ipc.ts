// WebSocket client for the backend: fetches port + token from Rust, authenticates
// with `hello`, reconnects with backoff.

import { invoke } from "@tauri-apps/api/core";
import { decode, encode, type Inbound, type Outbound } from "./protocol";

type Info = { port: number; token: string };

// starting: the backend is still loading. lost: the socket closed and a reconnect is
// pending. failed: the backend can't run (problem says why), retried with backoff anyway.
export type ConnectionStatus =
  | { phase: "starting" }
  | { phase: "connected" }
  | { phase: "lost" }
  | { phase: "failed"; problem: string };

export class BackendClient {
  private ws: WebSocket | null = null;
  private retry = 0;
  private stopped = false;

  constructor(
    private readonly onMessage: (msg: Inbound) => void,
    private readonly onStatus: (status: ConnectionStatus) => void,
  ) {}

  start(): void {
    void this.connect();
  }

  /** False when the message couldn't be sent (not connected): the caller tells the owner. */
  send(msg: Outbound): boolean {
    if (this.ws?.readyState !== WebSocket.OPEN) return false;
    this.ws.send(encode(msg));
    return true;
  }

  private async info(): Promise<Info> {
    // The backend takes a moment to load; Rust answers "starting" until it's ready.
    let reported = false;
    for (;;) {
      try {
        return await invoke<Info>("backend_info");
      } catch (err) {
        if (String(err) !== "starting") throw new Error(String(err));
        if (!reported) this.onStatus({ phase: "starting" });
        reported = true;
        await new Promise((r) => setTimeout(r, 200));
      }
    }
  }

  private async connect(): Promise<void> {
    if (this.stopped) return;
    let info: Info;
    try {
      info = await this.info();
    } catch (err) {
      this.onStatus({ phase: "failed", problem: (err as Error).message });
      return this.later();
    }

    const ws = new WebSocket(`ws://127.0.0.1:${info.port}`);
    this.ws = ws;
    ws.onopen = () => {
      ws.send(encode({ type: "hello", data: { token: info.token, client: "overlay" } }));
    };
    ws.onmessage = (ev) => {
      const msg = typeof ev.data === "string" ? decode(ev.data) : null;
      if (!msg) return;
      if (msg.type === "hello.ok") {
        this.retry = 0;
        this.onStatus({ phase: "connected" });
      }
      this.onMessage(msg);
    };
    ws.onclose = (ev) => {
      if (this.ws !== ws) return;
      this.ws = null;
      if (ev.code === 4401) this.onStatus({ phase: "failed", problem: "the backend rejected the session token" });
      else this.onStatus({ phase: "lost" });
      this.later();
    };
  }

  private later(): void {
    const delay = Math.min(5000, 250 * 2 ** this.retry++);
    setTimeout(() => void this.connect(), delay);
  }
}
