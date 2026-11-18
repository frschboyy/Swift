// Halo's anatomy on every card (ADR-019, Step B: the only look). The card
// renderer (card.ts) draws a card as always, marked with its state; this then moves its parts into a state
// line and an origin line. The buttons and the live time are the same elements, so their handlers and the
// once-a-second tick keep working. Words go through textContent only (dom.ts ``el``).

import { el, icon } from "./dom";
import { needsCompact, tailX } from "./geometry";
import { ago } from "./times";

const TAIL_PATH = "M0 0C6 0 9 11 12 11C15 11 18 0 24 0";

/** "just now", kept current by ``dressCards`` (ADR-019 §8.2: no clock times on cards). */
const sinceNow = (): HTMLElement => el("span", { class: "halo-time", "data-at": String(Date.now()) }, ago(Date.now(), Date.now()));

function stateLine(state: string, mark: Node, word: string, time: Node | string | null, close: Element | null): HTMLElement {
  return el("div", { class: `halo-state halo-state--${state}` },
    el("span", { class: "halo-mark" }, mark),
    el("span", { class: "halo-word" }, word),
    time === null ? null : typeof time === "string" ? el("span", { class: "halo-time" }, time) : time,
    el("span", { class: "halo-gap" }),
    close);
}

/** The state line goes first (a one-line card, the amber band and a question's tags already are one); what's
 * left of the head row is the origin line, the owner's words. */
function dress(inner: HTMLElement): void {
  const state = inner.dataset.card;
  const head = inner.querySelector<HTMLElement>(":scope > .card-head");
  const close = head?.querySelector(":scope > .icon-btn") ?? null;
  head?.classList.add("halo-origin");
  const bang = inner.querySelector(":scope > .fail > .bang");
  if (state === "due") {
    inner.prepend(stateLine("due", icon("bell"), "Due", "now", null));
  } else if (state === "working" && head) {
    const spinner = inner.querySelector(":scope > .status > .spinner");
    const time = inner.querySelector<HTMLElement>(":scope > .status > .elapsed");
    time?.classList.add("halo-time");
    if (spinner) inner.prepend(stateLine("working", spinner, "Working", time, close));
  } else if (state === "failed" && bang) {
    inner.prepend(stateLine("failed", bang, "Failed", sinceNow(), close));
  } else if (state === "done" && head && inner.querySelector(":scope > .answer")) {
    inner.prepend(stateLine("done", icon("check"), "Done", sinceNow(), close));
  } else if (state === "notice") {
    notice(inner);
  }
}

/** Board 9 §4, State · Notice: Swift's own notices and problems lead with their mark and title on the
 * 40 px state line; the body keeps the lines under it. Red only where Swift's engine stopped. */
function notice(inner: HTMLElement): void {
  const fail = inner.querySelector<HTMLElement>(":scope > .fail");
  const title = fail?.querySelector<HTMLElement>(".fail-title");
  const mark = fail?.firstElementChild;
  if (!fail || !title || !mark) return;
  const close = inner.querySelector<HTMLElement>(":scope > .icon-btn");
  close?.removeAttribute("style");
  const kind = mark.classList.contains("ok-dot") ? "ready"
    : mark.classList.contains("spinner") ? "busy"
    : mark.classList.contains("bang--info") ? "info" : "bad";
  const glyph = kind === "ready" ? icon("check") : kind === "busy" ? mark : kind === "info" ? icon("info") : el("span", {}, "!");
  inner.prepend(stateLine(`notice halo-state--notice-${kind}`, glyph, title.textContent ?? "", null, close));
  title.remove();
  if (kind !== "busy") mark.remove();
  if (!fail.querySelector(".fail-why")) fail.remove();
}

/** Dresses each card as it's drawn, keeps the tail on the orb and applies the compact rule. */
export function dressCards(stage: HTMLElement): void {
  const card = stage.querySelector<HTMLElement>("#card");
  const capsule = stage.querySelector<HTMLElement>("#capsule");
  const deck = stage.querySelector<HTMLElement>("#rows");
  if (!card || !capsule || !deck) return;  // a pane window

  const ns = "http://www.w3.org/2000/svg";
  const tail = document.createElementNS(ns, "svg");
  tail.setAttribute("class", "halo-tail");
  tail.setAttribute("viewBox", "0 0 24 11");
  tail.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(ns, "path");
  path.setAttribute("d", TAIL_PATH);
  tail.append(path);
  stage.append(tail);

  const fit = (): void => {
    const inner = card.querySelector<HTMLElement>(":scope > .card-in");
    if (inner) {
      // Measured as it would be without the rule; no paint happens in between.
      delete card.dataset.compact;
      const style = getComputedStyle(card);
      const chrome = parseFloat(style.paddingTop) + parseFloat(style.paddingBottom) + parseFloat(style.borderTopWidth) + parseFloat(style.borderBottomWidth);
      const edges = deck.querySelectorAll(".edge").length;
      if (needsCompact(card.classList.contains("card--confirm"), edges, inner.scrollHeight + chrome, deck.offsetHeight, window.innerHeight)) card.dataset.compact = "";
      // Only a card that scrolls needs its footer opaque, over what passes under it.
      card.toggleAttribute("data-scrolls", inner.scrollHeight > inner.clientHeight + 1);
    }
    const shown = card.classList.contains("card--in") && !card.classList.contains("card--held");
    tail.toggleAttribute("data-on", shown);
    if (!shown) return;
    // Layout positions, not the screen's: the card may be mid-growth.
    const dot = [...capsule.querySelectorAll<HTMLElement>(".orb, .cap-ring, .cap-spin")].find((n) => n.offsetParent !== null);
    const centre = capsule.offsetLeft + (dot ? dot.offsetLeft + dot.offsetWidth / 2 : capsule.offsetWidth / 2);
    const x = tailX(centre, card.offsetLeft, card.offsetWidth);
    const above = stage.dataset.anchor?.startsWith("top") ?? false;
    const join = parseFloat(getComputedStyle(card).borderBottomWidth) || 0;
    card.style.setProperty("--tail-x", `${x + 12}px`);
    tail.style.left = `${card.offsetLeft + x}px`;
    tail.style.top = `${above ? card.offsetTop - 11 + join : card.offsetTop + card.offsetHeight - join}px`;
  };

  new MutationObserver(() => {
    const inner = card.querySelector<HTMLElement>(":scope > .card-in");
    if (inner && inner.dataset.dressed === undefined) {
      inner.dataset.dressed = "";
      dress(inner);
    }
    fit();
  }).observe(card, { childList: true, attributes: true, attributeFilter: ["class"] });
  new MutationObserver(fit).observe(capsule, { attributes: true, attributeFilter: ["data-p"] });
  new MutationObserver(fit).observe(deck, { childList: true, attributes: true, attributeFilter: ["hidden"] });
  new MutationObserver(fit).observe(stage, { attributes: true, attributeFilter: ["data-anchor"] });
  const sized = new ResizeObserver(fit);
  sized.observe(card);
  sized.observe(capsule);
  window.addEventListener("resize", fit);
  window.setInterval(() => {
    for (const t of card.querySelectorAll<HTMLElement>(".halo-time[data-at]")) {
      const text = ago(Number(t.dataset.at), Date.now());
      if (t.textContent !== text) t.textContent = text;
    }
  }, 15_000);
}
