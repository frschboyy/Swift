// B4: a worker's diagram drawn by Mermaid, the vetted set's one dependency (@mermaid-js/tiny 12.3.0, pinned).
// The source is untrusted: swift/shapes.py refused clicks, links, directives, styles and markup before it got
// here, and this draws it in strict mode with text labels, then admits only an SVG that can't run or fetch.
// Imported lazily (blocks.ts), so the 2.8 MB file loads only when the first diagram is shown.

import TINY from "@mermaid-js/tiny/dist/mermaid.tiny.js?url";

type Mermaid = {
  initialize(config: object): void;
  parse(text: string): Promise<unknown>;
  render(id: string, text: string): Promise<{ svg: string }>;
};

let loaded: Promise<Mermaid> | null = null;
let n = 0;

// The tiny build is a classic script that sets globalThis.mermaid (as a module its top-level var stays local and
// it throws), so the bundler copies it as a file of Swift's own and it loads by a script tag: 'self' in the CSP.
function load(): Promise<Mermaid> {
  return (loaded ??= new Promise<Mermaid>((resolve, reject) => {
    const s = document.createElement("script");
    s.src = TINY;
    s.onload = () => resolve((globalThis as unknown as { mermaid: Mermaid }).mermaid);
    s.onerror = () => { loaded = null; reject(new Error("mermaid didn't load")); };
    document.head.append(s);
  }));
}

/** Whether Mermaid's SVG only draws: no script, no foreign HTML, no handlers, no link or image that leaves it. */
export function inert(root: Element): boolean {
  if (root.localName !== "svg" || root.querySelector("parsererror, script, foreignObject, image, a, iframe, object, embed")) return false;
  for (const node of [root, ...root.querySelectorAll("*")]) {
    for (const { name, value } of [...node.attributes]) {
      if (/^on/i.test(name)) return false;
      if (/(^|:)href$/i.test(name) && !value.startsWith("#")) return false;
      if (/url\(\s*['"]?(?!#)/i.test(value)) return false;
    }
  }
  // Mermaid's own <style>: its colours, and url() only for its own markers.
  return ![...root.querySelectorAll("style")].some((s) => /@import|url\(\s*['"]?(?!#)/i.test(s.textContent ?? ""));
}

/** The diagram as an SVG element in Swift's colours, or null when it doesn't parse or doesn't pass ``inert``. */
export async function draw(source: string, stage: Element): Promise<SVGSVGElement | null> {
  const id = `swift-diagram-${++n}`;
  try {
    const mermaid = await load();
    const v = (name: string, or = ""): string => getComputedStyle(stage).getPropertyValue(name).trim() || or;
    const panel = v("--panel-solid", "#1f2127");
    // shortcut: the colours are read once per drawing, so a diagram drawn before a theme change keeps the old
    // ones until it's drawn again; redraw on the theme event if the owner notices.
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",  // labels are text; clicks and links off
      htmlLabels: false,
      flowchart: { htmlLabels: false },
      maxTextSize: 4000,
      maxEdges: 100,
      theme: "base",
      fontFamily: "system-ui, sans-serif",
      // The worker's drawing in neutral colours: Swift's accent and its state colours are never the worker's.
      themeVariables: {
        background: panel, primaryColor: v("--edge-1", panel), primaryTextColor: v("--text"), primaryBorderColor: v("--muted"),
        lineColor: v("--faint"), textColor: v("--text"), secondaryColor: panel, tertiaryColor: panel, fontSize: "13px",
      },
    });
    await mermaid.parse(source);
    const { svg } = await mermaid.render(id, source);
    // Mermaid's output, through its own DOMPurify; parsed as SVG, never as HTML, then checked again here.
    const root = new DOMParser().parseFromString(svg, "image/svg+xml").documentElement;
    return inert(root) ? (document.importNode(root, true) as unknown as SVGSVGElement) : null;
  } catch {
    return null;
  } finally {
    document.getElementById(`d${id}`)?.remove();  // what Mermaid leaves in the page when a render fails
  }
}
