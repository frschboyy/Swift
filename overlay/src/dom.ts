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
  wifi: "M4.9 9.9a10 10 0 0114.2 0M7.8 12.8a6 6 0 018.4 0M10.6 15.6a2 2 0 012.8 0M12 19v.01",
  copy: "M9 9h10v10H9zM5 15V5h10",
  collapse: "M6 15l6-6 6 6",
  expand: "M6 9l6 6 6-6",
  grip: "M9 6v.01M15 6v.01M9 12v.01M15 12v.01M9 18v.01M15 18v.01",
  mic: "M12 3a3 3 0 00-3 3v6a3 3 0 006 0V6a3 3 0 00-3-3zM5 11a7 7 0 0014 0M12 18v3",
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
