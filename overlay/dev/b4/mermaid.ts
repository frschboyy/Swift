// B4 check: Mermaid (the vetted set's one new dependency) drawing a worker's diagram on a Halo card, offline.
// The file isn't in git (overlay/dev/b4/vendor/ is ignored): `npm pack @mermaid-js/tiny@12.3.0`, then copy
// its dist/mermaid.tiny.js into vendor/. A real build would import it lazily from node_modules instead.

type Mermaid = {
  initialize(config: object): void;
  parse(text: string): Promise<unknown>;
  render(id: string, text: string): Promise<{ svg: string }>;
};

let loaded: Promise<Mermaid> | null = null;

function load(): Promise<Mermaid> {
  return (loaded ??= new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "/dev/b4/vendor/mermaid.tiny.js";
    s.onload = () => resolve((globalThis as unknown as { mermaid: Mermaid }).mermaid);
    s.onerror = () => reject(new Error("mermaid.tiny.js isn't in overlay/dev/b4/vendor/"));
    document.head.append(s);
  }));
}

/** The diagram as SVG, or null when the source doesn't parse (the card then shows words). */
export async function drawMermaid(source: string, stage: HTMLElement, n: number): Promise<Element | null> {
  const mermaid = await load();
  const v = (name: string): string => getComputedStyle(stage).getPropertyValue(name).trim();
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "strict",  // labels are text; click handlers and links off
    htmlLabels: false,
    flowchart: { htmlLabels: false },
    theme: "base",
    fontFamily: "system-ui, sans-serif",
    themeVariables: {
      background: v("--panel-solid"), primaryColor: v("--edge-1"), primaryTextColor: v("--text"),
      primaryBorderColor: v("--accent"), lineColor: v("--muted"), textColor: v("--text"),
      secondaryColor: v("--edge-1"), tertiaryColor: v("--panel-solid"), fontSize: "13px",
    },
  });
  try {
    await mermaid.parse(source);
    const { svg } = await mermaid.render(`b4m${n}`, source);
    // Mermaid's own output, already through its DOMPurify; parsed as SVG, never as HTML.
    const doc = new DOMParser().parseFromString(svg, "image/svg+xml");
    const root = doc.documentElement;
    if (root.querySelector("parsererror, script, foreignObject")) return null;
    root.classList.add("b4-mermaid");
    return document.importNode(root, true);
  } catch {
    return null;
  }
}
