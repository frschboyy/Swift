// Draws the Deck (deck.ts) in the main window, the same in the app and the harness. An edge keeps its
// element for as long as its request is behind the card, so a click isn't lost to a redraw and an
// edge can move from where it was. Words go through textContent only (dom.ts ``el``).

import { foldLine, type DeckView, type Edge } from "./deck";
import { el, icon } from "./dom";
import type { Row } from "./presenter";
import { fadeIn, leaveTo, moveFrom, type Box } from "./shuffle";
import { edgeContent, edgeTimes, type EdgeView } from "./views";

export type DeckHost = {
  list: HTMLElement;
  // What a row is doing, in words.
  label: (r: Row) => string;
  focus: (runId: string) => void;
  watch: (r: Row) => void;
  // The folded edge was clicked: the long answer closes, and the deck opens again.
  unfold: () => void;
  // Where a new request comes from: the capsule, below the card.
  landingFrom: () => Box;
};

const ENDED: ReadonlySet<string> = new Set(["result", "error", "done"]);
const FOLD = "fold";
/** An edge that came forward waits this long for its card to be drawn. */
const FORWARD_MS = 500;

export class DeckDraw {
  private readonly nodes = new Map<string, HTMLElement>();
  private readonly host: DeckHost;
  // The edge that came forward, for its card to grow out of.
  private forward: { id: string; box: Box; at: number } | null = null;
  // The card in front that is going behind: its edge starts on the card.
  private leaving: { id: string; box: Box } | null = null;

  constructor(host: DeckHost) {
    this.host = host;
  }

  /** The request on the card is going behind it. */
  frontLeaving(id: string, box: Box): void {
    this.leaving = { id, box };
  }

  /** Where the card for ``id`` comes from, if it was an edge just now. */
  takeForward(id: string | null, now: number): Box | null {
    const f = this.forward;
    if (!f || f.id !== id) return null;
    this.forward = null;
    return now - f.at <= FORWARD_MS ? f.box : null;
  }

  /** ``front``: the request in front now. */
  draw(view: DeckView, front: string | null): void {
    const wanted = new Set(view.fold ? [FOLD] : view.edges.map((e) => e.row.runId));
    const arriving: { node: HTMLElement; edge: Edge }[] = [];
    const moved: { node: HTMLElement; box: Box; at: string }[] = [];
    for (const [id, node] of this.nodes) {
      if (wanted.has(id)) {
        moved.push({ node, box: node.getBoundingClientRect(), at: node.style.getPropertyValue("--at") });
        continue;
      }
      this.nodes.delete(id);
      if (id === front) {
        // One body: this edge is the card now.
        this.forward = { id, box: node.getBoundingClientRect(), at: Date.now() };
        node.remove();
      } else {
        node.removeAttribute("data-hit");
        node.style.pointerEvents = "none";
        leaveTo(node, null, () => node.remove());
      }
    }
    if (view.fold) {
      const words = foldLine(view.fold);
      const node = this.nodes.get(FOLD) ?? this.create(FOLD, () => this.host.unfold());
      this.place(node, 0, 10, 0, view.height);
      node.classList.toggle("edge--confirm", view.fold.needOk > 0);
      node.title = "Close the answer to see them";
      if (node.dataset.sig === undefined) fadeIn(node);
      this.fill(node, words, () => [el("span", { class: "edge-mark" }, icon("expand")), el("span", { class: "edge-title" }, words)]);
    }
    for (const edge of view.edges) {
      const id = edge.row.runId;
      const known = this.nodes.get(id);
      const node = known ?? this.create(id, () => this.host.focus(id));
      this.drawEdge(node, edge);
      if (!known) arriving.push({ node, edge });
    }
    this.host.list.hidden = wanted.size === 0;
    edgeTimes(this.host.list);
    // Once all are in place and the deck has its height: from where each one comes.
    for (const { node, box, at } of moved) {
      if (node.style.getPropertyValue("--at") !== at) moveFrom(node, box);  // its slot changed, not the card's height
    }
    for (const { node, edge } of arriving) {
      if (this.leaving?.id === edge.row.runId) moveFrom(node, this.leaving.box);
      else if (edge.landing) moveFrom(node, this.host.landingFrom(), true);
      else fadeIn(node);
    }
    this.leaving = null;
  }

  private create(id: string, click: () => void): HTMLElement {
    const node = el("li", { class: "edge", "data-hit": true, "data-run": id, role: "button", tabindex: "0", onclick: click });
    this.nodes.set(id, node);
    this.host.list.append(node);
    return node;
  }

  private place(node: HTMLElement, depth: number, inset: number, offset: number, peek: number): void {
    node.dataset.depth = String(depth);
    node.style.zIndex = String(30 - depth);
    node.style.setProperty("--inset", `${inset}px`);
    node.style.setProperty("--at", `${offset}px`);
    node.style.setProperty("--peek", `${peek}px`);
  }

  /** Redrawn only when what it says changes: the time ticks by itself, and a press isn't lost. */
  private fill(node: HTMLElement, sig: string, content: () => (Node | string)[]): void {
    if (node.dataset.sig === sig) return;
    node.dataset.sig = sig;
    node.replaceChildren(...content());
  }

  private drawEdge(node: HTMLElement, edge: Edge): void {
    const r = edge.row;
    const v: EdgeView = {
      title: r.title, words: r.words ?? r.title, label: this.host.label(r), startedMs: r.startedMs,
      running: !ENDED.has(r.state), state: r.state, more: edge.more, saying: edge.landing,
    };
    this.place(node, edge.depth, edge.inset, edge.offset, edge.peek);
    node.className = `edge edge--${edge.landing ? "ack" : r.state}`;
    node.title = `${v.words}\nClick to bring it forward`;
    node.setAttribute("aria-label", edge.landing ? `Got it: ${v.words}` : `${v.title}: ${v.label}`);
    this.fill(node, JSON.stringify(v), () => edgeContent(v, () => this.host.watch(r)));
  }
}
