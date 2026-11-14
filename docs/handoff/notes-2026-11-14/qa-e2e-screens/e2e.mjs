// QA end-to-end proof (2026-11-14): drives the dev harness against a running debug backend and captures each
// flow, dark and light, as small PNGs, with a JSON log of what the card said and which frames came.
// Usage: node e2e.mjs <outDir> <viteBase> <backendPort> <frames.json>   (ONLY=f1_quick,f2_wifi to run some flows)
// Headless Chrome over CDP (as halo-step-b's capture.mjs). Nothing here touches anything outside the harness:
// the debug backend uses the fake system device, the fake mail and calendar connectors and the echo agent.
import { spawn } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const [out, base, backend, framesFile] = process.argv.slice(2);
mkdirSync(out, { recursive: true });
const F = JSON.parse(readFileSync(framesFile, "utf8"));
const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const profile = join(process.env.TEMP ?? ".", `qa-e2e-chrome-${Date.now()}`);
const chrome = spawn(CHROME, ["--headless=new", "--remote-debugging-port=0", `--user-data-dir=${profile}`, "--disable-gpu",
  "--hide-scrollbars", "--force-device-scale-factor=1", "--no-first-run", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let ver;
for (let i = 0; i < 60 && !ver; i++) { try { const port = readFileSync(join(profile, "DevToolsActivePort"), "utf8").trim().split(/\s+/)[0]; ver = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json(); } catch { await sleep(400); } }
const ws = new WebSocket(ver.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
let id = 0;
const pending = new Map();
const cdpEvents = [];
ws.addEventListener("message", (m) => { const msg = JSON.parse(m.data); if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
  else if (msg.method === "Runtime.exceptionThrown" || (msg.method === "Runtime.consoleAPICalled" && ["error", "warning"].includes(msg.params.type))) cdpEvents.push(msg); });
const consoleSince = (n) => cdpEvents.slice(n).map((e) => e.method === "Runtime.exceptionThrown" ? "exception: " + (e.params.exceptionDetails.exception?.description ?? e.params.exceptionDetails.text).slice(0, 300) : e.params.type + ": " + e.params.args.map((a) => a.value ?? a.description).join(" ").slice(0, 300));
const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
  const n = ++id;
  pending.set(n, (msg) => (msg.error ? reject(new Error(`${method}: ${msg.error.message}`)) : resolve(msg.result)));
  ws.send(JSON.stringify({ id: n, method, params, sessionId }));
});
const { targetId } = await send("Target.createTarget", { url: "about:blank" });
const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
const S = (m, p) => send(m, p, sessionId);
await S("Page.enable");
await S("Runtime.enable");
await S("Emulation.setDeviceMetricsOverride", { width: 720, height: 560, deviceScaleFactor: 1, mobile: false });
const theme = (t) => S("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: t }, { name: "prefers-reduced-motion", value: "reduce" }] });
await theme("dark");
const ev = async (expression) => {
  const r = await S("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) throw new Error(`${expression.slice(0, 80)}: ${r.exceptionDetails.exception?.description ?? r.exceptionDetails.text}`);
  return r.result.value;
};
const J = JSON.stringify;
const log = [];
const note = (flow, what, data) => { log.push({ flow, what, ...data }); console.log(flow, what, J(data).slice(0, 300)); };

async function reload() {
  try { await ev("window.__qaOld = true"); } catch {}
  await S("Page.navigate", { url: `${base}/dev/harness.html?port=${backend}&token=devharness-token-0123456789abcdef&bare` });
  // A new page (not the old one before it unloads) whose socket said hello and got the stack (the resync).
  for (let i = 0; i < 60; i++) { await sleep(250); try { if (await ev("!window.__qaOld && !!(window.__shim && window.__shim.frames.some(f => f.type === 'hello.ok') && window.__shim.frames.some(f => f.type === 'stack'))")) break; } catch {} }
  await sleep(1200);
}
const frameCount = () => ev("window.__shim.frames.length");
async function waitFrame(type, since, pred = "true", ms = 8000) {
  for (let t = 0; t < ms; t += 100) {
    const f = await ev(`(() => { const f = window.__shim.frames.slice(${since}).find(f => f.type === ${J(type)} && ((d) => ${pred})(f.data)); return f ? f.data : null; })()`);
    if (f) return f;
    await sleep(100);
  }
  return null;
}
const sendB = (type, data) => ev(`window.__shim.send(${J(type)}, ${J(data)})`);
const inject = (type, data) => ev(`window.__shim.inject(${J(type)}, ${J(data)})`);
const framesSince = (n) => ev(`window.__shim.frames.slice(${n}).map(f => [f.type, JSON.stringify(f.data).slice(0, 220)])`);
const screen = () => ev(`(() => { const st = document.getElementById('stage'); const c = document.getElementById('card');
  const sk = document.getElementById('stack');
  return { stage: st.dataset.state, card: c.dataset.card ?? null, cardText: c.innerText, stack: sk.hidden ? null : sk.innerText,
    capsule: document.getElementById('capsule').innerText }; })()`);

async function shot(flow, name) {
  const clip = await ev(`(() => { const ids = ['card','capsule','stack','rows','live']; let x0=1e9,y0=1e9,x1=0,y1=0;
    for (const i of ids) { const e = document.getElementById(i); if (!e || e.hidden) continue; const r = e.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) continue; x0=Math.min(x0,r.left); y0=Math.min(y0,r.top); x1=Math.max(x1,r.right); y1=Math.max(y1,r.bottom); }
    if (x0 > x1) return {x:0,y:0,width:720,height:560,scale:1};
    x0=Math.max(0,x0-14); y0=Math.max(0,y0-14); x1=Math.min(720,x1+14); y1=Math.min(560,y1+14);
    return {x:Math.floor(x0),y:Math.floor(y0),width:Math.ceil(x1-x0),height:Math.ceil(y1-y0),scale:1}; })()`);
  const files = [];
  for (const t of ["dark", "light"]) {
    await theme(t);
    await sleep(180);
    const { data } = await S("Page.captureScreenshot", { format: "png", clip });
    const file = `${name}-${t}.png`;
    writeFileSync(join(out, file), Buffer.from(data, "base64"));
    files.push(file);
  }
  await theme("dark");
  note(flow, "shot", { files, screen: await screen() });
}
async function clickText(sel, text) {
  return ev(`(() => { const b = [...document.querySelectorAll(${J(sel)})].find(e => e.offsetParent !== null && e.innerText.trim() === ${J(text)}); if (!b) return false; b.click(); return true; })()`);
}
// Leftovers from an earlier flow live in the backend across reloads: end every item in the stack, then stop.
async function clean() {
  await reload();
  const items = await ev("(() => { const f = [...window.__shim.frames].reverse().find(f => f.type === 'stack'); return f ? f.data.items.map(i => i.id) : []; })()");
  for (const i of items) await sendB("stack.action", { id: i, action: "end" });
  await sendB("cancel", {});
  await sleep(800);
  await reload();
}
async function centre(sel) {
  return ev(`(() => { const e = document.querySelector(${J(sel)}); if (!e) return null; const r = e.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()`);
}
async function mouseClick({ x, y }) {
  await S("Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
  await S("Input.dispatchMouseEvent", { type: "mousePressed", x, y, button: "left", clickCount: 1 });
  await S("Input.dispatchMouseEvent", { type: "mouseReleased", x, y, button: "left", clickCount: 1 });
}
async function clickRow(title, label) {
  const row = await ev(`(() => { const rows = [...document.querySelectorAll('#stack .stack-row')]; const i = rows.findIndex(r => r.innerText.toLowerCase().includes(${J(title)})); return i < 0 ? null : rows[i].dataset.id; })()`);
  if (!row) return false;
  const r = await centre(`#stack .stack-row[data-id="${row}"]`);
  await S("Input.dispatchMouseEvent", { type: "mouseMoved", x: r.x, y: r.y });
  await sleep(300);
  const b = await ev(`(() => { const b = [...document.querySelectorAll('#stack .stack-row[data-id="${row}"] button')].find(b => ${J(label)} === "Open" ? b.classList.contains("btn--primary") : b.innerText.trim() === ${J(label)}); if (!b) return null; const r = b.getBoundingClientRect(); return r.width ? { x: r.left + r.width / 2, y: r.top + r.height / 2 } : null; })()`);
  if (!b) return false;
  await mouseClick(b);
  return true;
}
async function clickRowOld(title, label) {
  return ev(`(() => { const row = [...document.querySelectorAll('#stack .stack-row')].find(r => r.innerText.includes(${J(title)}));
    if (!row) return false; row.dispatchEvent(new PointerEvent('pointerenter', { bubbles: true }));
    const b = [...row.querySelectorAll('button')].find(b => b.innerText.trim() === ${J(label)}); if (!b) return false; b.click(); return true; })()`);
}
const AG = { id: "claude_code", name: "Claude" };

const flows = {
  async f1_quick() {
    await reload();
    const n = await frameCount();
    await sendB("debug.ask", { text: "what time is it" });
    note("1a", "result", { frame: await waitFrame("result", n) });
    await shot("1a", "1a-quick-answer");
  },
  async f1_long() {
    await reload();
    const L = F.long;
    const n0 = await frameCount();
    await inject("transcript", { text: "research the history of tea", final: true });
    await inject("state", { state: "working", run_id: "r305", agent: AG, thread_id: "t305" });
    if (process.env.PROBE) { await inject("state", { state: "result", run_id: "r305", agent: AG, thread_id: "t305" });
      await inject("result", { run_id: "r305", status: "done", summary: F.long.summary, details: F.long.details, agent: AG, note: null, origin: "asked", thread_id: "t305" });
      await sleep(3000); note("probe", "frames", { frames: await framesSince(n0), screen: await screen(),
        shim: await ev("window.__shim.log.slice(-10).map(l => l.cmd)") }); return; }
    await inject("state", { state: "result", run_id: "r305", agent: AG, thread_id: "t305" });
    await inject("result", { run_id: "r305", status: "done", summary: L.summary, details: L.details, agent: AG, note: null, origin: "asked", thread_id: "t305" });
    await sleep(500);
    await shot("1b", "1b-long-collapsed");
    const n1 = await frameCount();
    const clicked = await clickText("#card button", "Read more");
    const probe = `(() => { const c = document.getElementById('card'); const t = c.innerText;
      const end = [...c.querySelectorAll('*')].find(e => e.children.length === 0 && e.textContent.includes('THE-END-MARKER'));
      const sc = [...c.querySelectorAll('*')].filter(e => e.scrollHeight > e.clientHeight + 4 && ['auto','scroll'].includes(getComputedStyle(e).overflowY));
      const er = end?.getBoundingClientRect(); const cr = (sc[0] ?? c).getBoundingClientRect();
      return { stage: document.getElementById('stage').dataset.state, openingCount: t.split('Tea began in southwest China').length - 1, ellipsis: t.includes('…'),
        endVisible: !!er && er.height > 0 && er.top >= cr.top - 1 && er.bottom <= cr.bottom + 1, open: !!c.querySelector('.answer--open'),
        scroller: sc.map(e => e.className + ' ' + e.scrollTop + '/' + (e.scrollHeight - e.clientHeight)) }; })()`;
    for (const ms of [150, 400, 800]) { await sleep(ms === 150 ? 150 : ms - 150); note("1b", `read-more+${ms}ms`, { clicked, ...(await ev(probe)) }); if (ms === 400) await shot("1b", "1b-long-read-more"); }
    // Check 340 step 3: scroll to the end of the answer (the mouse wheel over it, as the owner would).
    const at = await ev(`(() => { const r = document.querySelector('#card .answer--open').getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; })()`);
    for (let i = 0; i < 8; i++) { await S("Input.dispatchMouseEvent", { type: "mouseWheel", x: at.x, y: at.y, deltaX: 0, deltaY: 200 }); await sleep(80); }
    await sleep(500);
    note("1b", "scrolled-to-end", await ev(probe));
    await shot("1b", "1b-long-read-to-end");
    note("1b", "frames-after-read-more", { frames: await framesSince(n1), shim: await ev("window.__shim.log.slice(-6).map(l => l.cmd)") });
  },
  async f2_wifi() {
    const ask = async (flow) => {
      await reload();
      const n = await frameCount();
      await sendB("debug.ask", { text: "turn off Wi-Fi" });
      const a = await waitFrame("ask", n);
      note(flow, "ask", { frame: a });
      await sleep(400);
      return a;
    };
    const after = async (flow, n, ms = 2500) => { await sleep(ms); note(flow, "frames", { frames: await framesSince(n), screen: await screen() }); };
    // yes
    await ask("2a"); await shot("2a", "2a-wifi-question");
    let n = await frameCount(); await sendB("debug.ask", { text: "yes" });
    note("2a", "result", { frame: await waitFrame("result", n) }); await shot("2a", "2a-wifi-yes");
    n = await frameCount(); await sendB("debug.ask", { text: "turn on Wi-Fi" });
    note("2a", "back-on", { frame: await waitFrame("result", n) });
    // no
    await ask("2b"); n = await frameCount(); await sendB("debug.ask", { text: "no" }); await after("2b", n); await shot("2b", "2b-wifi-no");
    // the request said again (A+B)
    await ask("2c"); n = await frameCount(); await sendB("debug.ask", { text: "turn off Wi-Fi" });
    note("2c", "result", { frame: await waitFrame("result", n) }); await shot("2c", "2c-wifi-said-again");
    n = await frameCount(); await sendB("debug.ask", { text: "turn on Wi-Fi" }); note("2c", "back-on", { frame: await waitFrame("result", n) });
    // typed "yes": must never approve
    await ask("2d"); n = await frameCount(); await sendB("text", { text: "yes" }); await after("2d", n); await shot("2d", "2d-wifi-typed-yes");
    await sendB("cancel", {});
    // typed request again: must never approve
    await ask("2e"); n = await frameCount(); await sendB("text", { text: "turn off Wi-Fi" }); await after("2e", n); await shot("2e", "2e-wifi-typed-again");
    await sendB("cancel", {});
  },
  async f3_approvals() {
    const card = async (flow, name, run, c, step) => {
      await reload();
      await inject("transcript", { text: "make a repository for my notes", final: true });
      await inject("state", { state: "working", run_id: run, agent: AG, thread_id: `t${run}` });
      await inject("state", { state: "confirm", run_id: run, agent: AG, thread_id: `t${run}` });
      await inject("confirm.request", { request_id: `${run}:9`, run_id: run, title: c.title, detail: c.detail, tool: "Bash", purpose: c.purpose,
        ...(step ? { step: true } : {}), agent: AG, artifact_id: null, thread_id: `t${run}` });
      await inject("countdown", { request_id: `${run}:9`, left_s: 45, running: true });
      await sleep(500);
      const order = await ev(`(() => { const t = document.getElementById('card').innerText; return { lead: t.indexOf(${J(c.purpose)}), firstLine: t.indexOf(${J(c.detail.split("\n")[0])}) }; })()`);
      note(flow, "order", order);
      await shot(flow, name);
    };
    await card("3a", "3a-b1-command", "b1", F.b1, false);
    await card("3b", "3b-b2-step", "b2", F.b2, true);
    note("3b", "step-said", { said: F.b2.said });
    await card("3c", "3c-delete-own-card", "del", F.delete, false);
    // the backend's own approval card (mock run): a bare "yes" said must not approve; a click does
    await reload();
    let n = await frameCount();
    await sendB("debug.run", { scenario: "confirm" });
    note("3d", "confirm", { frame: await waitFrame("confirm.request", n) });
    await sleep(400); await shot("3d", "3d-backend-confirm");
    n = await frameCount(); await sendB("debug.say", { text: "yes" }); await sleep(2000);
    note("3d", "bare-yes", { frames: await framesSince(n), screen: await screen() });
    n = await frameCount(); note("3d", "click-approve", { clicked: await clickText("#card button", "Approve") });
    note("3d", "after-approve", { frame: await waitFrame("result", n) }); await shot("3d", "3d-after-approve");
  },
  async f4_email() {
    await reload();
    let n = await frameCount();
    await sendB("debug.run", { scenario: "email" });
    note("4a", "confirm", { frame: await waitFrame("confirm.request", n, "true", 15000) });
    await sleep(500); await shot("4a", "4a-email-draft");
    n = await frameCount(); await sendB("debug.say", { text: "approve" }); await sleep(2500);
    note("4a", "bare-approve", { frames: await framesSince(n), screen: await screen() });
    await shot("4a", "4a-after-bare-approve");
    await sendB("cancel", {});
    // Which Sam: the agent's choice question (find_contact found two), as the backend sends it
    await reload();
    await inject("transcript", { text: "Email Sam about Friday", final: true });
    await inject("state", { state: "working", run_id: "x1", agent: AG, thread_id: "tx1" });
    await inject("ask", { ask_id: "a1", run_id: "x1", open: true, question: "Which Sam: Sam Lee or Sam Okoro?", kind: "choice", options: ["Sam Lee", "Sam Okoro"], phase: "listening", seconds: 20, thread_id: "tx1" });
    await sleep(500); await shot("4b", "4b-which-sam");
  },
  async f5_timer_stack() {
    await reload();
    let n = await frameCount();
    await sendB("debug.ask", { text: "set a timer for 6 seconds" });
    note("5a", "timer", { frame: await waitFrame("result", n) });
    await sleep(1500);
    n = await frameCount();
    await sendB("debug.run", { scenario: "confirm" });
    note("5a", "confirm", { frame: await waitFrame("confirm.request", n) });
    await sleep(7000);
    note("5a", "due", { frames: await framesSince(n), screen: await screen() });
    await shot("5a", "5a-timer-due-behind-card");
    n = await frameCount(); note("5a", "reject", { clicked: await clickText("#card button", "Reject") || await clickText("#card button", "Cancel") });
    await sleep(2500); note("5a", "after-reject", { frames: await framesSince(n), screen: await screen() }); await shot("5b", "5b-after-card");
    // the stack: open it, park (Skip), reopen (Open), end (End)
    const openStack = () => ev(`(() => { const s = document.querySelector('#stack .stack'); if (!s) return false; s.dispatchEvent(new MouseEvent('dblclick', {bubbles: true})); return true; })()`);
    note("5c", "open-stack", { opened: await openStack() }); await sleep(600); await shot("5c", "5c-stack-open");
    for (const [flow, label] of [["5d", "Skip"], ["5e", "Open"], ["5f", "End"]]) {
      n = await frameCount();
      let clicked = await clickText("#stack button, #card button", label);
      if (!clicked && label !== "Skip") { await openStack(); await sleep(500); clicked = await clickText("#stack button, #card button", label); }
      await sleep(1500);
      note(flow, label, { clicked, frames: await framesSince(n), screen: await screen() });
      await shot(flow, `${flow}-stack-${label.toLowerCase()}`);
    }
  },
  async f2_typed_named() {
    // intake.approves lets a typed yes WITH Swift's name answer Swift's reversible question; CLAUDE.md says typing never approves.
    for (const [flow, text] of [["2f", "Swift, yes"], ["2g", "Swift, turn off Wi-Fi"]]) {
      await reload();
      let n = await frameCount();
      await sendB("debug.ask", { text: "turn off Wi-Fi" });
      note(flow, "ask", { frame: await waitFrame("ask", n) });
      await sleep(400);
      n = await frameCount(); await sendB("text", { text });
      await sleep(2500);
      note(flow, "frames", { typed: text, frames: await framesSince(n), screen: await screen() });
      await shot(flow, `${flow}-wifi-typed-named`);
      await sendB("debug.ask", { text: "turn on Wi-Fi" }); await sleep(800);
      await sendB("cancel", {});
    }
  },
  async f4_probe() {
    // An agent's question arriving while the start-up "Swift is ready" notice is on the card.
    await clean();
    const c0 = cdpEvents.length;
    for (let i = 0; i < 20 && !(await screen()).cardText.includes("Swift is ready"); i++) await sleep(150);
    const before = await screen();
    const n0 = await frameCount();
    await inject("transcript", { text: "Email Sam about Friday", final: true });
    await inject("state", { state: "working", run_id: "x1", agent: AG, thread_id: "tx1" });
    await inject("ask", { ask_id: "a1", run_id: "x1", open: true, question: "Which Sam: Sam Lee or Sam Okoro?", kind: "choice", options: ["Sam Lee", "Sam Okoro"], phase: "listening", seconds: 20, thread_id: "tx1" });
    const seen = [];
    for (let t = 0; t <= 8000; t += 500) { const sc = await screen(); seen.push([t, sc.stage, sc.cardText.slice(0, 50), sc.capsule.split(String.fromCharCode(10)).join(" ")]); if (t === 1000) await shot("4p", "4p-ask-over-ready-1s"); await sleep(500); }
    note("4p", "timeline", { before: before.cardText.slice(0, 40), seen, frames: await framesSince(n0), console: consoleSince(c0), shim: await ev("window.__shim.log.slice(-12).map(l => l.cmd)") });
    await shot("4p", "4p-ask-over-ready-8s");
  },
  async f4_variants() {
    const ASK = (agent, run) => ({ ask_id: "a-" + run, run_id: run, open: true, question: "Which Sam: Sam Lee or Sam Okoro?", kind: "choice", options: ["Sam Lee", "Sam Okoro"], phase: "listening", seconds: 20, thread_id: "t-" + run });
    const variants = {
      // a: no notice on screen (wait it out), then the same agent question
      a_no_notice: { wait: true, frames: (r) => [["transcript", { text: "Email Sam about Friday", final: true }], ["state", { state: "working", run_id: r, agent: AG, thread_id: "t-" + r }], ["ask", ASK(AG, r)]] },
      // b: notice on screen, only the working state
      b_working_only: { wait: false, frames: (r) => [["transcript", { text: "Email Sam about Friday", final: true }], ["state", { state: "working", run_id: r, agent: AG, thread_id: "t-" + r }]] },
      // c: notice on screen, the question with no working state first
      c_ask_only: { wait: false, frames: (r) => [["ask", ASK(AG, r)]] },
      // d: notice on screen, Swift's own question (agent null), as the Wi-Fi flow sends it
      d_own_question: { wait: false, frames: (r) => [["state", { state: "working", run_id: r, agent: null, thread_id: "t-" + r }], ["ask", { ...ASK(null, r), question: "Turn off Wi-Fi?", kind: "yes_no", options: [] }]] },
    };
    for (const [name, v] of Object.entries(variants)) {
      await clean();
      if (v.wait) { for (let i = 0; i < 40 && (await screen()).cardText.includes("Swift is ready"); i++) await sleep(250); await sleep(500); }
      const before = (await screen()).cardText.slice(0, 20);
      for (const [t, d] of v.frames("v" + name[0])) await inject(t, d);
      const seen = [];
      for (const t of [300, 1500, 3500, 6000]) { await sleep(t - (seen.length ? [300, 1500, 3500, 6000][seen.length - 1] : 0)); const sc = await screen(); seen.push([t, sc.stage, sc.cardText.slice(0, 40), sc.capsule.split(String.fromCharCode(10)).join(" ")]); }
      note("4v", name, { before, seen });
      await shot("4v", `4v-${name}`);
    }
  },
  async f4_real_over_notice() {
    // The same moment with the backend's own frames: Swift's question asked while "Swift is ready" is on the card.
    await clean();
    for (let i = 0; i < 20 && !(await screen()).cardText.includes("Swift is ready"); i++) await sleep(150);
    const before = (await screen()).cardText.slice(0, 20);
    const n0 = await frameCount();
    await sendB("debug.ask", { text: "turn off Wi-Fi" });
    const seen = [];
    for (const t of [300, 1500, 3500, 6000]) { await sleep(t - (seen.length ? [300, 1500, 3500, 6000][seen.length - 1] : 0)); const sc = await screen(); seen.push([t, sc.stage, sc.cardText.slice(0, 40), sc.capsule.split(String.fromCharCode(10)).join(" ")]); }
    note("4r", "timeline", { before, seen, frames: (await framesSince(n0)).map((f) => f[0] + " " + f[1].slice(0, 90)) });
    await shot("4r", "4r-own-question-over-ready");
    await sendB("debug.ask", { text: "no" }); await sleep(800);
  },
  async f4_sam() {
    await clean();
    await sleep(1500);
    const put = async () => {
      // The backend sends the run's row (``runs``, with focus) before its state; without it the overlay draws nothing.
      await inject("runs", { focus: "x1", rows: [{ run_id: "x1", thread_id: "tx1", title: "Email Sam about Friday", state: "working", activity: null, app: null, agent: AG, started_ms: Date.now(), origin: "asked" }] });
      await inject("transcript", { text: "Email Sam about Friday", final: true });
      await inject("state", { state: "working", run_id: "x1", agent: AG, thread_id: "tx1" });
      await inject("ask", { ask_id: "a1", run_id: "x1", open: true, question: "Which Sam: Sam Lee or Sam Okoro?", kind: "choice", options: ["Sam Lee", "Sam Okoro"], phase: "listening", seconds: 20, thread_id: "tx1" });
      await sleep(600);
    };
    const n0 = await frameCount();
    await put();
    if (!(await screen()).cardText.includes("Which Sam")) { note("4b", "first-try", { frames: await framesSince(n0), screen: await screen(), shim: await ev("window.__shim.log.slice(-8).map(l => l.cmd)") }); await sleep(1500); await put(); }
    await shot("4b", "4b-which-sam");
  },
  async f5_stack() {
    const setup = async (flow) => {
      await clean();
      let n = await frameCount();
      await sendB("debug.ask", { text: "set a timer for 6 seconds" });
      note(flow, "timer", { frame: await waitFrame("result", n) });
      await sleep(1500);
      n = await frameCount();
      await sendB("debug.run", { scenario: "confirm" });
      note(flow, "confirm", { frame: await waitFrame("confirm.request", n) });
      note(flow, "stack", { frame: await waitFrame("stack", n, "d.items.length > 0", 15000) });
      await sleep(600);
    };
    const openStack = async () => { const at = await centre("#stack .stack"); if (!at) return false; await mouseClick(at); await sleep(120); await mouseClick(at); return true; };
    const act = async (flow, label, name) => {
      const n = await frameCount();
      const clicked = await clickRow("timer", label);
      await sleep(1500);
      note(flow, label, { clicked, frames: await framesSince(n), screen: await screen() });
      await shot(flow, name);
    };
    await setup("5a");
    await shot("5a", "5a-timer-due-behind-card");
    note("5c", "open-stack", { opened: await openStack() }); await sleep(700); await shot("5c", "5c-stack-open");
    await act("5d", "Skip", "5d-stack-park");
    if (!(await ev("!!document.querySelector('#stack .stack-open')"))) { await openStack(); await sleep(700); }
    await act("5e", "Open", "5e-stack-reopen");
    { const n = await frameCount(); await sleep(2000); note("5e", "after-open-2s", { frames: await framesSince(n), screen: await screen() });
      note("5e", "reject", { clicked: await clickText("#card button", "Reject") }); await sleep(2500);
      note("5e", "after-card", { frames: await framesSince(n), screen: await screen() }); await shot("5e", "5e-after-card"); }
    // End: a fresh timer behind a fresh card, ended from the stack; after the card, it must not come back.
    await setup("5f");
    await openStack(); await sleep(700);
    await act("5f", "End", "5f-stack-end");
    let n = await frameCount();
    note("5f", "reject", { clicked: await clickText("#card button", "Reject") });
    await sleep(3000);
    note("5f", "after-card", { frames: await framesSince(n), screen: await screen() });
    await shot("5f", "5f-after-card-nothing-back");
  },
  async f5_park() {
    // Park, reopen and end on the stack: Swift's question, set aside by a new request (test_seam_replay's scenario).
    const openStack = async () => { const at = await centre("#stack .stack"); if (!at) return false; await mouseClick(at); await sleep(120); await mouseClick(at); await sleep(700); return true; };
    const park = async (flow) => {
      const n = await frameCount();
      await sendB("debug.ask", { text: "what time is it" });
      note(flow, "parked", { stack: await waitFrame("stack", n, "d.items.some(i => i.kind === 'parked')"), screen: await screen() });
      await sleep(4000);  // the quick answer's card reads and goes
    };
    await clean();
    let n = await frameCount();
    await sendB("debug.ask", { text: "turn off Wi-Fi" });
    note("5g", "ask", { frame: await waitFrame("ask", n) });
    await sleep(500);
    await park("5g");
    await shot("5g", "5g-question-parked");
    note("5h", "open-stack", { opened: await openStack() }); await shot("5h", "5h-stack-open");
    n = await frameCount();
    note("5h", "open", { clicked: await clickRow("wi-fi", "Open") });
    note("5h", "reopened", { ask: await waitFrame("ask", n), screen: await screen() });
    await sleep(500); await shot("5h", "5h-question-reopened");
    await park("5i");
    await openStack();
    n = await frameCount();
    note("5i", "skip", { clicked: await clickRow("wi-fi", "Skip") }); await sleep(1200);
    note("5i", "after-skip", { frames: await framesSince(n), screen: await screen() });
    if (!(await ev("!!document.querySelector('#stack .stack-open')"))) await openStack();
    n = await frameCount();
    note("5j", "end", { clicked: await clickRow("wi-fi", "End") }); await sleep(1500);
    note("5j", "after-end", { frames: await framesSince(n), screen: await screen() });
    await shot("5j", "5j-question-ended");
  },
  async f6_web() {
    // C3 runs inside the agent (desktop_open); the harness's agent is the echo executor, so the request only
    // shows that it reached the agent and opened nothing. The rules are proven by unit tests (see the note).
    await reload();
    for (const [flow, text] of [["6a", "open usiu dot ac dot ke"], ["6b", "open that site again"], ["6c", "open my university's website"]]) {
      const n = await frameCount();
      await sendB("debug.ask", { text });
      note(flow, "result", { frame: await waitFrame("result", n) });
      await sleep(300); await shot(flow, `${flow}-web`);
    }
  },
};

const only = process.env.ONLY ? process.env.ONLY.split(",") : Object.keys(flows);
for (const k of only) {
  try { await flows[k](); } catch (e) { note(k, "ERROR", { error: String(e.stack ?? e) }); }
}
writeFileSync(join(out, `e2e-log${process.env.ONLY ? "-" + process.env.ONLY.replaceAll(",", "_") : ""}.json`), J(log, null, 1));
ws.close();
try { (await import("node:child_process")).execSync(`taskkill /T /F /PID ${chrome.pid}`, { stdio: "ignore" }); } catch { chrome.kill(); }
process.exit(0);
