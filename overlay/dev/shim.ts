// Dev-only stand-in for Tauri's injected internals, so the overlay UI can be
// developed in a plain browser against a backend started by hand.
// Usage: http://localhost:1420/dev/harness.html?port=<n>&token=<token>[&anchor=top-right]
// Never loaded by index.html or the production build.

export {};

type Callback = (payload: unknown) => void;

const params = new URLSearchParams(location.search);
const callbacks = new Map<number, Callback>();
const listeners = new Map<string, number[]>();
let nextId = 1;

const log: { cmd: string; args: unknown }[] = [];
const copied: string[] = [];

const internals = {
  metadata: { currentWindow: { label: "overlay" }, currentWebview: { label: "overlay", windowLabel: "overlay" } },
  transformCallback(cb: Callback): number {
    const id = nextId++;
    callbacks.set(id, cb);
    return id;
  },
  unregisterCallback(id: number): void {
    callbacks.delete(id);
  },
  async invoke(cmd: string, args: Record<string, unknown> = {}): Promise<unknown> {
    log.push({ cmd, args });
    switch (cmd) {
      case "backend_info":
        return { port: Number(params.get("port")), token: params.get("token") ?? "" };
      case "register_hotkeys":
        return [];
      case "set_escape":
      case "set_hit_regions":
      case "begin_drag":
      case "open_logs":
      case "set_status":
        return null;
      case "copy_text":
        copied.push(String(args.text));
        return null;
      case "get_placement":
        return { anchor: params.get("anchor") ?? "bottom-center", flipped: false };
      case "overlay_ready":
        return { startup_ms: Math.round(performance.now()), backend_ms: null };
      case "plugin:event|listen": {
        const event = String(args.event);
        listeners.set(event, [...(listeners.get(event) ?? []), Number(args.handler)]);
        return Number(args.handler);
      }
      case "plugin:event|unlisten":
        return null;
      default:
        throw new Error(`dev shim: unhandled command ${cmd}`);
    }
  },
};

// Record every backend frame (except mic levels) with the time it arrived.
const frames: { t: number; type: string; data: unknown }[] = [];
let socket: WebSocket | null = null;
const NativeWebSocket = window.WebSocket;
window.WebSocket = class extends NativeWebSocket {
  constructor(url: string | URL, protocols?: string | string[]) {
    super(url, protocols);
    socket = this;
    this.addEventListener("message", (ev) => {
      const msg = JSON.parse(String(ev.data));
      if (msg.type !== "level") frames.push({ t: Math.round(performance.now()), type: msg.type, data: msg.data });
    });
  }
};

(window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = internals;
(window as unknown as Record<string, unknown>).__shim = {
  log,
  frames,
  copied,
  /** Send a frame to the backend as the overlay would, e.g. send("debug.say", {text: "show me"}). */
  send(type: string, data: Record<string, unknown> = {}): boolean {
    if (!socket || socket.readyState !== NativeWebSocket.OPEN) return false;
    socket.send(JSON.stringify({ v: 1, type, ts: Date.now(), data }));
    return true;
  },
  /** Deliver a frame to the overlay as if the backend sent it, e.g. inject("state", {state: "working"}). */
  inject(type: string, data: Record<string, unknown> = {}): boolean {
    if (!socket) return false;
    socket.dispatchEvent(new MessageEvent("message", { data: JSON.stringify({ v: 1, type, ts: Date.now(), data }) }));
    return true;
  },
  /** Simulate a Rust-side event, e.g. emit("hotkey", {name: "debug", state: "down"}). */
  emit(event: string, payload: unknown): void {
    for (const id of listeners.get(event) ?? []) callbacks.get(id)?.({ event, id, payload });
  },
};
