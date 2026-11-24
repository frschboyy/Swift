// Dev-only stand-in for Tauri's injected internals, so the overlay UI can be
// developed in a plain browser against a backend started by hand.
// Usage: http://localhost:1420/dev/harness.html?port=<n>&token=<token>[&anchor=top-right][&theme=light]
// A pane window's page (dev/pane.html) passes ?label=pane-…: the shim says it is that window.
// Never loaded by index.html or the production build.

export {};

type Callback = (payload: unknown) => void;

const params = new URLSearchParams(location.search);
// A13 harness state (?explore=1): window.__shim.emit("follow", {phase: "out"}) fades the orb, {phase: "in"} brings it back.
// A11 (?explore=1): the backend's hints.py payload; ?learned=1 seeds 3 manual Copy clicks.
const HARNESS_HINTS = {
  verbs: [{ learn: "copy", label: "Put it in Word", say: "put that in Word", ok: true }, { learn: "show", label: "Show me again", say: "show me again", ok: false }],
};
try { if (params.get("learned") === "1") localStorage.setItem("swift.learned", JSON.stringify({ copy: 3 })); } catch { /* none */ }
const callbacks = new Map<number, Callback>();
const listeners = new Map<string, number[]>();
let nextId = 1;

const log: { cmd: string; args: unknown }[] = [];
const copied: string[] = [];

const windowLabel = params.get("label") ?? "overlay";
// What a pane sent to the main window (``pane-action``), for checks by eye.
const emitted: unknown[] = [];

const internals = {
  metadata: { currentWindow: { label: windowLabel }, currentWebview: { label: windowLabel, windowLabel } },
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
      case "fit_pane":
      case "close_pane":
      case "reveal":
      case "set_anchor":
      case "set_smart":
        return null;
      case "drag_pane":
        return false;  // a press that doesn't move: a click
      case "watch_outside":
        return new Promise(() => {});  // no click outside in the harness
      case "get_prefs":
        return { anchor: params.get("anchor") ?? "bottom-center", smart: true };
      case "plugin:event|emit_to":
      case "plugin:event|emit":
        emitted.push(args);
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

// No ?port= (design states only): a stand-in socket that says hello back and never drops, so injected frames
// draw and no connection card covers them.
if (!params.get("port")) {
  window.WebSocket = class extends EventTarget {
    readyState = NativeWebSocket.OPEN;
    onopen: ((ev: Event) => void) | null = null;
    onmessage: ((ev: MessageEvent) => void) | null = null;
    onclose: ((ev: CloseEvent) => void) | null = null;
    constructor() {
      super();
      socket = this as unknown as WebSocket;
      this.addEventListener("message", (ev) => this.onmessage?.(ev as MessageEvent));
      setTimeout(() => this.onopen?.(new Event("open")));
    }
    send(raw: string): void {
      if (JSON.parse(raw).type === "hello") this.dispatchEvent(new MessageEvent("message", { data: JSON.stringify({ v: 1, type: "hello.ok", ts: Date.now(), data: { version: "dev", debug: true, hotkeys: { push_to_talk: "Ctrl+Shift+Space", type: "Ctrl+Alt+Space" }, explore: { orb_glance: params.get("explore") === "1", follow_monitor: params.get("explore") === "1", next_steps: params.get("explore") === "1" }, ...(params.get("explore") === "1" ? { hints: HARNESS_HINTS } : {}) } }) }));
    }
    close(): void {}
  } as unknown as typeof WebSocket;
}

(window as unknown as Record<string, unknown>).__TAURI_INTERNALS__ = internals;
(window as unknown as Record<string, unknown>).__shim = {
  log,
  frames,
  copied,
  emitted,
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
