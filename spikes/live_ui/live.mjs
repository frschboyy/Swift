// Live UI driver: the real Swift overlay (an isolated test build) on the real desktop.
// CDP into the overlay's WebView2 (state, frames, webview screenshots) + desk.ps1 (real keys, mouse, desktop captures).
// spikes/live_ui: see docs/testing/live-ui-loop.md. Never points at the owner's Swift (port 1420, its hotkeys).
import { spawn, execFileSync } from "node:child_process";
import { writeFileSync, mkdirSync, appendFileSync } from "node:fs";

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const HERE = new URL(".", import.meta.url).pathname.replace(/^\/(\w:)/, "$1");
const CDP = 9230;
export let OUT = `${HERE}/out`;
export const setOut = (d) => { OUT = d; mkdirSync(OUT, { recursive: true }); };

export function desk(...args) {
  return execFileSync("powershell.exe", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", `${HERE}/desk.ps1`, ...args.map(String)], { encoding: "utf8" }).trim();
}

let app = null;
export async function launch(exe = process.env.SWIFT_TEST_EXE ?? "C:/st/t/debug/swift-overlay.exe") {
  const lad = `${process.env.TEMP}\\swift-test\\lad`;
  mkdirSync(lad, { recursive: true });
  app = spawn(exe, [], {
    env: { ...process.env, SWIFT_BACKEND_PORT: "8765", SWIFT_SESSION_TOKEN: "devharness-token-0123456789abcdef", SWIFT_DEV_ALLOW_CAPTURE: "1",
      WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${CDP}`, LOCALAPPDATA: lad },
    stdio: ["ignore", "pipe", "pipe"],
  });
  app.stderr.on("data", (d) => appendFileSync(`${OUT}/app.log`, d));
  app.stdout.on("data", (d) => appendFileSync(`${OUT}/app.log`, d));
  for (let i = 0; i < 60; i++) { try { await fetch(`http://127.0.0.1:${CDP}/json/version`); return app.pid; } catch { await sleep(500); } }
  throw new Error("no CDP on the test overlay");
}
export const quit = () => { try { app?.kill(); } catch {} };
export const targets = async () => (await (await fetch(`http://127.0.0.1:${CDP}/json/list`)).json()).filter((t) => t.type === "page");

async function attach(t) {
  const ws = new WebSocket(t.webSocketDebuggerUrl); await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
  let id = 0; const pend = new Map(); const on = [];
  ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pend.has(d.id)) { pend.get(d.id)(d); pend.delete(d.id); } else on.forEach((f) => f(d)); };
  const send = (method, params = {}) => new Promise((r) => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
  const ev = async (expr) => { const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true }); if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description ?? JSON.stringify(r.result.exceptionDetails)); return r.result?.result?.value; };
  return { send, ev, on, url: t.url, close: () => ws.close() };
}

// The overlay's own socket, borrowed: every frame in and out goes to a timeline; send() speaks as the overlay.
const TAP = `(() => { if (window.__tap) return; const W = window.WebSocket; window.__frames = [];
  window.WebSocket = function (...a) { const s = new W(...a); window.__ws = s; const send = s.send.bind(s);
    s.send = (m) => { try { const f = JSON.parse(m); if (f.type !== "hello") window.__frames.push({ t: Date.now(), dir: "out", type: f.type, data: f.data }); } catch {} return send(m); };
    s.addEventListener("message", (e) => { try { const f = JSON.parse(e.data); if (f.type !== "level") window.__frames.push({ t: Date.now(), dir: "in", type: f.type, data: f.data }); } catch {} }); return s; };
  window.WebSocket.prototype = W.prototype; Object.assign(window.WebSocket, W); window.__tap = true; })()`;

export let ov = null;
export const errors = [];
export async function connect() {
  const t = (await targets()).find((x) => !/pane/.test(x.url) && /localhost:143\d\/?(\?|$|index)/.test(x.url)) ?? (await targets())[0];
  ov = await attach(t);
  await ov.send("Runtime.enable"); await ov.send("Page.enable"); await ov.send("Log.enable");
  ov.on.push((d) => {
    if (d.method === "Runtime.exceptionThrown") errors.push(d.params.exceptionDetails.exception?.description ?? d.params.exceptionDetails.text);
    if (d.method === "Runtime.consoleAPICalled" && d.params.type === "error") errors.push(d.params.args.map((a) => a.value ?? a.description).join(" "));
  });
  await adopt();
  return ov;
}
// Find the overlay's live socket among the page's objects (no reload, no race) and tap it for the timeline.
async function adopt() {
  for (let i = 0; i < 30; i++) {
    const proto = await ov.send("Runtime.evaluate", { expression: "WebSocket.prototype" });
    const q = await ov.send("Runtime.queryObjects", { prototypeObjectId: proto.result.result.objectId });
    const r = await ov.send("Runtime.callFunctionOn", { objectId: q.result.objects.objectId, returnByValue: true, functionDeclaration: `function () {
      const s = [...this].find((w) => w.readyState === 1 && w.url.includes(":8765")); if (!s) return false; if (window.__ws === s) return true;
      window.__ws = s; window.__frames = window.__frames ?? [];
      const send = s.send.bind(s); s.send = (m) => { try { const f = JSON.parse(m); window.__frames.push({ t: Date.now(), dir: "out", type: f.type, data: f.data }); } catch {} return send(m); };
      s.addEventListener("message", (e) => { try { const f = JSON.parse(e.data); if (f.type !== "level") window.__frames.push({ t: Date.now(), dir: "in", type: f.type, data: f.data }); } catch {} });
      return true; }` });
    if (r.result?.result?.value) return true;
    await sleep(500);
  }
  throw new Error("the overlay never opened its backend socket");
}
export const say = (text) => frame("debug.say", { text });
export async function frame(type, data) {
  if (!(await ov.ev("!!(window.__ws && window.__ws.readyState === 1)"))) await adopt();
  return sendRaw(type, data);
}
const sendRaw = (type, data) => ov.ev(`window.__ws.send(JSON.stringify({ v: 1, type: ${JSON.stringify(type)}, ts: Date.now(), data: ${JSON.stringify(data)} })), "sent"`);

// What the owner can see, read from the real DOM, plus what the presenter believes.
export async function look() {
  return JSON.parse(await ov.ev(`JSON.stringify((() => {
    const vis = (e) => { if (!e) return false; const r = e.getBoundingClientRect(); const s = getComputedStyle(e); return !e.hidden && s.display !== "none" && s.visibility !== "hidden" && +s.opacity > 0.05 && r.width > 0 && r.height > 0; };
    const card = document.getElementById("card"), cap = document.getElementById("capsule"), rows = [...document.querySelectorAll("#rows > li")];
    const r = card?.getBoundingClientRect();
    return {
      stage: document.getElementById("stage")?.dataset.state, capsule: cap?.dataset.p, capText: (cap?.querySelector(".cap-text")?.textContent ?? "").trim(),
      card: vis(card) ? { variant: card.dataset.variant ?? card.className, words: card.querySelector(".words")?.textContent ?? "", text: (card.innerText ?? "").replace(/\\s+/g, " ").slice(0, 160),
        buttons: [...card.querySelectorAll("button")].filter(vis).map((b) => (b.getAttribute("aria-label") || b.textContent).trim() + (b.disabled ? " (disabled)" : "")),
        rect: [Math.round(r.x), Math.round(r.y), Math.round(r.right), Math.round(r.bottom)], inWindow: r.x >= 0 && r.y >= 0 && r.right <= innerWidth && r.bottom <= innerHeight } : null,
      rows: rows.filter(vis).map((li) => li.innerText.replace(/\\s+/g, " ").slice(0, 60)),
      cards: document.querySelectorAll(".card").length,
      speaking: window.__overlay?.speaking, presenter: window.__overlay ? Object.keys(window.__overlay.pres ?? {}).length : null,
      frames: window.__frames?.length ?? 0, win: [innerWidth, innerHeight] };
  })())`));
}
export const framesSince = async (n) => JSON.parse(await ov.ev(`JSON.stringify(window.__frames.slice(${n}).map(f => [f.t % 100000, f.dir, f.type, f.type === "state" ? f.data.state : f.type === "result" ? f.data.status : f.type === "transcript" ? (f.data.final ? "final" : "partial") : ""]))`));

// Two pictures of every step: the webview alone (what the overlay drew) and the real desktop (what the owner sees).
export async function shot(name, desktop = true) {
  const r = await ov.send("Page.captureScreenshot", { format: "png" });
  writeFileSync(`${OUT}/${name}.webview.png`, Buffer.from(r.result.data, "base64"));
  // No full-desktop captures: they record the owner's other windows. The webview capture shows only Swift.
}

// Invariants checked after every step: the UI must stay coherent whatever the owner did.
export function check(l, step) {
  const bad = [];
  if (l.cards > 1) bad.push(`${l.cards} card elements`);
  if (l.card && !l.card.inWindow) bad.push(`card outside its window ${l.card.rect}`);
  const dupes = l.rows.filter((r, i) => l.rows.indexOf(r) !== i); if (dupes.length) bad.push(`duplicate deck rows: ${dupes}`);
  if (l.capsule === "listening" && l.card?.variant?.includes("confirm")) bad.push("listening while a confirm card shows");
  if (l.speaking && l.capsule !== "speaking" && l.capsule !== undefined) bad.push(`speaking=true but capsule=${l.capsule}`);
  if (errors.length) bad.push(`page errors: ${errors.splice(0).join(" | ").slice(0, 200)}`);
  return { step, ok: bad.length === 0, bad };
}
