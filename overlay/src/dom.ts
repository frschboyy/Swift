// Minimal DOM builder. Text always goes through textContent, never innerHTML:
// transcripts and agent output are untrusted.

type Child = Node | string | null | undefined | false;

export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Record<string, string | boolean | ((ev: Event) => void)> = {},
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (typeof value === "function") node.addEventListener(key.replace(/^on/, ""), value);
    else if (value === true) node.setAttribute(key, "");
    else if (value !== false) node.setAttribute(key, value);
  }
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    node.append(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

/** Inline SVG icons (stroke = currentColor). */
const ICONS: Record<string, string> = {
  check: "M5 12.5l4.2 4.2L19 7",
  x: "M6 6l12 12M18 6L6 18",
  alert: "M12 8v5M12 16.5v.5M10.3 3.9L2.6 17.5A2 2 0 004.3 20.5h15.4a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z",
  info: "M12 11v6M12 7.5v.5M12 21a9 9 0 100-18 9 9 0 000 18z",
  shield: "M12 3l7 3v5.5c0 4.4-3 8-7 9.5-4-1.5-7-5.1-7-9.5V6l7-3z",
  stop: "M7 7h10v10H7z",
  edit: "M4 20h4L19 9l-4-4L4 16v4zM13.5 6.5l4 4",
  wifi: "M4.9 9.9a10 10 0 0114.2 0M7.8 12.8a6 6 0 018.4 0M10.6 15.6a2 2 0 012.8 0M12 19v.01",
  copy: "M9 9h10v10H9zM5 15V5h10",
  collapse: "M6 15l6-6 6 6",
  expand: "M6 9l6 6 6-6",
  grip: "M9 6v.01M15 6v.01M9 12v.01M15 12v.01M9 18v.01M15 18v.01",
  mic: "M12 3a3 3 0 00-3 3v6a3 3 0 006 0V6a3 3 0 00-3-3zM5 11a7 7 0 0014 0M12 18v3",
  // The Capsule redesign (ADR-017): 24-unit, 2 px round strokes.
  keyboard: "M3 6h18v12H3zM7 10h.01M11 10h.01M15 10h.01M7 14h10",
  bell: "M6 16v-5a6 6 0 0112 0v5l2 2H4l2-2zM10 21a2 2 0 004 0",
  timer: "M12 21a8 8 0 100-16 8 8 0 000 16zM12 9v4l3 2M10 2h4",
  pause: "M9 6v12M15 6v12",
  lock: "M6 11h12v9H6zM8.5 11V8a3.5 3.5 0 017 0v3",
  question: "M12 21a9 9 0 100-18 9 9 0 000 18zM9.6 9.6a2.5 2.5 0 114.1 1.9c-.9.7-1.7 1.2-1.7 2.5M12 17v.01",
  play: "M8 5l11 7-11 7z",
  external: "M14 4h6v6M20 4l-9 9M18 14v5H5V6h5",
  settings: "M12 15a3 3 0 100-6 3 3 0 000 6zM19.4 13a7.5 7.5 0 000-2l2-1.5-2-3.4-2.4 1a7.5 7.5 0 00-1.7-1L15 3h-4l-.3 2.6a7.5 7.5 0 00-1.7 1l-2.4-1-2 3.4L6.6 11a7.5 7.5 0 000 2l-2 1.5 2 3.4 2.4-1a7.5 7.5 0 001.7 1L11 21h4l.3-2.6a7.5 7.5 0 001.7-1l2.4 1 2 3.4z",
  power: "M12 3v8M6.3 6.3a8 8 0 1011.4 0",
  restart: "M20 11a8 8 0 10-2.3 5.7M20 4v7h-7",
  slash: "M5 5l14 14",
  // Saved recordings (audit B-06): clear them, improve speech recognition from them.
  trash: "M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3",
  wave: "M3 12h2M7 8v8M11 5v14M15 9v6M19 11v2",
};

export function icon(name: keyof typeof ICONS | string): SVGSVGElement {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.classList.add("icon");
  const path = document.createElementNS(ns, "path");
  path.setAttribute("d", ICONS[name] ?? ICONS.alert);
  svg.append(path);
  return svg;
}

/** "ctrl+shift+space" -> ["Ctrl", "Shift", "Space"]. */
export function hotkeyParts(spec: string): string[] {
  const names: Record<string, string> = { ctrl: "Ctrl", control: "Ctrl", alt: "Alt", shift: "Shift", super: "Win", meta: "Win", cmd: "Win", esc: "Esc" };
  return spec
    .split("+")
    .map((p) => p.trim())
    .filter(Boolean)
    .map((p) => names[p.toLowerCase()] ?? p.charAt(0).toUpperCase() + p.slice(1));
}

/** A hotkey as keycaps: Ctrl + Shift + Space. */
export function keys(spec: string): HTMLElement {
  const out = el("span", { class: "keys" });
  hotkeyParts(spec).forEach((part, i) => {
    if (i) out.append("+");
    out.append(el("kbd", {}, part));
  });
  return out;
}

/** Text with `code` spans (hints name commands like `claude`). */
export function rich(text: string): DocumentFragment {
  const out = document.createDocumentFragment();
  text.split(/(`[^`]+`)/).forEach((part) => {
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) out.append(el("code", {}, part.slice(1, -1)));
    else if (part) out.append(part);
  });
  return out;
}

/** Text with every mention of `spec` (as written, or formatted) shown as keycaps. */
export function withKeys(text: string, spec: string): DocumentFragment {
  const out = document.createDocumentFragment();
  const variants = [spec, hotkeyParts(spec).join("+")].filter(Boolean);
  const hit = variants.map((v) => ({ v, i: text.indexOf(v) })).find((m) => m.i >= 0);
  if (!hit) {
    out.append(rich(text));
    return out;
  }
  out.append(rich(text.slice(0, hit.i)), keys(spec), rich(text.slice(hit.i + hit.v.length)));
  return out;
}
