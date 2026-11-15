# B4: results shaped to fit them (proposal, 2026-11-13)

Status: **the owner approved the vetted set on 2026-11-14** (§4): Swift's own code for text, tables, comparisons,
simple charts and mind maps; Mermaid's tiny build for diagrams; and Windows' PDF renderer plus a text excerpt for
documents. The checks before approval (§9) replaced Windows Shell thumbnails, which gave a thumbnail for only 2 of
24 real files. The owner also asked for a mind-map shape (§6) and, later, a brainstorm map that grows by voice
(§10). The first slice, `show_result` and the compare shape, is merged (§8, 2026-11-15); the second, diagram and
mind map, is built on a branch (§8); preview, chart and cards are not. A dev-only prototype draws the shapes (`overlay/dev/b4.html`, §6).

**The owner's decision (2026-11-13):** results aren't a fixed list of layouts. For each result, Swift works out
how best to show it, visually and in words: a table, a side-by-side comparison, project cards, a real diagram, a
document preview, a chart, or plain text. The card's look follows. Swift may use free tools to make that work.

**In one paragraph:** the worker sends Swift a *typed result*, a shape plus its data, through a tool Swift
gives it, never as markup. Swift's backend checks it, may change the shape or the size it's shown at, and adds who
made it. The overlay draws it with Halo blocks that only Swift's own code draws. When anything doesn't fit, the
card shows plain text. Swift says a sentence or two aloud and the card shows the rest. The owner decided the tools question (2026-11-13): a vetted set of free
tools ships with Swift and the owner approves the list once. Anything else is installed only when needed, with a
card every time (C4). It runs on the worker's side, and its output reaches the card as data, never as code in the
overlay. §4 has the recommended set and how an install is asked for and kept.

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

**X-17 on result cards:** a worker's *judgment* inside a shape needs its own mark: the comparison's highlighted
column, or a chart's "best". Swift's accent can't present it as Swift's own advice, and the label never names the
provider (`CLAUDE.md`: "Swift speaks as itself"). **Decided (2026-11-15):** "Worker's pick", in grey under the
worker's bar, never "Best fit" and never "Claude's pick". The prototype still says "Best fit"; Swift's block doesn't.

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
New blocks: **Compare, Diagram, Mind map, Chart, Cards, Preview,** and Table gains headings.

**Order:** Step B first, with no protocol change, as its brief says. Then B4 adds one shape at a time, each with its
seam scenario (`tests/unit/test_seam_replay.py`) and owner checks:
1. **Compare** and headed tables. No dependency. The most common case in the owner's run (238).
2. **Diagram** through Mermaid, the one new dependency (approved 2026-11-14), and **Mind map**, drawn by Swift's own
   code (§6).
3. **Preview**: Windows' own PDF renderer and a text excerpt (§9). No new dependency.
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
| Diagrams (flow, sequence, state, class, ER, timeline, gantt, quadrant, journey) | Mermaid, `@mermaid-js/tiny` 12.3 | MIT | 2.85 MB, one minified file; 0.76 MB gzipped (measured, §9) | yes | **yes** | **Ship** |
| Diagrams, full build | `mermaid` 12.3 | MIT, but it bundles elkjs (EPL-2.0/GPL) and KaTeX | 5.4 MB in 105 lazy chunks (1.6 MB gzipped) | yes | yes | Rejected: the ELK licence; tiny covers the need |
| Graph layout only | `@dagrejs/dagre` 3.1 | MIT | 1.4 MB | yes | yes | Fallback if Mermaid is refused: fixes the crossing in the prototype, but flows only |
| PDF preview (first page as PNG) | Windows' own renderer, `Windows.Data.Pdf` (Windows 10+) | Windows | 0 | yes | **no** | **Ship.** 6 of 6 PDFs rendered (§9) |
| Office preview (Word, PowerPoint, Excel) | A text excerpt from the file's XML, Python standard library (`zipfile`) | Python's | ~30 lines | yes | **no** | **Ship.** 14 of 14 real files, ≤62 ms (§9) |
| Document thumbnails | Windows Shell thumbnails (`IShellItemImageFactory`), through `comtypes` | Windows / MIT | 0 | yes | no | **Rejected after the spike:** 2 of 24 real files, failures took up to 9 s |
| Word excerpt | Word through COM (ADR-012, already used) | — | 0 | yes | no | Not needed: the standard-library excerpt doesn't open Word |
| Dense time series | uPlot 1.6 | MIT | 0.5 MB | yes | yes | Not now: own SVG covers the need |
| Charts, general | Chart.js 4.6 | MIT | 6.2 MB | yes | yes | Rejected: canvas (no text for screen readers), bigger than needed |
| Charts, grammar | Vega-Lite 6.5 + vega-embed | BSD-3 | 5.9 + 0.6 MB (+ vega) | yes | yes | Rejected: a second spec language for the worker |
| Charts, all-in-one | ECharts 6.1 | Apache-2.0 | 60 MB | yes | yes | Rejected: size |
| Graphviz | `@viz-js/viz` 3.31 (WASM) | MIT | 5.0 MB | yes | yes | Rejected: Mermaid covers it |
| Graph layout | elkjs 0.12 | EPL-2.0 or GPL-3.0+ | 8.2 MB | yes | yes | Rejected: licence |
| PDF pages | pdf.js (`pdfjs-dist` 6.5) | Apache-2.0 | 37.6 MB | yes | yes | Rejected: Windows renders PDF pages already |
| .docx to HTML | mammoth 1.13 / docx-preview 0.4 | BSD-2 / Apache-2.0 | 1.7 / 1.0 MB | yes | yes | Rejected: produces markup the overlay would have to trust |
| Math | KaTeX 0.19 | MIT | 4.0 MB | yes | yes | Not now: no request for it yet |

**Mermaid, in detail:** Claude writes Mermaid fluently, and one dependency covers almost every diagram the owner
listed. Mermaid's input is the worker's text, so it gets the same care as any worker input:
- `mermaid.parse()` first: a diagram that doesn't parse becomes text.
- `securityLevel: "strict"` and `htmlLabels: false`: labels are text, scripts and clicks are off. Mermaid sanitises
  its SVG with DOMPurify, bundled inside it.
- The SVG is parsed as SVG, never as HTML, and refused if it holds a `script` or `foreignObject` (the prototype
  does this, `overlay/dev/b4/mermaid.ts`).
- Mermaid is loaded only when the first diagram arrives, or while Swift is idle after start-up: cold, it takes
  0.8 s to load and parse once (§9).
- Halo's tokens are passed as Mermaid's `themeVariables`, so it matches dark and light.
- There's a size cap: source over a few kB, or more than about 40 nodes, opens in the reader or becomes text.

Mermaid has had XSS advisories in earlier versions. That's the reason for pinning, strict mode and the review that
comes with every version bump (`uv`/`npm` lockfiles already pin).

### The owner's decision (2026-11-13): a vetted set, and installs outside it ask

A vetted set of free tools ships with Swift, and the owner approves that list once. Anything outside the set is
installed only when needed, and Swift asks on a card every time (C4).

### The vetted set (approved by the owner on 2026-11-14)

| # | Tool | Covers | Licence | Size | Offline | New dependency |
|---|---|---|---|---|---|---|
| 1 | **Swift's own blocks** (overlay TypeScript) | Text, list, headed table, comparison, mind map (≤3 levels, ≤30 ideas), project cards, simple bar and line charts (≤4 series, SVG) | Swift's | ~70 lines per shape (prototype) | yes | no |
| 2 | **Mermaid**, `@mermaid-js/tiny` 12.3.0, pinned | Diagrams: flow, sequence, state, class, ER, timeline, gantt, quadrant, journey. Mind maps are drawn by row 1; tiny leaves out mind maps and architecture diagrams | MIT | 2.85 MB minified, one file, 0.76 MB gzipped (measured) | yes: no network calls in the file, and only localhost requests when rendering (§9) | **yes**, the only one |
| 3 | **`Windows.Data.Pdf`**, Windows' own PDF renderer | A PDF's first page as a PNG on a Preview block, plus its page count | Windows | 0 | yes | no |
| 4 | **A text excerpt from Office files**, Python standard library (`zipfile` + the file's XML) | The opening words of a Word document, the first slide of a PowerPoint, an Excel file's text | Python's | ~30 lines (spike) | yes | no |
| + | Windows Shell thumbnails, opportunistically | A PowerPoint's own embedded preview picture, *when the file has one*; never asked for a PDF | Windows; `comtypes` MIT | 0 | yes | no. Optional: 2 of 6 PowerPoints had one, and a failure can take seconds, so only with a short timeout |

That's the whole set: **one new dependency.** Everything in it draws in the overlay or in Swift's backend, runs
offline, sends nothing off the PC, and loads only when a result needs it (lazy import). The list, versions and
licences go in an ADR, and the overlay's licence check covers them. A version bump is a code change, reviewed with
Mermaid's advisories in mind (strict mode, §4 above), not an install.

Kept out of the set, and why (the full table above): ECharts (60 MB), Vega-Lite (a second spec language), Chart.js
(canvas, no text for screen readers), Graphviz WASM and dagre (Mermaid covers them), elkjs (EPL/GPL licence),
pdf.js (Windows renders PDFs already) and mammoth (its HTML would have to be trusted), the full Mermaid build
(it bundles elkjs), and KaTeX (no request yet). A page *image* of a Word or PowerPoint file is left out too: it
needs Office to export it, which is slow and opens the owner's apps. If the owner wants it, it's a later step
behind "Show me", not on the card. Each can still come in later through the install path below, or by the owner adding it to the set.

### An install outside the set

**Where it runs.** An installed tool runs on the worker's side, never in the overlay page. The overlay draws Needs
your OK, so it only ever runs reviewed, shipped code. An outside tool's output reaches the card as data, or as a
PNG through the Preview block, so Swift still draws everything (principle 3). For example, a chart library the set
lacks makes a PNG, and Swift shows that PNG as a Preview. It never adds a script to the overlay. Installs go into a
folder Swift owns (`%LOCALAPPDATA%\Swift\tools\<name>\`, a `uv` venv for Python or a local `npm` prefix for Node),
never a global install and never the PATH. Removing one deletes that folder.

**How it's asked: a Needs your OK card, every time.**
- **The worker asks** through a `request_tool` tool, giving the package, the ecosystem (pip or npm) and a reason in
  a few words. Swift never installs anything from a worker's shell command: the command card refuses
  `pip install`, `npm i`, `winget` and the like, and points the worker to `request_tool`.
- **Swift looks up the facts itself** from the package index, never from the worker: the name, the exact version,
  the source (PyPI or npm), the licence, the download size, and whether it needs network access when it runs.
  If a fact can't be found, the card says so.
- **The card:** "Install *name* *version* to make the chart you asked for?" The facts box holds the source,
  licence, size, where it goes, and "works offline: yes / no / unknown". The worker's reason is shown as the
  worker's, marked as on X-17. The buttons are **Install** and **Not now**.
- **Product rules hold:** approving hands-free needs Swift's name, and a bare "yes" never installs (this isn't
  the reversible-change exception). Typing never approves. Approve ignores clicks for its first 400 ms. The card
  never times out into a yes.
- **Refused by default, without a card:** licences that aren't OSI-approved, GPL/AGPL code that would ship with
  Swift (a separate tool the worker runs is fine), packages that need a sign-in or an account (sign-in is the
  owner's), and anything that sends audio off the PC.

**How it's kept.** Each approved install writes a record to `%LOCALAPPDATA%\Swift\tools\installed.yaml`: the name,
version, source, licence, hash of what was downloaded, when, the run that asked, and that the owner approved by
voice or by click. This is a content-free record, so it fits the logging rule. The record is how Swift knows what
it has:
- **Using an installed tool again doesn't ask again.** The decision was "asking every time it is installed". An
  upgrade to a new version is a new install and asks. *For the owner to confirm (decision 3b).*
- **The owner can see and remove them:** "what tools have you installed?" reads the record, and "remove *name*"
  deletes the folder and its entry. Deleting asks on a card, as every delete does (ADR-019).
- **Promoting a tool into the vetted set** is the owner's decision and a code change, never automatic. That way the
  set grows only by review.

**Built with C4, not B4.** The install path is C4's work, after the groundwork (the `WorkerTask` grant and run
records). B4 needs only the vetted set, so B4 doesn't wait for C4.

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

| Comparison, dark | Comparison, light | Diagram, hand-made layout |
|---|---|---|
| ![](b4/compare-dark.jpg) | ![](b4/compare-light.jpg) | ![](b4/diagram-dark.jpg) |

| The same diagram, Mermaid | Sequence, Mermaid, light | Labels that try markup, Mermaid |
|---|---|---|
| ![](b4/mermaid-flow-dark.jpg) | ![](b4/mermaid-sequence-light.jpg) | ![](b4/mermaid-markup-dark.jpg) |

| Mind map, dark | Mind map, light |
|---|---|
| ![](b4/mindmap-dark.jpg) | ![](b4/mindmap-light.jpg) |

The mind map is `?shape=mindmap`. The Mermaid cases are `?shape=mermaid|mermaid-seq|mermaid-evil`. They need `mermaid.tiny.js` copied into
`overlay/dev/b4/vendor/`, which git ignores (the steps are in `overlay/dev/b4/mermaid.ts`).

**What it showed:**
- **The comparison works with no dependency.** Headings, row labels, a highlighted column and tabular numbers fit a
  512 px card at 3 × 5. Four items is the most a card holds; more opens the expanded card.
- **A hand-made diagram layout breaks at seven nodes.** In the screenshot, the edge from "Swift's own tool" to
  "Result card" runs through "Needs your OK". A real layout needs dummy nodes and crossing reduction, which is
  exactly what Mermaid (or dagre) already does. This is the clear need for the one new dependency.
- **The fallback holds:** `?shape=bad` (an edge to a missing node) shows the worker's words, not a broken drawing.
- **Mermaid lays the same seven nodes out with no crossing,** in Halo's colours, dark and light.
- The "Best fit" tag in Swift's accent reads like Swift's own advice. Swift's block says "Worker's pick" (§2, §7.4).
- A sequence diagram of six messages is taller than a card: it belongs in the expanded card (`fits()`, §3).
- **The mind map needs no layout library.** A mind map is a tree, so nothing crosses. Swift draws it as nested
  lists (`drawMindMap` in `shapes.ts`, about 15 lines, plus CSS for the lines): the root on the left, the branches
  beside it, each branch's ideas beside that, and a third level indented below. Text wraps, so labels aren't cut.
  Screen readers get nested lists, and `mindMapText()` gives the same map as indented lines for Copy.
- **The mind map's limits:** up to 3 levels under the root and 30 ideas, each label up to 60 characters. Past
  either limit, or with an unnamed idea, the whole map falls back to words (tested). Four branches with 12 ideas
  fill a card (the screenshot). A bigger map opens the expanded card.
- **No state colours on the map:** branches use the accent only. Amber means an OK is waiting and red means failed,
  so neither can colour a branch. The lines use `--accent-edge`, because `--rim-hi` vanished in light mode.

Not checked: the real overlay (`main.ts` isn't touched, to keep clear of B1 and the screen-snapshot work), 150%
scaling, forced colours and reduced motion.

## 7. Decisions for the owner

1. **Who chooses the shape:** **decided by the owner (2026-11-15):** the worker proposes it through a `show_result`
   tool, and Swift checks it, sizes it and marks it. (The alternative, Swift guessing the shape from the worker's
   text, is weaker and guesses wrong on prose.)
2. **Ship or install:** **decided by the owner (2026-11-13).** A vetted set ships and is approved once. Anything
   outside it is installed when needed, with a card every time (§4).
3. **The vetted set:** **approved by the owner on 2026-11-14.** Swift's own blocks; Mermaid (`@mermaid-js/tiny`
   12.3.0, MIT), the one new dependency; Windows' PDF renderer; and a standard-library excerpt for Office files
   (§4). The checks replaced Windows thumbnails with the last two (§9).
   - **3a. Mind maps:** **the owner said yes (2026-11-14).** They're drawn by Swift's own code, with no new
     dependency (§6). The brainstorm map that grows by voice is a separate, later item (§10).
   - **3b.** **Decided (2026-11-15):** an installed tool outside the set is reused without asking again, and a new
     version asks again.
   - **3c.** **Decided (2026-11-15):** outside tools run on the worker's side and reach the card as data or a PNG,
     never as code in the overlay.
4. **The worker's judgment is labelled as the worker's,** never in Swift's voice and **never naming the provider**:
   "Worker's pick". **Decided (2026-11-15).** The earlier "Claude's pick" wording was wrong (`CLAUDE.md`: "Swift
   speaks as itself").
5. **Order:** **decided (2026-11-15):** Halo Step B first (merged 2026-11-14), then the shapes one at a time:
   compare, diagram and mind map, preview, chart and cards.
6. **Shapes only on Done results and the reader,** never on Needs your OK or Waiting for you. **Decided
   (2026-11-15).**

## 8. When it's built

**Slice 1, `show_result` and compare (merged to `main` 2026-11-15):**
- The tool: `show_result` in the executor's in-process `swift` server (`claude_code.py`), always offered. Its schema
  and description, and the check, are `swift/shapes.py` (pydantic, strict, no extra fields): 2–4 items, 1–12 rows,
  one value per item, cells up to 160 characters, a title up to 120, `pick` an item's index; no tags or entities,
  no control or format characters. Anything else is refused whole and the worker is told to answer in words; the
  log gets field roles and error kinds only.
- Sizing and marking are Swift's: `size` is `"expanded"` past six rows (drawn today as an answer that opens with
  Read more, until B5's expanded card) and `by` is always `"worker"`. The answer's words after its summary go
  under the table (`text`), so nothing is lost.
- Done only: the shape is attached in `_final` on a Done outcome; a stop, refusal or failure never carries it. The
  question card draws no details.
- The overlay: `Compare` in `ResultDetails`, drawn by `compareBlock` in `blocks.ts` (the one renderer's block, used
  by the card and the reader), with `detailsText` in `answer.ts` for Copy and the seam. The table sits under the
  worker's bar with "Compared by the worker, not checked by Swift", and its pick is grey, never the accent.
- In the dev harness (`__design("answerCompare")`, `"answerCompareLong"`, default look, headless at 100%):

  | Compare, dark | Compare, light | Seven rows, opened with Read more |
  |---|---|---|
  | ![](b4/slice1-compare-dark.jpg) | ![](b4/slice1-compare-light.jpg) | ![](b4/slice1-compare-long-light.jpg) |
- Not yet: headed tables, a `fits()` per block (the backend's size stands in), the fenced-JSON fallback for a second
  provider, "It's on screen" when the card isn't seen, the ADR for the renderer list.

**Slice 2, diagram and mind map (2026-11-15, branch `claude/b4-diagram-902ffc`):**
- `diagram`: Mermaid source in `show_result`, checked in `swift/shapes.py`. Only the vetted kinds (flowchart/graph,
  sequence, state, class, ER, timeline, gantt, quadrant, journey), up to 40 lines and 3000 characters. Refused whole
  for tags and entities (Mermaid's `#name;` too), control or format characters, and anything that does more than
  draw: `click`, `call`, `href`, `link`, `callback`, `%%{` directives and front matter, `style`/`classDef`/
  `linkStyle` (the colours are Swift's), `url(`, `@{ }` images and icons, and URLs. Sized by Swift: more than 12
  statements (6 for sequence, timeline, gantt and journey) opens with Read more.
- Drawn by `diagramBlock` (`overlay/src/blocks.ts`) through `overlay/src/mermaid.ts`: `@mermaid-js/tiny` 12.3.0, an
  exact pin. It's a classic script, so the build copies it as a file of Swift's own and it loads by a script tag,
  only when the first diagram is shown, under the CSP as it was (`script-src` falls back to `'self'`). Strict mode,
  no HTML labels, `maxTextSize` and `maxEdges` caps, Swift's neutral colours. Its SVG is parsed as SVG and admitted
  only if `inert()` finds no script, `foreignObject`, image, link, `on*` handler, outside `href` or `url()`. A
  source that doesn't draw shows "Swift couldn't draw this diagram." and the words. Checked in the harness under
  the overlay's CSP: no violation, and only same-origin requests.
- `mindmap`: a root and its children, each `{label, children}`: up to 3 levels and 30 ideas, labels up to 60
  characters of plain text. Drawn by `mindmapBlock`, Swift's own nested lists from the prototype, textContent only,
  no dependency. The card selects up to 12 ideas breadth-first, so deeper ideas cannot displace later branches; it
  says how many more remain. More than 12 ideas opens with Read more.
- Both sit under the worker's bar ("Drawn from the worker's outline" / "Mapped by the worker, not checked by
  Swift") in neutral colours, never Swift's accent, amber or red. Copy gives a diagram's source and a map's
  indented lines.
- Bundle (`vite build`): the eager JavaScript grows by 1.7 kB (0.5 kB gzipped) and the CSS by 1.7 kB (0.3 kB
  gzipped). New and lazy: `mermaid.ts`'s chunk, 1.5 kB, and `mermaid.tiny.js`, 2,853 kB (0.76 MB gzipped, §9),
  fetched from Swift's own files the first time a diagram shows.
- In the dev harness (`__design("answerDiagram")`, `"answerDiagramLong"`, `"answerDiagramBroken"`,
  `"answerMindmap"`, `"answerMindmapLong"`):

  | Diagram, dark | Diagram, light | Sequence, opened with Read more |
  |---|---|---|
  | ![](b4/slice2-diagram-dark.jpg) | ![](b4/slice2-diagram-light.jpg) | ![](b4/slice2-diagram-long-dark.jpg) |

  | Mind map, dark | Mind map, light |
  |---|---|
  | ![](b4/slice2-mindmap-dark.jpg) | ![](b4/slice2-mindmap-light.jpg) |
- Fixed on `claude/b4-diagram-902ffc`: diagrams redraw when the theme changes; a diagram too wide to stay readable
  opens in full instead of shrinking; mind-map cards select ideas breadth-first and scroll their preview on short
  screens instead of clipping it. The owner checks for this slice are still pending. The licence check §4 mentions
  doesn't exist yet, so nothing checks Mermaid's licence automatically.

**Slice 3, document previews (2026-11-15, branch `claude/b4-diagram-902ffc`):**
- `preview`: a local PDF, DOCX, PPTX or XLSX path. Swift permits a preview only inside the run's read scope or after
  that exact file was approved through `Read`; secret paths remain refused.
- PDF: `Windows.Data.Pdf` renders the first page in the packaged `pdf_page.ps1` helper. Swift resizes the PNG to at
  most 512×720 pixels, caps it at 1 MB, and gives rendering 15 seconds. The helper is included in the wheel.
- Office files use only Python's standard-library ZIP/XML support: Word's document text, the first PowerPoint slide
  in presentation order, or the first Excel worksheet in workbook order (including shared and inline cell text).
  Parts are bounded; DTD/entity declarations, NUL-containing XML and archives with over 10,000 entries are refused.
  Excerpts are capped at 600 characters; there is no new dependency.
- The result shows the PDF thumbnail or Office excerpt, filename and an explicit **Open** button. The file path is
  not copied or read aloud; the Tauri command canonicalizes it and accepts only the four supported extensions.
- Verified with synthetic PDF/OOXML fixtures, the overlay tests and production build, Rust tests, and a wheel
  inspection. The dev harness showed the PDF image/page count and the Office excerpt with **Open** and **Read more**.
  No personal documents were opened. Owner checks b4-diagram-902ffc-4 and -5 are pending.

**Slice 4a, charts (2026-11-15, branch `claude/b4-diagram-902ffc`):**
- `chart`: one bar or line chart, with 2–8 short categories and 1–4 named series. Values must be finite and within
  ±1 billion, with one value per category; the optional unit and title are plain text. The overlay draws the chart
  from SVG elements created by Swift's own code, never from worker-provided markup.
- The card shows the first six categories; the reader shows all eight. The chart and series have neutral theme
  colors, and line series have different dash patterns. Its SVG has a text description; Copy emits a tab-separated
  table of every category and value, not the SVG or only the visible subset. The worker's data is marked as not
  checked by Swift.
- The owner check is b4-diagram-902ffc-6. Project cards followed in slice 4b.

**Slice 4b, project cards (2026-11-15, branch `claude/b4-diagram-902ffc`):**
- `cards`: 1–8 read-only project summaries, each with a plain-text title (80 characters at most) and optional
  detail (120) and meta (48). Larger or text-heavy sets are marked expanded by Swift.
- The card shows up to three projects in a responsive neutral grid; the reader shows all of them. Copy includes
  every title, detail and meta line. Each card is marked as the worker's data, not a Swift recommendation.
- The owner check is b4-diagram-902ffc-7. B4 step 4 now has both approved shapes; checks 6 and 7 remain for the
  owner to run.


- Each shape: a seam scenario that fails with it undone, owner checks numbered from "Next free check number", their
  ledger lines, and report lines.
- Routing parity unchanged: the routing doesn't move.
- Charts and project cards (slices 4a and 4b) are implemented; owner checks 6 and 7 remain.
- An ADR for the shipped renderer list and the `show_result` contract.

## 9. The two checks before approval (2026-11-13, on the owner's PC)

### Mermaid's real size and behaviour

Measured from the npm tarballs, without installing them in the project (`npm pack` into a scratch folder):

| | `@mermaid-js/tiny` 12.3.0 | `mermaid` 12.3.0 (full) |
|---|---|---|
| What ships | one file, `mermaid.tiny.js` | 105 lazily loaded chunks |
| Size | 2.85 MB minified, 0.76 MB gzipped | 5.4 MB, 1.6 MB gzipped |
| Dependencies at run time | none (all bundled) | none at run time; bundles elkjs (EPL-2.0/GPL-3.0) and KaTeX |
| Diagrams | all but mind map and architecture | all |

**Timings (WebView2 / Chromium):**
- Loading and parsing the file cold takes 0.8 s, once. After that, loading it again takes 26–32 ms.
- Rendering a diagram takes 82–106 ms.
- The dev server took 5–37 s, because Vite adds a 13 MB inline source map to the file. A built Swift won't do that.

**Offline:** the file holds no `fetch` calls, and its only URLs are documentation strings. With Mermaid rendering,
the page made requests to `localhost` only.

**Markup in a worker's labels** (`?shape=mermaid-evil`):
- An `<img onerror>` label is drawn as the literal text `<img src="x">`.
- A `<script>` label is dropped, leaving an empty node.
- `click a "javascript:…"` leaves an `<a>` with no `href`.
- The rendered SVG has no `img`, `script` or `foreignObject` element and no `on*` attribute.

So strict mode holds. The one loss is that a dropped label shows as an empty box: `parseShape`'s check should
refuse labels with `<` or `>` before Mermaid sees them, and show words instead.

**Verdict:** ship `@mermaid-js/tiny` 12.3.0, pinned, imported lazily. Its README says it's meant for a CDN.
Swift bundles the same file from npm with the lockfile's integrity hash, so nothing is fetched while Swift runs.

### Document previews

- **Windows Shell thumbnails fail on this PC.** Of 24 real files (6 each of PDF, Word, PowerPoint and Excel, from
  Documents, Downloads, Desktop and OneDrive), only 2 PowerPoints gave a thumbnail.
  - PDFs have no thumbnail handler (Adobe isn't installed, and Edge doesn't register one).
  - Office's handlers only return a preview picture saved inside the file, and most files don't have one.
  - Failures took 0.1–1.8 s on the owner's files and 5–9 s on files the spike made itself.
- **`Windows.Data.Pdf` renders PDFs:** 6 of 6, the spike's own PDF and 5 of the owner's, first page to PNG, in
  0.8–2.3 s each. That's through a PowerShell helper (`Windows.Data.Pdf` through `AsTask`), and PowerShell's start-up
  is most of it.
- **The Office text excerpt works:** 14 of 14 real Word, PowerPoint and Excel files, in 1–62 ms, with the Python
  standard library alone. It reads at most 2 MB of the part, never the whole file. Four more files in the sample
  were macOS `._` metadata files with an Office name, and the check refuses them (they aren't zip files).

Only counts and timings were kept from the owner's files. No file names, text or images were saved or looked at.

**Where to call `Windows.Data.Pdf` from: decide when building Preview.**
- *A PowerShell helper from the backend* is proven here and needs no dependency, but costs about 1–2 s a page.
- *Rust in the Tauri app* uses the `windows` crate. It's already in `Cargo.lock` (0.62, through Tauri), but Swift's
  own `Cargo.toml` uses `windows-sys`, which has no WinRT, so it would be a new direct dependency on a crate that's
  already built.
- *Python's `winrt` packages* (MIT) are a new dependency.

Start with the PowerShell helper (`shortcut:` with its cost), and move to Rust if 1–2 s shows on the card.

## 10. Later, not B4: a brainstorm map that grows by voice

The owner wants this (2026-11-14). It's a separate item because it isn't a way to *show* a result: it's a thing
Swift keeps and changes over several turns. B4's mind map draws a map once, from one answer. A brainstorm map:

- **Lives across turns:** "add pricing under Marketing", "move that under Risks", "drop the Naivasha idea", "what
  have we got so far?" Each turn changes the same map, and the card redraws it with the change marked for a
  moment.
- **Needs run records** (the groundwork session `gw-run-records`): the map belongs to one conversation's record.
  Each change is a step in it, so "undo that" and "show me the map from this morning" work, and a restart doesn't
  lose it.
- **Needs the memory store** (`gw-memory-store`) only to keep a map past its conversation ("keep this brainstorm").
  The product rule holds: the map is written from the owner's own words, or from ideas they accepted on a card,
  never from what a worker read. A worker's suggested ideas are drawn as suggestions (marked as the worker's, as in
  §2) until the owner keeps them.
- **Edits are Swift's own, not the worker's:** add, move, rename and remove an idea are small typed operations on
  the map that Swift applies and checks against the same limits, past which the map moves to the expanded card. The
  worker proposes ideas; it never rewrites the map.
- **Removing an idea isn't deleting a file,** and it can be undone, so it needs no card. Saving the map *into an
  app* (a Word document, an email) needs the owner's own words asking for it, as every write into an app does.
- **The same shape draws it:** the mind-map block from B4, with "new" and "suggested" marks added.

Order: after run records land, and after B4's mind map. It needs the owner's design calls first: how a change is
shown, how many suggestions at once, and whether the map can be opened in the Swift window to edit by hand.
