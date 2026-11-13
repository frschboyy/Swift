# B4: results shaped to fit them (proposal, 2026-11-13)

Status: **proposal, for the owner.** Nothing here is built into Swift. A dev-only prototype draws two shapes
(`overlay/dev/b4.html`, below).

**The owner's decision (2026-11-13):** results aren't a fixed list of layouts. For each result, Swift works out
how best to show it, visually and in words: a table, a side-by-side comparison, project cards, a real diagram, a
document preview, a chart, or plain text. The card's look follows. Swift may use free tools to make that work.

**In one paragraph:** the worker sends Swift a *typed result*, a shape plus its data, through a tool Swift
gives it, never as markup. Swift's backend checks it, may change the shape or the size it's shown at, and adds who
made it. The overlay draws it with Halo blocks that only Swift's own code draws. When anything doesn't fit, the
card shows plain text. Swift says a sentence or two aloud and the card shows the rest. The free tools are
renderers that ship with Swift, pinned and offline, and the owner approves the list once. Installing on demand,
with a card each time as C4 says, is for the worker's own tools, never for what draws the overlay.

## 1. What's there today

- The agent's final text goes through `split_answer` (`executors/claude_mapping.py:296`). The opening lines become
  the summary and the rest becomes `details`, as `text` or `list`. `table` exists in the protocol
  (`overlay/src/protocol.ts:27`), but only Swift's own tools, like the calendar, produce it. Nothing the agent
  writes reaches it, and the table hides its column headings (`styles.css:468`), so it can't hold a comparison.
- `speech.spoken()` says the summary, at most two sentences. The card shows the summary and the details.
- Halo's principle 3 (`SPEC.md` §1): **"Workers never draw. A worker returns data; Swift picks a block from its
  own catalog."** B4 keeps this. It's what makes B4 safe, not something in its way.
- The overlay has one runtime dependency (`@tauri-apps/api`). Every word goes through `textContent` (`dom.ts`).

## 2. Where the choice is made: both, with Swift having the last word

| Who | Decides | Why |
|---|---|---|
| **Worker (the agent)** | Which shape the content has, and the data for it | Only the worker knows the content: that three laptops on five measures make a comparison |
| **Swift's backend** | Whether the shape holds up, the size it's shown at (card, expanded card, reader), who it's from | The worker can't be trusted to keep a card small or to say whose words they are |
| **Swift's own tools** (calendar, email, files) | Their shape, as today | They're Swift's: their facts are drawn as Swift's own |

**How the worker says it:** an in-process tool, `show_result`, added beside `request_stronger_model`
(`claude_code.py:491` already builds an SDK MCP server). Its input schema lists the shapes. The SDK checks the
schema, then the backend checks again with pydantic (already a dependency) in a small new module,
`swift/shapes.py`, so the check doesn't grow `session.py`. The tool's description tells the worker when to use
each shape. The prompt keeps "the final answer short": that answer becomes the spoken sentence (§5).
A fenced JSON block in the final text was considered as the way in. It works for providers without tools, but it
mixes data into prose and fails quietly. Keep it only as the fallback for a second provider.

**What the backend does with it:**
1. **Check** every field: lengths, counts (a comparison has 2–4 items and up to 12 rows; a diagram up to 16 nodes),
   references (an edge to a node that doesn't exist), and no markup anywhere. Anything that fails becomes plain
   text from the worker's answer. Nothing is lost and nothing crashes.
2. **Size:** a shape that's too big for the card opens as the expanded card. That's B5's "grows when the content
   needs it", decided by Swift from the data, not by the worker.
3. **Mark who made it:** `by: "worker"` and the worker's name, set by the backend, never read from the worker.
4. **Never on an approval:** shapes appear only on Done results and in the reader. Needs your OK, Waiting for
   you and the facts box keep drawing from the action (principle 2, X-17). A shape can't hold a button, a link
   that does something, or an image from a URL.

**Reaching the overlay:** `ResultDetails` (`protocol.ts:27`) gets new kinds next to `text`, `list` and `table`:

```ts
| { kind: "compare"; items: string[]; rows: { label: string; values: string[] }[]; pick?: number; by: By }
| { kind: "diagram"; source: string; by: By }                    // Mermaid text, checked (§4)
| { kind: "chart"; type: "bar" | "line"; x: string[]; series: { name: string; values: number[] }[]; unit?: string; by: By }
| { kind: "cards"; cards: { title: string; detail?: string; meta?: string }[]; by: By }   // project cards
| { kind: "preview"; path: string; thumb: string; excerpt?: string; by: By }  // thumb: a PNG made by Swift
| { kind: "table"; columns: string[]; rows: string[][]; headed?: boolean; by?: By }       // headed: show headings
type By = { who: "swift" } | { who: "worker"; name: string };
```

**X-17 on result cards:** the byline ("Swift · via Claude") already names the worker. A worker's *judgment* inside
a shape needs its own mark too: the comparison's highlighted column, or a chart's "best". Swift's accent can't
present it as Swift's own advice. **Recommendation:** label it "Claude's pick", never "Best fit". The prototype
still says "Best fit"; that's the change to make.

## 3. The renderer: Halo Step B, and what changes in it

Step B (brief-halo.md) builds one card renderer: state line, origin line, blocks, footer. B4 needs three things
from it, and none of them adds a feature to Step B itself:

1. **Blocks are a table from kind to drawing function,** each taking typed data:
   `kind → { draw(data, size), text(data), fits(data, size) }`. `text()` gives the same content as words, for Copy,
   a screen reader and the fallback. `fits()` tells Swift whether the data fits a card or needs the expanded card.
   Step B fills the table with today's blocks; B4 then adds rows to it without touching the renderer.
2. **One block, two sizes:** the same `draw` serves the card and the expanded card/reader (`SPEC.md` §7: "one run,
   five sizes"). Today's `renderDetails(details, full)` already works this way for six rows against all rows.
3. **Heavy renderers load when needed:** `await import()`, as `look/index.ts` already loads `halo.css`. A Mermaid
   diagram costs nothing until the first diagram.

**Step B's own rule changes in one place.** `SPEC.md` §5 says "add a block only when two capabilities need it". With
the owner's decision it reads: **add a shape when Swift's own code can draw it from typed data and check that
data.** The worker can't add a shape while Swift runs; a new shape is a code change, reviewed like any other.
New blocks: **Compare, Diagram, Chart, Cards, Preview,** and Table gains headings.

**Order:** Step B first, with no protocol change, as its brief says. Then B4 adds one shape at a time, each with its
seam scenario (`tests/unit/test_seam_replay.py`) and owner checks:
1. **Compare** and headed tables. No dependency. The most common case in the owner's run (238).
2. **Diagram** through Mermaid. The one new dependency, after the owner's OK.
3. **Preview** through Windows' own thumbnails. No new dependency.
4. **Chart** and **Cards**, drawn by Swift's own code.

## 4. Free tools: which shapes, licences, sizes

Sizes are npm's *unpacked* package sizes (`npm view <pkg> dist.unpackedSize`, 2026-11-13). The shipped,
minified bundle is much smaller; measure it with `vite build` before the owner approves the list. Everything below
runs inside the overlay's WebView2 or through Windows itself. **All of them run offline. Nothing sends audio or
content off the PC.**

| Shape | Tool | Licence | Size (unpacked) | Offline | New dependency? | Verdict |
|---|---|---|---|---|---|---|
| Table, compare, list, cards | Swift's own code (prototype: ~70 lines) | — | — | yes | no | **Ship** |
| Simple charts (bar, line, ≤4 series) | Swift's own SVG code (as the diagram prototype) | — | — | yes | no | **Ship** |
| Diagrams (flow, sequence, state, timeline, gantt, mind map, ER) | Mermaid, `@mermaid-js/tiny` 12.3 | MIT | 2.9 MB (full `mermaid`: 124 MB, every build) | yes | **yes** | **Ship, if the owner approves** |
| Graph layout only | `@dagrejs/dagre` 3.1 | MIT | 1.4 MB | yes | yes | Fallback if Mermaid is refused: fixes the crossing in the prototype, but flows only |
| Document preview (PDF, Word, PowerPoint, images) | Windows Shell thumbnails (`IShellItemImageFactory`) through `comtypes`/`pywin32` | Windows / MIT, PSF | 0 | yes | **no** (both already in `pyproject.toml`) | **Ship.** Unproven on the PC: needs a spike |
| Word excerpt | Word through COM (ADR-012, already used) | — | 0 | yes | no | Ship |
| Dense time series | uPlot 1.6 | MIT | 0.5 MB | yes | yes | Not now: own SVG covers the need |
| Charts, general | Chart.js 4.6 | MIT | 6.2 MB | yes | yes | Rejected: canvas (no text for screen readers), bigger than needed |
| Charts, grammar | Vega-Lite 6.5 + vega-embed | BSD-3 | 5.9 + 0.6 MB (+ vega) | yes | yes | Rejected: a second spec language for the worker |
| Charts, all-in-one | ECharts 6.1 | Apache-2.0 | 60 MB | yes | yes | Rejected: size |
| Graphviz | `@viz-js/viz` 3.31 (WASM) | MIT | 5.0 MB | yes | yes | Rejected: Mermaid covers it |
| Graph layout | elkjs 0.12 | EPL-2.0 or GPL-3.0+ | 8.2 MB | yes | yes | Rejected: licence |
| PDF pages | pdf.js (`pdfjs-dist` 6.5) | Apache-2.0 | 37.6 MB | yes | yes | Rejected: a thumbnail and an "Open" covers a card |
| .docx to HTML | mammoth 1.13 / docx-preview 0.4 | BSD-2 / Apache-2.0 | 1.7 / 1.0 MB | yes | yes | Rejected: produces markup the overlay would have to trust |
| Math | KaTeX 0.19 | MIT | 4.0 MB | yes | yes | Not now: no request for it yet |

**Mermaid, in detail:** Claude writes Mermaid fluently, and one dependency covers almost every diagram the owner
listed. Mermaid's input is the worker's text, so it gets the same care as any worker input:
- `mermaid.parse()` first: a diagram that doesn't parse becomes text.
- `securityLevel: "strict"` and `htmlLabels: false`: labels are text, scripts and clicks are off. Mermaid sanitises
  its SVG with DOMPurify, bundled inside it.
- The SVG goes into a sandboxed shadow root, with no `foreignObject` and no external `href`.
- Halo's tokens are passed as Mermaid's `themeVariables`, so it matches dark and light.
- There's a size cap: source over a few kB, or more than about 40 nodes, opens in the reader or becomes text.

Mermaid has had XSS advisories in earlier versions. That's the reason for pinning, strict mode and the review that
comes with every version bump (`uv`/`npm` lockfiles already pin).

**Ship a vetted set, or install when needed? Recommendation: ship the set, and the owner approves it once.**
- What draws the overlay runs in the same page that draws Needs your OK. Code downloaded while Swift runs would
  sit next to the approval button. Product rules and X-17 depend on that page running only reviewed code.
- Shipped renderers work offline, cost nothing until used (lazy import), and go through the same tests, seam
  replay and licence check as the rest of Swift.
- "Install when needed, asking on a card each time" (C4) stays for the **worker's** tools: a Python package to
  read a spreadsheet, a converter for an odd file type. Those run in the worker's sandbox and never in the overlay.
  The C4 card says what will be installed, from where, why and its licence.
- The list Swift ships and its versions go in an ADR, so adding a renderer later is an owner decision and not a
  surprise.

## 5. Words and visuals: what's said and what's shown

| Said aloud | Shown |
|---|---|
| The conclusion, in one or two sentences: "The Zenbook fits travel best: lightest, longest battery, mid-priced." | The evidence: the comparison table |
| What the diagram means: "Your request goes through Swift, then a worker, and anything that changes something asks you first." | The diagram |
| For a document: what it is and the one thing that matters | The thumbnail, the excerpt, and Open |
| Never: cell values read row by row, node lists, file paths, numbers no one asked for | — |

The rules:
- **The spoken sentence stands alone.** It's the worker's final answer, kept short by the prompt and capped by
  `speech.spoken()` as today. The `show_result` tool's description tells the worker to keep data out of it.
- **A shape is never spoken.** Its title and caption are for the eye. `spoken()` already drops headings and code.
- **When the owner can't see the card** (a hands-free answer while the card is folded or behind another), add one
  of Swift's own short phrases, "It's on screen", and never read the shape instead.
- **Every shape has its text:** the block's `text()` gives the table as rows, the diagram as "A → B" lines, and the
  chart as its values. Copy, screen readers and the fallback use it.

## 6. The prototype

`overlay/dev/b4.html` with `overlay/dev/b4/shapes.ts` (dev only, nothing in `src/` imports it). It draws a Done
card in Halo with the spoken sentence and a shape, from sample typed results that go through `parseShape`, the
boundary check. Run it with the dev harness's Vite on port 1431:
`/dev/b4.html?shape=compare|diagram|bad&theme=light`. Tests are in `overlay/tests/b4-shapes.test.ts`: malformed
shapes, including markup, fall back to text, and layers stop on a cycle.

| Comparison, dark | Comparison, light | Diagram, dark |
|---|---|---|
| ![](b4/compare-dark.jpg) | ![](b4/compare-light.jpg) | ![](b4/diagram-dark.jpg) |

**What it showed:**
- **The comparison works with no dependency.** Headings, row labels, a highlighted column and tabular numbers fit a
  512 px card at 3 × 5. Four items is the most a card holds; more opens the expanded card.
- **A hand-made diagram layout breaks at seven nodes.** In the screenshot, the edge from "Swift's own tool" to
  "Result card" runs through "Needs your OK". A real layout needs dummy nodes and crossing reduction, which is
  exactly what Mermaid (or dagre) already does. This is the clear need for the one new dependency.
- **The fallback holds:** `?shape=bad` (an edge to a missing node) shows the worker's words, not a broken drawing.
- The "Best fit" tag in Swift's accent reads like Swift's own advice. Rename it "Claude's pick" (§2).

Not checked: the real overlay (`main.ts` isn't touched, to keep clear of B1 and the screen-snapshot work), 150%
scaling, forced colours, reduced motion, and the Windows thumbnail call.

## 7. Decisions for the owner

1. **Who chooses the shape:** the worker proposes it through a `show_result` tool, and Swift checks it, sizes it
   and marks it. *Recommended.* Alternative: Swift guesses the shape from the worker's text, which is weaker and
   guesses wrong on prose.
2. **Ship or install:** ship a vetted set of renderers and approve the list once. *Recommended.* Installing on
   demand (C4, a card each time) stays for the worker's own tools only.
3. **The list:** Mermaid (`@mermaid-js/tiny`, MIT) as the one new overlay dependency, for diagrams. Swift's own code
   for tables, comparisons, cards and simple charts. Windows thumbnails for document previews, with no new
   dependency. *Recommended.* Without Mermaid, dagre does flow diagrams only.
4. **The worker's judgment is labelled as the worker's** ("Claude's pick"), never in Swift's voice. *Recommended.*
5. **Order:** Halo Step B first, built as a table of typed blocks with no protocol change. Then the shapes one at a
   time: compare, diagram, preview, chart and cards. *Recommended.* B4 can't land before Step B without drawing
   everything twice.
6. **Shapes only on Done results and the reader,** never on Needs your OK or Waiting for you. *Recommended*; it
   follows from the product rules.

## 8. When it's built

- Each shape: a seam scenario that fails with it undone, owner checks numbered from "Next free check number", their
  ledger lines, and report lines.
- Routing parity unchanged: the routing doesn't move.
- A spike before Preview: Windows thumbnails for a PDF, a .docx and a .pptx on the owner's PC.
- An ADR for the shipped renderer list and the `show_result` contract.
