// Realistic, messy sequences against the live test overlay (isolated build, debug backend, fake connectors).
// Every step: act → wait → read the real DOM + presenter → invariants → webview capture. Keys/clicks only reach the test overlay.
import * as L from "./live.mjs";
import { writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";

const OUT = process.argv[2]; L.setOut(OUT);
const only = process.argv[3]?.split(",");
const log = [];
let PID = 0;
const front = () => Number(L.desk("focused"));

async function step(sc, name, act, wait = 900) {
  const n0 = (await L.look()).frames, fg0 = front(), t0 = Date.now();
  let err = null; try { await act(); } catch (e) { err = e.message; }
  await L.sleep(wait);
  const l = await L.look(); const c = L.check(l, name); if (err) c.bad.push("act: " + err), (c.ok = false);
  const fg1 = front(); if (fg0 !== fg1 && fg1 === PID && !name.includes("text box")) c.bad.push("the overlay took focus"), (c.ok = false);
  const frames = await L.framesSince(n0);
  const i = String(log.filter((x) => x.sc === sc).length + 1).padStart(2, "0");
  await L.shot(`${sc}-${i}-${name.replace(/\W+/g, "_").slice(0, 34)}`, false);
  log.push({ sc, step: name, ms: Date.now() - t0, ...c, capsule: l.capsule, stage: l.stage, speaking: l.speaking, card: l.card && { words: l.card.words, text: l.card.text, buttons: l.card.buttons, inWindow: l.card.inWindow }, rows: l.rows, frames });
  console.log(`${c.ok ? "ok " : "BAD"} ${sc} · ${name} · ${l.capsule}/${l.stage} · ${l.card ? JSON.stringify(l.card.text.slice(0, 80)) : "no card"} · rows ${l.rows.length}${c.ok ? "" : " · " + c.bad.join("; ")}`);
}
const ask = (t) => L.frame("debug.ask", { text: t });
const say = (t) => L.say(t);
const waitFor = async (type, ms = 25000) => { const n = (await L.look()).frames; for (let t = 0; t < ms; t += 400) { const f = await L.framesSince(n); if (f.some((x) => x[2] === type)) return true; await L.sleep(400); } return false; };
const lastConfirm = async () => JSON.parse(await L.ov.ev(`JSON.stringify([...window.__frames].reverse().find(f => f.type === "confirm.request")?.data ?? null)`));

// Real click through Windows hit-testing. The overlay's true screen position is found by trying the mappings
// a mixed-DPI desktop can produce and keeping the one whose point belongs to the test overlay (pidat).
async function realClick(labels) {
  const r = JSON.parse(await L.ov.ev(`JSON.stringify((() => { const e = [...document.querySelectorAll("#card button, #rows button, #stack button")].find(b => { const q = b.getBoundingClientRect(); return q.width > 0 && ${JSON.stringify(labels)}.split("|").includes((b.getAttribute("aria-label") || b.textContent).trim()); }); if (!e) return null; const q = e.getBoundingClientRect(); return { x: q.x + q.width / 2, y: q.y + q.height / 2, dpr: devicePixelRatio, sx: screenX, sy: screenY }; })())`));
  if (!r) throw new Error(`no ${labels} on screen`);
  const rects = L.desk("rect", PID).split(";").map((s) => s.split(",").map(Number)).filter((w) => w[2] - w[0] > 300);
  const cands = [];
  for (const w of rects) cands.push([w[0] + r.x * r.dpr, w[1] + r.y * r.dpr]);
  cands.push([(r.sx + r.x) * r.dpr, (r.sy + r.y) * r.dpr], [r.sx + r.x, r.sy + r.y]);
  for (const [x, y] of cands.map(([a, b]) => [Math.round(a), Math.round(b)])) {
    if (x < 0 || y < 0 || x > 3840 || y > 2160) continue;
    L.desk("move", x, y); await L.sleep(150);            // over a card the 33 ms hit poll turns click-through off
    if (Number(L.desk("pidat", x, y)) !== PID) continue;  // only now can Windows see the overlay under the pointer
    L.desk("click", x, y); return `${x},${y}`;
  }
  throw new Error(`refused: no mapping of ${labels} lands on the test overlay (tried ${cands.map((c) => c.map(Math.round)).join(" ")})`);
}
const ptt = (ms) => L.desk("key", "ctrl+alt+shift+f7", String(ms));   // test hotkeys only exist while the test overlay runs
const typeKey = () => L.desk("key", "ctrl+alt+shift+f8");

const SC = {
  // A realistic run of mistakes: talk, pause, press again, interrupt, correct.
  async messy() {
    await step("messy", "hold push-to-talk 2 s (real mic, room audio)", () => ptt(2000), 3500);
    await step("messy", "press push-to-talk again while it's still answering", () => ptt(400), 2500);
    await step("messy", "ask for research", () => L.frame("debug.run", { scenario: "research" }), 3000);
    await step("messy", "interrupt: a new question mid-run", () => ask("what time is it"), 2500);
    await step("messy", "say stop (which run stops?)", () => say("stop"), 1500);
    await step("messy", "correction: no, I meant the weather", () => ask("no, I meant what's the weather tomorrow"), 2500);
  },
  // State conflicts: answers arriving while an approval waits.
  async conflict() {
    await say("stop"); await L.sleep(800);
    await step("conflict", "email that needs an OK", () => L.frame("debug.run", { scenario: "email" }), 1000);
    await step("conflict", "confirm card arrives", () => waitFor("confirm.request"), 800);
    await step("conflict", "a quick question while the OK waits", () => ask("what time is it"), 2500);
    await step("conflict", "and another", () => ask("what's 12 times 7"), 2500);
    await step("conflict", "real click: Send (twice, 150 ms apart)", async () => { const a = await realClick("Send|Approve"); await L.sleep(150); await realClick("Send|Approve").catch(() => {}); return a; }, 2500);
  },
  // Repeated and late actions.
  async repeat() {
    await say("stop"); await L.sleep(800);
    await step("repeat", "same question three times fast", async () => { await ask("what time is it"); await ask("what time is it"); await ask("what time is it"); }, 3000);
    await step("repeat", "research, then stop three times", async () => { await L.frame("debug.run", { scenario: "research" }); await L.sleep(2500); await say("stop"); await say("stop"); await say("stop"); }, 2000);
    await step("repeat", "stop when nothing runs", () => say("stop"), 1500);
    await step("repeat", "real click: Close, twice", async () => { await realClick("Close"); await L.sleep(100); await realClick("Close").catch(() => {}); }, 1500);
  },
  // The OK that nobody answers: where does it go?
  async timeout() {
    await say("stop"); await L.sleep(800);
    await step("timeout", "email that needs an OK", async () => { await L.frame("debug.run", { scenario: "email" }); await waitFor("confirm.request"); }, 1000);
    await step("timeout", "wait out the countdown (50 s)", async () => {}, 50000);
    await step("timeout", "a new question after it lapsed", () => ask("what time is it"), 2500);
  },
  // Hotkeys over every state.
  async hotkeys() {
    await say("stop"); await L.sleep(800);
    await step("hotkeys", "push-to-talk during a run", async () => { await L.frame("debug.run", { scenario: "research" }); await L.sleep(2000); ptt(800); }, 3000);
    await step("hotkeys", "push-to-talk over a confirm card", async () => { await say("stop"); await L.sleep(800); await L.frame("debug.run", { scenario: "email" }); await waitFor("confirm.request"); ptt(800); }, 3000);
    await step("hotkeys", "text box hotkey over the confirm card", () => typeKey(), 1500);
    await step("hotkeys", "text box hotkey again (toggle?)", () => typeKey(), 1500);
    await step("hotkeys", "ten fast push-to-talk taps", async () => { for (let i = 0; i < 10; i++) ptt(30); }, 3000);
  },
  // The engine dies mid-run and comes back.
  async engine() {
    await say("stop"); await L.sleep(800);
    await step("engine", "research running", () => L.frame("debug.run", { scenario: "research" }), 2500);
    await step("engine", "kill the test backend", () => { execFileSync("powershell.exe", ["-NoProfile", "-Command", "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'swift-test[/\\\\]config.yaml' -and $_.Name -match 'python' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"]); }, 4000);
    await step("engine", "8 s later", async () => {}, 8000);
  },
};

PID = await L.launch(); await L.connect();
console.log("test overlay", PID);
await step("boot", "idle", async () => {}, 600);
for (const [k, f] of Object.entries(SC)) { if (only && !only.includes(k)) continue; try { await f(); } catch (e) { log.push({ sc: k, ok: false, bad: ["crashed: " + e.message] }); console.log("CRASH", k, e.message); } }
writeFileSync(`${OUT}/seq.json`, JSON.stringify(log, null, 2));
L.quit(); process.exit(0);
