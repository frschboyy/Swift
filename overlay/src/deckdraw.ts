// Draws the Deck (deck.ts) in the main window, the same in the app and the harness. An edge keeps its
// element for as long as its request is behind the card, so a click isn't lost to a redraw and an
// edge can move from where it was. Words go through textContent only (dom.ts ``el``).

import { foldLine, type DeckView, type Edge } from "./deck";
import { el, icon } from "./dom";
import type { Row } from "./presenter";
import { edgeContent, edgeTimes, type EdgeView } from "./views";

export type DeckHost = {
  list: HTMLElement;
  // What a row is doing, in words.
  label: (r: Row) => string;
  focus: (runId: string) => void;
  watch: (r: Row) => void;
  // The folded edge was clicked: the long answer closes, and the deck opens again.
  unfold: () => void;
};

const ENDED: ReadonlySet<string> = new Set(["result", "error", "done"]);
const FOLD = "fold";

export class DeckDraw {
  private readonly nodes = new Map<string, HTMLElement>();
  private readonly host: DeckHost;

  constructor(host: DeckHost) {
    this.host = host;
  }

  draw(view: DeckView): void {
    const wanted = new Set(view.fold ? [FOLD] : view.edges.map((e) => e.row.runId));
    for (const [id, node] of this.nodes) {
      if (wanted.has(id)) continue;
      node.remove();
      this.nodes.delete(id);
    }
    if (view.fold) {
      const words = foldLine(view.fold);
      const node = this.nodes.get(FOLD) ?? this.create(FOLD, () => this.host.unfold());
      this.place(node, 0, 10, 0, view.height);
      node.classList.toggle("edge--confirm", view.fold.needOk > 0);
      node.title = "Close the answer to see them";
      this.fill(node, words, () => [el("span", { class: "edge-mark" }, icon("expand")), el("span", { class: "edge-title" }, words)]);
    }
    for (const edge of view.edges) {
      const id = edge.row.runId;
      const node = this.nodes.get(id) ?? this.create(id, () => this.host.focus(id));
      this.drawEdge(node, edge);
    }
    this.host.list.hidden = wanted.size === 0;
    edgeTimes(this.host.list);
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
      running: !ENDED.has(r.state), state: r.state, more: edge.more,
    };
    this.place(node, edge.depth, edge.inset, edge.offset, edge.peek);
    node.className = `edge edge--${r.state}`;
    node.title = `${v.words}\nClick to bring it forward`;
    node.setAttribute("aria-label", `${v.title}: ${v.label}`);
    this.fill(node, JSON.stringify(v), () => edgeContent(v, () => this.host.watch(r)));
  }
}
