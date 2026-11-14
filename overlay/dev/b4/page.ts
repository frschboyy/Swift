// B4 prototype page: one Done card in Halo, with what Swift says aloud and the shape it shows.
// The samples stand in for a worker's typed result; `parseShape` is the boundary they cross.

import { el, icon } from "../../src/dom.ts";
import { drawMermaid } from "./mermaid.ts";
import { drawShape, parseShape } from "./shapes.ts";

type Sample = { asked: string; say: string; raw: unknown };

const SAMPLES: Record<string, Sample> = {
  compare: {
    asked: "Compare the three laptops I was looking at for travel",
    say: "The Zenbook is the best fit for travel: lightest, longest battery, and mid-priced.",
    raw: {
      shape: "compare",
      items: ["Zenbook 14", "XPS 13", "ThinkPad X1"],
      pick: 0,
      rows: [
        { label: "Weight", values: ["1.2 kg", "1.2 kg", "1.1 kg"] },
        { label: "Battery", values: ["15 h", "12 h", "13 h"] },
        { label: "Screen", values: ["14\" OLED", "13.4\" IPS", "14\" IPS"] },
        { label: "Ports", values: ["2×USB-C, HDMI", "2×USB-C", "2×USB-C, 2×USB-A"] },
        { label: "Price", values: ["KSh 165k", "KSh 210k", "KSh 240k"] },
      ],
    },
  },
  diagram: {
    asked: "How does a request go through Swift, as a diagram",
    say: "You speak, Swift hears it, a worker does the job, and you approve anything that changes something.",
    raw: {
      shape: "diagram",
      title: "A request through Swift",
      nodes: [
        { id: "you", label: "You speak" },
        { id: "stt", label: "Speech to text" },
        { id: "route", label: "Swift routes it" },
        { id: "own", label: "Swift's own tool" },
        { id: "worker", label: "Worker (Claude)" },
        { id: "ok", label: "Needs your OK" },
        { id: "card", label: "Result card" },
      ],
      edges: [
        { from: "you", to: "stt" },
        { from: "stt", to: "route" },
        { from: "route", to: "own" },
        { from: "route", to: "worker" },
        { from: "worker", to: "ok", label: "a change" },
        { from: "own", to: "card" },
        { from: "ok", to: "card" },
      ],
    },
  },
  mindmap: {
    asked: "Help me brainstorm a birthday weekend for Ada",
    say: "Four directions: a trip, food, people and a surprise. The coast trip and a small dinner fit best together.",
    raw: {
      shape: "mindmap",
      root: "Ada's birthday weekend",
      children: [
        { label: "A trip", children: [
          { label: "Coast: Diani or Watamu", children: [{ label: "Train there on Friday" }, { label: "Book by the 20th" }] },
          { label: "Naivasha, one night" },
        ] },
        { label: "Food", children: [
          { label: "Dinner at her favourite place" },
          { label: "Cook together", children: [{ label: "Her mum's pilau recipe" }] },
        ] },
        { label: "People", children: [{ label: "Small: six close friends" }, { label: "Call her sister first" }] },
        { label: "Surprise", children: [{ label: "Photo book of the year" }, { label: "A letter from everyone" }] },
      ],
    },
  },
  // A malformed shape (an edge to a node that doesn't exist): the card falls back to words.
  bad: {
    asked: "Draw my week as a diagram",
    say: "Here is your week.",
    raw: { shape: "diagram", nodes: [{ id: "a", label: "Monday" }], edges: [{ from: "a", to: "zz" }] },
  },
};

// Mermaid samples: the same flow as `diagram` (to compare layouts), a sequence, and labels that try markup.
const MERMAID: Record<string, Sample & { source: string }> = {
  "mermaid": { ...SAMPLES.diagram, raw: null, source: `flowchart TD
  you[You speak] --> stt[Speech to text] --> route[Swift routes it]
  route --> own[Swift's own tool]
  route --> worker["Worker (Claude)"]
  worker -- a change --> ok[Needs your OK]
  own --> card[Result card]
  ok --> card` },
  "mermaid-seq": { asked: "Show how approving an email works", say: "Claude drafts it, Swift shows you the card, and it's sent only after you say yes.", raw: null, source: `sequenceDiagram
  participant You
  participant Swift
  participant Claude
  You->>Swift: Email Ada the notes
  Swift->>Claude: the request
  Claude-->>Swift: a draft
  Swift->>You: Needs your OK
  You->>Swift: Swift, send it
  Swift-->>You: Sent` },
  "mermaid-evil": { asked: "Draw it", say: "Here it is.", raw: null, source: `flowchart LR
  a["<img src=x onerror=alert(1)>"] --> b["<script>alert(2)</script>"]
  click a "javascript:alert(3)"` },
};

const q = new URLSearchParams(location.search);
const asked = q.get("shape") ?? "compare";
const sample = MERMAID[asked] ?? SAMPLES[asked] ?? SAMPLES.compare;
const stage = document.getElementById("stage")!;
if (q.get("theme") === "light") stage.dataset.theme = "light";

const shape = parseShape(sample.raw, "source" in sample ? "" : "The worker's answer, as plain text, when its shape didn't check out.");
const slot = el("div", { class: "b4-slot" });
if ("source" in sample) {
  const started = performance.now();
  void drawMermaid(sample.source as string, stage, 1).then((svg) => {
    slot.replaceChildren(svg ?? el("p", {}, "The diagram didn't check out, so here are the words."));
    stage.dataset.mermaidMs = String(Math.round(performance.now() - started));
  });
}
stage.append(el("section", { class: "card card--result card--in b4-card", "data-shape": shape.shape },
  el("div", { class: "card-in" },
    el("div", { class: "halo-state halo-state--done" },
      el("span", { class: "halo-mark" }, icon("check")), el("span", { class: "halo-word" }, "Done"),
      el("span", { class: "halo-time" }, "10:42"), el("span", { class: "halo-gap" })),
    el("header", { class: "card-head halo-origin" }, el("p", { class: "words" }, `“${sample.asked}”`), icon("mic")),
    el("div", { class: "answer" },
      el("p", { class: "b4-said" }, "Said aloud:"),
      el("p", { class: "b4-say" }, sample.say),
      shape.shape !== "text" && shape.title ? el("p", { class: "section-title" }, shape.title) : null,
      "source" in sample ? slot : drawShape(shape)),
    el("footer", { class: "card-foot" }, el("span", { class: "byline" }, "Swift · via Claude")))));
