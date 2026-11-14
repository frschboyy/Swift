# B6: the live view ("watch me"), a study

Workstream item B6 (owner checks 93, 95). On 2026-11-13 the owner agreed the live view should look distinct from the
working cards, and asked two questions:

1. Should the live view be a card of its own, or a mode of the working card?
2. Should it feel technical (steps ticking by, like a console) or visual (watching the email being written, the slides
   appearing, like a design taking shape in pen.dev)?

This is a study. It changes no product code. The prototype is a dev page with fake data
(`overlay/dev/live-b6.html`), and the screenshots are in `docs/design/b6/`.

## Recommendation in short

- **Form: a window of its own, as it is today, but restyled as a monitor** so it can't be mistaken for a working card. The
  working card stays glass. The live view gets a solid, dark frame in both themes, a title bar with a pulsing **LIVE**
  mark and a running clock, and monospace for the technical parts.
- **Feel: a mix.** When Swift is making something you can see (an email, a Word document, a deck), the view shows that
  thing being built on a white "paper" surface. Under it, one console line always shows the step Swift is on. When there
  is nothing to see (research, a command), the view is the console, plus the sources list it has today.
- **Order:** Word first (its stream exists already, so it's overlay-only work), then email, then decks once Swift can make
  a deck at all (it can't today).

## What exists today

- `overlay/src/live.ts` keeps one `LiveRun` per request, fed by `live` items from the backend: `doing` (the step),
  `source` (a page found or read), `note` (Claude's short notes between tool calls), `text` (a paragraph Swift wrote into
  an app) and `hint`. "Show me", or **Watch** on a card or edge, opens it in its own pane window (at most 3, ADR-017 §7).
  When the request ends it says Done and links the answer, then closes 45 s after the owner last looked at it (check 95).
- `overlay/src/views.ts` `liveCard` draws it with the same glass panel, header and footer as the reader and the working
  card. That's why it doesn't read as distinct: the only differences are a LIVE badge and an accent border.
- The backend sends `live` items from two places. `executors/claude_mapping.py` `LiveMapper` turns Claude Code's
  WebSearch/WebFetch calls and text into sources and notes. `workflows/desktop_tools.py` `desktop_write` sends each
  paragraph after it's written into Word or the app in front. `session._send_live` puts only counts per kind in the
  run record, never the content (product rule: logs content-free).
- `workflows/artifacts.py` is a separate channel: typed snapshots (`email_draft`, `recipient`, `send_status`, …) that
  the working card's "show me" detail view opens (ADR-010). `draft_email` publishes the whole draft as one artifact.

## Question 1: its own card, or a mode of the working card?

**Its own window.** Reasons:

- **The jobs differ.** The working card is where the request asks for things: an OK, an answer, a stop. It has to stay
  small and always readable. The live view is optional watching. It's large, there can be up to three at once, and it
  stays open after the request ends. As a mode of the card, it would cover the approval or the question just when one
  arrives, or the card would grow to the size of an email.
- **It's already built as its own window.** Pane windows, placement, dragging, Stop per request and lingering after the
  end all exist and passed checks 93 to 95. Making it a mode would mean undoing that work.
- **Distinct is a matter of look, not structure.** Today it's a working card with a badge. The prototype keeps the
  structure and gives it a different chrome. In each screenshot, the working card on the left and the live view on the
  right look like different things.

The monitor frame as prototyped:

| | Working card | Live view |
|---|---|---|
| Surface | glass, `--panel`, blur | solid near-black (`#0d1018`) in **both** themes, no blur |
| Header | the owner's words | a title bar: **● LIVE** (red, pulsing) · title · `00:06.2` clock · × |
| Type | Segoe UI | Segoe UI for titles; Cascadia Mono for steps, clock and results |
| Content | state and actions | what's being made (on paper), or the console |
| Footer | the request's actions | Show in *app*, Stop |

## Question 2: technical or visual?

**Both, chosen by what there is to see.** What the prototype shows:

- **Technical** (`email-technical.jpg`, `deck-technical.jpg`): a console listing each step with its time, the tool and a
  short result (`→ 1 match`, `→ 5 paragraphs`). It's honest and readable, and it's the right view for research and
  commands. For an email or a deck, though, it shows only that work is happening, never the work itself. "Slide 4 of 5"
  doesn't let you watch a deck being made.
- **Visual** (`email-visual-writing.jpg`, `email-visual-filling.jpg`, `deck-visual.jpg`, `deck-visual-done.jpg`): the
  email appears on a compose sheet with a caret, word by word. Then, while Gmail is filled in, the field being filled
  lights up (To, then the message, then the subject). The deck shows the current slide large, with its title and then its
  bullets appearing, and a strip of all five slides underneath: built ones filled in, the current one outlined, the rest
  dashed. One console line at the bottom keeps the technical feel the workstream line asks for ("the watch keeps a
  technical feel").

The mix rule: **visual when the run carries a stream of what's being made; the console otherwise.** A research run that
then writes into Word starts as a console with sources and turns into the page view once the first paragraph arrives.

## What a visual view needs underneath, and what it costs

A visual view needs the content as it's made, not only step names. Per kind:

| What's made | Where the stream comes from | Real today? | Cost |
|---|---|---|---|
| **Word / app in front** | `desktop_write` already sends each paragraph as a `live` `text` item after writing it | yes | **Small, overlay only:** draw `written` as a page instead of today's grey box. Paragraphs are the real writing step, so the stream is truthful as it is |
| **Email: the draft** | The model writes the whole message as **one** `draft_email` tool call, and Swift publishes it as an `email_draft` artifact when the call completes. Today nothing exists to stream until it's done. To show it being written: turn on the SDK's partial messages (`include_partial_messages`) in `executors/claude_code.py`, read the `input_json_delta` events for `draft_email`, pull `subject` and `message` from the partial JSON, and send them as a new `live` kind (`draft`, throttled to about 10 a second) | no | **Medium, backend + overlay:** a partial-JSON reader, one new item kind, a reducer case. The greeting and sign-off are added by Swift (`compose`) after the call, so the final artifact replaces the streamed text when it lands |
| **Email: the recipient** | Only from `find_contact` / `scope.resolved`, **never** from the address the model is typing in the stream | yes | None. The **To** chip shows the resolved contact's name, so a recipient Swift didn't resolve is never shown as if it were real (product rule: recipients only from contacts) |
| **Email: Gmail fill** | `desktop/gmail_fill.fill` pastes each field whole (To, body, subject). The real progress is per field | partly | **Small:** one content-free step per field (`Filling in Gmail: To`); the overlay highlights that field on the draft it already has. Nothing is streamed into the page: Gmail gets each field in one paste |
| **Presentation** | **Swift can't make a deck today.** No tool does it. Claude Code could write a python-pptx script, but the view would only see "Running a command" and could show nothing visual | no | **Large, and it belongs to the capability:** a Swift tool that takes structured slides (`add_slide(title, bullets, notes)`, one call per slide, so each slide really is a step). Each call sends a `live` `slide` item, and the overlay draws a schematic slide (title and bullets, as in the prototype), **not** a picture of the real slide. Writing the file needs python-pptx (a new dependency, justified only when decks become a feature) or PowerPoint over COM (writing into an app, so only when the owner asked for PowerPoint). Pixel-true thumbnails (exporting from PowerPoint after each slide) are slow and fragile. Not recommended |

### The product rules

- **Logs content-free.** `_send_live` already logs counts per kind only. New kinds (`draft`, `slide`) go into its
  counted list and nowhere else. The stream goes to the overlay over IPC and is held in memory there (`live.ts` never logs).
  Ship it with a test that sends a draft through `_send_live` and finds none of its words in the log records or the run
  record.
- **Swift writes into apps only when the owner asked.** The live view only shows. It never writes anything itself. The
  deck preview is drawn in Swift's own window, so watching a deck being planned writes nothing anywhere. The `.pptx` is
  saved or PowerPoint opened only when the owner's words asked for it, like `desktop_write` and `fill_in_email` today.
  **Show in PowerPoint / Gmail** only brings forward what already exists.
- **Approvals stay on the working card.** Nothing in the live view approves anything. Stop is its only control over the
  request.

## Suggested order, if the owner agrees

1. **The monitor frame and the Word page.** `views.ts` `liveCard` + `styles.css`. No backend change. Today's sections
   (sources, notes) move under the console line. Seam scenario: a running live view with written text.
2. **Email.** Gmail fill steps per field (backend, small), the draft sheet drawn from the `email_draft` artifact the
   overlay already gets, then the partial-message stream for the writing itself (medium). Step 2 without the stream is
   still worth it: the sheet appears when the draft is done and the fields light up as Gmail is filled.
3. **Decks.** Only together with a deck-making capability (a C-section item, not B6).

Each step would get owner checks when it's built (from the next free number in `docs/testing/owner-checks.md`). This study
changes no behaviour, so it adds none.

## Decisions for the owner

1. **Form:** its own window, restyled as a monitor (recommended), or a mode of the working card?
2. **Feel:** the mix (recommended): visual when there's something being made, the console otherwise, with one console
   line always under the visual. Or technical only, or visual only?
3. **The LIVE mark's colour:** red, as in the prototype (the usual "recording" sign), or Halo's accent blue? Halo uses red
   for failures, so red could read as an error. The recommendation is red, because the mark pulses and sits only in the
   live view's title bar.
4. **The email's writing:** stream it as it's written (partial messages, medium cost), or show the sheet once the draft is
   done (small cost)? Recommended: the small one first, the stream afterwards.
5. **Decks:** agree that the visual deck waits for a deck-making capability, and that the preview is a schematic slide,
   not a picture of the real one?

## The prototype

Dev only, fake data, no backend:

```
http://localhost:1431/dev/live-b6.html?work=email|deck&feel=visual|technical[&at=MS][&theme=light]
```

Without `at` it plays in a loop; `at` freezes it at that many milliseconds (as the screenshots were taken). To run it,
add a temporary `.claude/launch.json` entry for vite on 1431 (CLAUDE.md, "Dev harness") and revert it afterwards. The
page draws today's working card on the left for comparison. It shares no code with the overlay except `dom.ts` (`el`,
`icon`) and the stylesheet.

| | Email | Deck |
|---|---|---|
| Technical | `b6/email-technical.jpg` | `b6/deck-technical.jpg` |
| Visual, while it works | `b6/email-visual-writing.jpg`, `b6/email-visual-filling.jpg` | `b6/deck-visual.jpg` |
| Visual, done | — | `b6/deck-visual-done.jpg` |
