// Dev only: the B6 study (docs/design/b6-live-view.md). Two feels for the live view, driven by fake
// runs: an email written and filled into Gmail, and a five-slide deck. Nothing here is product code.

import { el, icon } from "../src/dom";

type Step = { at: number; tool: string; line: string; result?: string };
type Slide = { title: string; bullets: string[] };

const p = new URLSearchParams(location.search);
const WORK = p.get("work") === "deck" ? "deck" : "email";
const FEEL = p.get("feel") === "technical" ? "technical" : "visual";
const AT = p.has("at") ? Number(p.get("at")) : null;
const stage = document.getElementById("stage")!;
if (p.get("theme") === "light") stage.dataset.theme = "light";

// ---- fake runs ---------------------------------------------------------------------------

const EMAIL = {
  title: "Email Sam about lunch on Thursday",
  to: "Sam Okafor",
  subject: "Lunch on Thursday",
  body: "Hi Sam,\n\nAre you still free for lunch on Thursday? I was thinking Café Nord at half past twelve, since it's close to both of us.\n\nIf another day suits you better, just say and I'll move things around.\n\nSee you soon,\nFrancis",
  // The draft streams in from 2.4 s to 9 s (the model writing it); Gmail is filled from 10 s.
  write: [2400, 9000] as const,
  fill: { to: 10000, body: 10800, subject: 11600 },
  end: 12600,
  steps: [
    { at: 0, tool: "find_contact", line: "Finding the contact", result: "1 match" },
    { at: 1800, tool: "draft_email", line: "Writing the email" },
    { at: 9000, tool: "draft_email", line: "Draft ready", result: "5 paragraphs" },
    { at: 10000, tool: "fill_in_email", line: "Filling in Gmail: To" },
    { at: 10800, tool: "fill_in_email", line: "Filling in Gmail: message" },
    { at: 11600, tool: "fill_in_email", line: "Filling in Gmail: subject" },
    { at: 12600, tool: "fill_in_email", line: "Compose window ready", result: "not sent" },
  ] as Step[],
};

const SLIDES: Slide[] = [
  { title: "A short history of tea", bullets: ["From a Chinese legend to the world's second drink"] },
  { title: "Origins in China", bullets: ["Legend: Shennong, 2737 BC", "Tang dynasty: tea as an art", "Lu Yu writes The Classic of Tea"] },
  { title: "Tea goes west", bullets: ["Dutch traders, early 1600s", "Catherine of Braganza brings it to England", "The East India Company"] },
  { title: "Tea in Kenya", bullets: ["First bushes at Limuru, 1903", "Now the largest black-tea exporter", "Smallholders grow most of it"] },
  { title: "Tea today", bullets: ["Over 6 million tonnes a year", "Green, black, oolong, white", "Questions?"] },
];

const DECK = {
  title: "Make a deck on the history of tea",
  slideMs: 2200,
  first: 3200,
  end: 3200 + SLIDES.length * 2200 + 900,
  steps: [
    { at: 0, tool: "WebSearch", line: "Searching: history of tea", result: "8 results" },
    { at: 900, tool: "WebFetch", line: "Reading britannica.com", result: "read" },
    { at: 1800, tool: "WebFetch", line: "Reading teaboard.or.ke", result: "read" },
    { at: 2600, tool: "build_deck", line: "Planning 5 slides" },
    ...SLIDES.map((_, i) => ({ at: 3200 + i * 2200, tool: "build_deck", line: `Slide ${i + 1} of 5` })),
    { at: 3200 + 5 * 2200, tool: "save", line: "Saving history-of-tea.pptx", result: "Documents" },
  ] as Step[],
};

const RUN = WORK === "email" ? EMAIL : DECK;

// ---- what the run looks like at time t -------------------------------------------------

const clock = (ms: number): string => {
  const s = Math.floor(ms / 1000);
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}.${Math.floor((ms % 1000) / 100)}`;
};

function shownBody(t: number): string {
  const [a, b] = EMAIL.write;
  if (t <= a) return "";
  const words = EMAIL.body.split(/(?<=\s)/);
  const n = Math.min(words.length, Math.ceil(((t - a) / (b - a)) * words.length));
  return words.slice(0, n).join("");
}

/** Slide i at t: null before it starts, else how many of its parts (title, then bullets) show. */
function slideParts(i: number, t: number): number | null {
  const start = DECK.first + i * DECK.slideMs;
  if (t < start) return null;
  const parts = 1 + SLIDES[i].bullets.length;
  return Math.min(parts, 1 + Math.floor(((t - start) / (DECK.slideMs * 0.8)) * parts));
}

// ---- the working card, as it is today (for the comparison) -----------------------------

function workingCard(t: number): HTMLElement {
  const steps = RUN.steps.filter((s) => s.at <= t);
  const now = steps[steps.length - 1];
  const done = t >= RUN.end;
  return el("section", { class: "b6-working" },
    el("p", { class: "b6-cap" }, "The working card (today)"),
    el("div", { class: "b6-work-card" },
      el("p", { class: "b6-work-words" }, RUN.title),
      el("div", { class: "b6-work-now" },
        done ? el("span", { class: "ok-dot" }, icon("check")) : el("span", { class: "spinner spinner--small" }),
        el("span", {}, done ? "Done" : now.line)),
      el("div", { class: "card-foot" },
        el("button", { class: "btn btn--ghost btn--small" }, icon("play"), "Watch"),
        el("button", { class: "btn btn--ghost btn--small" }, icon("stop"), "Stop"))));
}

// ---- the live view: its frame (one for both feels) -------------------------------------

function frame(t: number, body: HTMLElement, ticker: HTMLElement | null): HTMLElement {
  const done = t >= RUN.end;
  const app = WORK === "email" ? "Gmail" : "PowerPoint";
  return el("section", { class: `b6-live b6-live--${FEEL}${done ? " b6-live--done" : ""}`, role: "region", "aria-label": `Watching: ${RUN.title}` },
    el("header", { class: "b6-bar" },
      el("span", { class: "b6-rec" }, done ? "DONE" : "LIVE"),
      el("span", { class: "b6-title" }, RUN.title),
      el("span", { class: "b6-clock" }, clock(Math.min(t, RUN.end))),
      el("button", { class: "icon-btn", "aria-label": "Close" }, icon("x"))),
    body,
    ticker,
    el("footer", { class: "b6-foot" },
      el("button", { class: "btn btn--ghost btn--small" }, icon("external"), `Show in ${app}`),
      done ? null : el("button", { class: "btn btn--ghost btn--small" }, icon("stop"), "Stop")));
}

// ---- technical feel: a console of what Swift does ---------------------------------------

function technical(t: number): HTMLElement {
  const rows = RUN.steps.filter((s) => s.at <= t);
  const extra: HTMLElement[] = [];
  if (WORK === "email" && t > EMAIL.write[0] && t < EMAIL.write[1]) {
    const words = shownBody(t).split(/\s+/).filter(Boolean).length;
    extra.push(el("li", { class: "b6-con-row b6-con-row--now" }, el("span", { class: "b6-con-t" }, clock(t)), el("span", { class: "b6-con-tool" }, "draft_email"), el("span", {}, `writing · ${words} words`)));
  }
  return el("div", { class: "b6-console", tabindex: "0" },
    el("ol", {},
      ...rows.map((s, i) => {
        const last = i === rows.length - 1 && !extra.length && t < RUN.end;
        return el("li", { class: `b6-con-row${last ? " b6-con-row--now" : ""}` },
          el("span", { class: "b6-con-t" }, clock(s.at)),
          el("span", { class: "b6-con-tool" }, s.tool),
          el("span", {}, s.line),
          s.result && !last ? el("span", { class: "b6-con-res" }, `→ ${s.result}`) : null);
      }),
      ...extra));
}

// ---- visual feel: the thing being made, with one technical line under it ---------------

function emailSheet(t: number): HTMLElement {
  const body = shownBody(t);
  const writing = t > EMAIL.write[0] && t < EMAIL.write[1];
  const f = EMAIL.fill;
  const filling = (k: keyof typeof f, next: number) => t >= f[k] && t < next;
  const field = (k: keyof typeof f, next: number) => `b6-field${filling(k, next) ? " b6-field--now" : ""}${t >= next ? " b6-field--in" : ""}`;
  return el("div", { class: "b6-sheet b6-mail" },
    el("div", { class: field("to", f.body) }, el("span", { class: "b6-label" }, "To"), t >= 1200 ? el("span", { class: "b6-chip" }, EMAIL.to) : null),
    el("div", { class: field("subject", EMAIL.end) }, el("span", { class: "b6-label" }, "Subject"), t >= 2000 ? el("span", {}, EMAIL.subject) : null),
    el("div", { class: `b6-mail-body${filling("body", f.subject) ? " b6-field--now" : ""}` },
      ...body.split("\n").map((line, i, all) => el("p", { class: i === all.length - 1 && writing ? "b6-caret" : "" }, line))));
}

function slideView(s: Slide, parts: number, big: boolean): HTMLElement {
  return el("div", { class: `b6-slide${big ? " b6-slide--big" : ""}${parts === 0 ? " b6-slide--empty" : ""}` },
    parts >= 1 ? el("h4", {}, s.title) : null,
    el("ul", {}, ...s.bullets.slice(0, Math.max(0, parts - 1)).map((b) => el("li", {}, b))));
}

function deckStage(t: number): HTMLElement {
  const started = SLIDES.map((_, i) => slideParts(i, t));
  const current = Math.max(0, started.filter((x) => x !== null).length - 1);
  const big = started[current];
  return el("div", { class: "b6-deck" },
    el("div", { class: "b6-sheet b6-deck-main" },
      big === null
        ? el("p", { class: "b6-wait" }, t < 2600 ? "Reading sources…" : "Planning the slides…")
        : slideView(SLIDES[current], big, true)),
    el("ol", { class: "b6-strip" },
      ...SLIDES.map((s, i) => el("li", { class: `${i === current && big !== null && t < DECK.end ? "b6-strip--now" : ""}` },
        started[i] === null ? el("div", { class: "b6-slide b6-slide--empty" }) : slideView(s, started[i]!, false),
        el("span", {}, String(i + 1))))));
}

function ticker(t: number): HTMLElement {
  const now = RUN.steps.filter((s) => s.at <= t).pop()!;
  return el("p", { class: "b6-ticker" },
    el("span", { class: "b6-con-t" }, clock(now.at)),
    el("span", { class: "b6-con-tool" }, now.tool),
    el("span", {}, now.line),
    now.result ? el("span", { class: "b6-con-res" }, `→ ${now.result}`) : null);
}

// ---- draw ------------------------------------------------------------------------------

function draw(t: number): void {
  const live = FEEL === "technical"
    ? frame(t, technical(t), null)
    : frame(t, WORK === "email" ? emailSheet(t) : deckStage(t), ticker(t));
  stage.replaceChildren(workingCard(t), live);
  const con = stage.querySelector<HTMLElement>(".b6-console");
  if (con) con.scrollTop = con.scrollHeight;
}

if (AT !== null) draw(AT);
else {
  const t0 = performance.now();
  const loop = (): void => {
    const t = (performance.now() - t0) % (RUN.end + 4000);
    draw(t);
    setTimeout(loop, 100);
  };
  loop();
}
