# ADR-012: Desktop interaction, structured first (exploration)

- **Status:** Exploration. Nothing is decided. Measurements on the owner's apps are in §9 (run 2026-10-25/26); the owner's questions are in §11.
- **Date:** 2026-10-25
- **Builds on:** ADR-009 (overlay mechanics, caret-aware placement), ADR-010 (gateway, artifacts, "show me"), ADR-011 (workflow ecosystem)
- **Probe:** [`spikes/desktop/`](../../spikes/desktop/README.md)

## 1. Context

The owner wants Swift to work *in* the desktop, not only beside it:
- "open this app";
- dictating into Word, or "start a template on this topic" in the open document;
- "compose and send this" with Gmail open in the browser.

The work should be **visible**: the owner watches it happen in their own apps.

The owner's questions:
1. Is this the same direction as ADR-011, or a change of scope?
2. Do screenshots have to be the way Swift sees the screen? Or can Swift use native, structured, more private representations, with screenshots only as a fallback?

## 2. Where it fits

It is the same direction, and it sharpens what Swift is.

| Way of seeing the work | Where | Since |
|---|---|---|
| **Results** | A card after the fact | ADR-006 |
| **"Show me"** | Swift reports what it's doing, in the overlay | ADR-010 |
| **"Watch it happen"** (new) | The work happens in the owner's own apps, in front of them | This ADR |

In ADR-011's terms nothing structural changes:
- desktop control is a family of **capabilities**;
- a workflow step can run **in the foreground**, and then the app itself is the "show me" view;
- **agents** decide what to type or click;
- the **gateway** decides what is allowed.

What does change is how Swift is described. It moves from "a voice front door that hands work to agents" to **"a voice co-pilot that operates your computer with you, visibly and under your control."** Desktop context becomes one of Swift's senses, like the microphone.

## 3. What Windows exposes without a screenshot

| Layer | Gives | Notes |
|---|---|---|
| **Win32 window and input APIs** | Foreground window, its process, window positions and stacking order, cursor, text caret (ADR-009 already uses `GetGUIThreadInfo`), clipboard; events on focus and foreground changes | Instant, local, no model |
| **UI Automation (UIA)**, the accessibility tree | Elements with type, name, automation id, position and states (including "is a password field"); **patterns** to act without the mouse (Invoke, Value, Text with selection and caret, Selection, Toggle, ExpandCollapse, Scroll); **events** for focus, selection and structure changes | What screen readers use, so mainstream apps support it. Chromium browsers have used a native UIA provider by default since Chrome 138 (2025), still built on demand when a client asks; Electron apps such as VS Code follow Chromium. Weak for games, canvas and custom-drawn interfaces, and some Java and Qt apps. |
| **App object models** | Office (Word, Excel, Outlook, PowerPoint): read and write the open document live, with the app's own undo. Shell: the open folder and **selected files**. Browser: page structure through an extension with native messaging, inside the owner's real session. VS Code: extension API and command line. | More precise than UIA, but written per app |
| **Windows agent platform** (preview) | MCP servers registered on the device ("agent connectors"); built-in File Explorer and System Settings connectors; apps declaring actions | The most native long-term route; early |
| **Local pixels** | Windows' built-in OCR; local UI-element detectors such as OmniParser | OCR is fast enough on this laptop. Detectors need a GPU or NPU, and the development laptop (i7-10610U) has neither. |
| **Screenshot to a cloud vision model** | Anything visible | The universal last resort |

Prior art: Microsoft's UFO² agent combines UIA with vision-based detection and native app APIs. Existing "Windows MCP" servers expose UIA to agents. The structured-first approach is established; Swift's twist is voice, one trust boundary, and keeping context local.

## 4. Four levels of desktop interaction

| Level | What | Example | Route | Effort |
|---|---|---|---|---|
| 1 | Launch and focus | "Open Word" | Exists for configured names (`routing/local.py`). "Open *this*" needs context (§5.1). | Small |
| 2 | Put content where the owner is | "Write: …" into the focused field | UIA Value or Text pattern, else paste, else keystrokes | Small |
| 3 | Operate an app through its own interface | "Start a template on photosynthesis" in the open Word document; "move these files" in Explorer; filling Gmail's compose window | App object models, UIA patterns, browser extension | Medium, per app |
| 4 | General computer use | Anything, in any app | Snapshot (structured, else screenshot) → model → act → check, repeated | Large; slowest and riskiest |

Most of the value is in levels 1 to 3. Level 4 is a fallback, not the default.

## 5. Proposed hybrid architecture

```
 owner's apps ──(Win32 events, UIA events)──► [1] context tracker (always on, local)
                                                   │  foreground app, window, focused element,
                                                   │  selection, caret: used by routing ("this", "here")
                                                   ▼
 request needs more ─────────────────────────► [2] structured snapshot (on demand)
                                                   │  pruned subtree: interactive elements with
                                                   │  short refs (e12 Button 'Send'), plus selection
                                                   │  → redaction → only this goes to a model
                                                   ▼
 model answers "set e12 …" ──────────────────► [3] act by reference, then check by re-reading
                                                   │  app object model ▸ UIA pattern ▸ paste ▸ keys
                                                   ▼
 every action ───────────────────────────────► gateway: element meaning → risk → confirm card
 fallback when structure is missing ─────────► [4] local OCR ▸ screenshot to vision model (permission)
```

### 5.1 The context tracker

- Event-driven (WinEvents, UIA focus and selection events), cheap, and **nothing leaves the machine**.
- It keeps a small current state: app, window class, focused element type, whether there is a selection and how long it is.
- Routing uses it:
  - "open *this*" (the selected file in Explorer);
  - "rewrite *this*" (the selection);
  - "send *it* to Ada" (the open draft).
- It also feeds smart placement, which today reads only the caret.

### 5.2 Structured snapshot

- Built on demand from the focused window: elements that are on screen and interactive, plus text and document elements near the focus.
- Each entry is one short line (`e12 Button 'Send'`). On the taskbar test this came to about 126 tokens for 13 interactive elements, against roughly 1,500 or more for a screenshot of the same region.
- The selection's text is included only when the request is about it.
- **Redaction before anything leaves:**
  - password fields never read;
  - a per-app deny list (password manager, banking site in the browser) never read;
  - other windows and notifications never included.

### 5.3 Acting by reference, checking by reading

- The model answers with element references and an action ("invoke e7", "set value of e12").
- Swift picks the most precise route: the app's object model, then a UIA pattern, then paste, then keystrokes. Clicks at coordinates come only with level 4.
- **Patterns act without taking over the mouse or keyboard**, so the owner's cursor stays theirs.
- After acting, Swift reads the element again to confirm the change. A mismatch is reported, not retried blindly.

### 5.4 Exposed as Swift tools

`desktop.context`, `desktop.snapshot`, `desktop.act`, `desktop.type` and `desktop.open` join the `ToolHost` (ADR-010). Every provider then uses the same native layer over MCP. The gateway assigns their risk (§7).

### 5.5 Where it runs

| Option | For | Against |
|---|---|---|
| Python backend, UIA via `comtypes`, in a dedicated thread with timeouts | Next to the tools, gateway and routing; one language for logic | A new dependency (`comtypes`); COM threading must never block the event loop |
| Tauri (Rust) process, `windows` crate | Already does window work (caret, hit regions); native speed | Logic split across two processes; needs a protocol for snapshots and actions |

Leaning: **Python for the logic, in a worker thread**, with Rust kept to window mechanics. To revisit if the probe shows UIA latency that matters.

## 6. Foreground mode

The owner and Swift share one screen, keyboard and focus. When Swift works in an app:

- **Hands-off signal:** the overlay shows "Swift is writing in Word". The card stays put and never takes focus (ADR-009).
- **No cursor takeover** at levels 1 to 3. If level 4 must click, it says so first.
- **Esc stops instantly.** Swift checks for a stop between every action.
- **Undo:** prefer actions the app itself can undo (Word's Ctrl+Z). Swift records what it did so "undo that" can reverse it.
- **Owner input wins:** if the owner starts typing or clicking in that window, Swift pauses and asks before going on.
- **Streaming:** for long text, write it as it's generated, so the owner watches it appear.

## 7. Safety and privacy

- **Approvals in the UI:**
  - Pressing a button whose meaning is external or destructive (Send, Delete, Buy, Submit, Post) is an external or destructive action. It goes through the gateway's confirm card, exactly like `send_email`.
  - When the element's meaning is unclear, Swift assumes the higher risk.
  - **The owner's own click as approval:** Swift fills in the Gmail compose window, and the owner presses Send. No API setup is needed, and the most consequential action stays with the owner.
- **Untrusted screen content:** text read from the screen (web pages, emails, documents) is tainted (ADR-011 §7.3). It can't choose an action or a target.
- **Minimization over secrecy:** structured text is still private content. The gain is sending *only* the focused part, never the whole screen. Screenshots need a permission, per app or per use, and Swift says when it is "looking".
- **Windows' own boundaries help:**
  - Swift stays a normal, non-administrator process, so it can't drive windows running as administrator (UIPI).
  - UAC prompts and the lock screen are unreachable.
  - Nothing executes outside the `ACTIVE` state (threat model T7).
- **Threat model:** new entries are needed for screen-content injection, misclicks on consequential controls, and screen data leaving the machine (an extension of T11).

## 8. Relation to ADR-010 and ADR-011

- **"Show me"** gains a foreground counterpart: when work happens in an app, "show me" brings that window forward instead of opening an artifact.
- **Recipes:** UI steps refer to elements by automation id, name and type, never coordinates. Replays are deterministic, and they fail clearly when an app changes. Hardening (ADR-011 §5.3) works on UI tasks too.
- **Capabilities are scoped per app:** `desktop.act: {apps: [WINWORD], patterns: [Text, Value]}`. A workflow can't silently start operating a different app.
- **Workers:** computer-use quality differs a lot between providers. Role-based provider choice (ADR-011 §7.2) lets level 4 go to whichever provider is best at it.

## 9. Measurements (owner-run)

`spikes/desktop/uia_probe.ps1` reports, per app:
- how fast Swift knows the app, the focus and the selection;
- which actions the focused control supports;
- how much of the window is named or has automation ids;
- the size of a structured snapshot in tokens;
- walk and bulk-fetch times.

`-Word` writes into a new document live, reads it back through UIA, and undoes. Numbers only; no screen text.

Test run by the developer session on the taskbar:

| Measure | Result |
|---|---|
| Elements | 36 |
| Named | 83 % |
| With automation ids | 89 % |
| Interactive | 13 |
| Snapshot | about 126 tokens |
| Walk / bulk fetch | 220 ms / 135 ms (managed UIA client, an upper bound) |

### 9.1 Results on the owner's apps (2026-10-25/26)

The owner ran 35 probes. Runs that measured the wrong window were discarded: VS Code instead of Excel, and Word while it was still starting. Tokens are the estimated size of a structured snapshot of the visible interactive elements; a screenshot is roughly 1,500 or more.

| App | Focused element (what was clicked) | Read selection / text | Write | Window: named / with ids | Snapshot | Bulk read |
|---|---|---|---|---|---|---|
| **Word** | Document | yes: 69 chars selected, 53,446-char document in 27 ms | **yes**, through Word's object model: 133 ms a paragraph, read back through UIA (268 of 269 chars), undone in 88 ms (`-Word` test; Word's cold start 5.3 s) | 24 % / 8 % (tables make 512 cells) | ~325 tokens | 1.9 s; element-by-element walk 11 s |
| **PowerPoint** | a generic pane, even with the cursor in a slide text box | **slide text not visible** | object model only | 96 % / 53 % (ribbon) | ~800 | 0.2 s |
| **Excel** | the current cell | cell value (88 chars) | **yes**: cell value writable, plus Invoke and grid position | 96 % / 72 % | ~1,750 (every visible cell is an element) | 0.5 s |
| **Outlook** (classic) | message body / compose body | yes: 1,549-char message, 10-char selection | body offers text access but no Value: object model or typing | 78–83 % / 37–49 % | ~360–420 | 0.2 s |
| **Chrome** | address bar / page / Gmail compose | address (54 chars), page text (6k), selection, compose body | **address bar and Gmail compose writable** | 61–82 % / 10–49 % | ~460–1,200 | 0.2–0.4 s once built |
| **Brave, Edge** | the same as Chrome | the same | the same | the same | ~150–2,000 | the same |
| **Claude desktop** | message box | yes (10 chars, 5 selected) | **yes** | 83 % / 13 % | ~1,150 | 0.3 s |
| **Slack** | message box | yes (10 of 10 selected) | **yes** | 70 % / 18 % | ~920 | 0.1 s |
| **VS Code** | editor | **only a window of the file** (99 chars), selection not reported | value writable, but only that window | 72 % / 10 % | ~1,000 | 0.2 s |
| **Spotify** | a pane (the row click didn't take focus) | n/a | n/a | 90 % / 4 % | ~1,450 | 0.75 s |
| **WhatsApp** | a pane | **nothing**: 9 elements in the whole window | n/a | n/a | ~16 | 0.05 s |
| **Snipping Tool** | a pane | n/a | n/a | 93 % / 71 % (14 elements) | ~90 | 0.07 s |
| **File Explorer** | a file item | n/a (list selection isn't text) | items support Invoke, Value (rename), SelectionItem | 80 % / 72 % | ~640 | 0.3 s |
| Notepad | not run | | | | | |

### 9.2 What the results show

1. **Structured access works for most daily apps.** Word, Excel, Outlook, all three browsers, Claude, Slack and Explorer expose the focused control, text and selection in tens of milliseconds, without a screenshot. Level 2 (put content where the owner is) is feasible in all of them.
2. **Chromium apps behave as one family.** Chrome, Brave, Edge, Claude, Slack and VS Code expose text boxes the same way (Value plus Text, writable). One implementation covers them all. Their elements rarely have stable ids (4–37 %), so element references there rely on names.
3. **Browsers build their tree on first request.** The first look at Chrome or Edge saw 80 elements; two seconds later, 400–900. Swift's first desktop query to a browser must wait for this, then reads are fast.
4. **Three apps need their own route:**
   - **PowerPoint:** slide text wasn't visible through the managed UIA client's control view. Use PowerPoint's object model. Re-check with the raw view or native UIA before concluding PowerPoint hides it.
   - **VS Code's editor:** exposes only a window of the file around the cursor, and no selection. Use VS Code's extension API or command line.
   - **WhatsApp:** exposes almost nothing (9 elements). It is a candidate for the level-4 fallback (local OCR or a screenshot with permission), or for staying out of scope.
5. **Whole-window snapshots are often as big as a screenshot** (~1,000–2,000 tokens in Excel, Spotify, busy pages and Edge). They are cheap only when **scoped to the focus area** (Word: ~325; Outlook: ~400). §5.2's "near the focus" rule is necessary, not an optimisation.
6. **Speed:** Win32 basics take 30–100 ms, the focused element 10–120 ms, the selection 15–170 ms. Bulk reads take 0.1–0.5 s for most apps but 1.9 s for a Word document with tables, and element-by-element walks are much slower (up to 11 s). Snapshots must use bulk, scoped reads. The managed client is an upper bound; native UIA is to be measured when building D4.
7. **Live pages change while being read.** One Edge run failed with an element vanishing mid-read. The snapshot code must retry or read in parts.
8. **Incomplete data exists even in Windows' own apps.** One Explorer element reported no control type.

### 9.3 Consequences for the plan

- **D1–D2 (context, typing where the owner is) are confirmed** for every app above except WhatsApp.
- **D3 adapters, in the owner's order of value:**
  - Word and Excel through their object models;
  - Outlook (classic) through its object model: a draft created and shown for the owner to send;
  - Chrome through UIA, which is enough for the address bar and Gmail compose, so the extension route isn't needed for the basic Gmail case;
  - Explorer through its shell interface (selected files) plus UIA;
  - PowerPoint and VS Code through their own interfaces.
- **The Gmail question (§11.3) has a cheap answer:** filling Gmail's compose window through UIA in the owner's browser works with no Google setup. Classic Outlook offers the same through its object model.
- **Writing visibly is confirmed in Word.** The `-Word` test wrote a paragraph every 133 ms through the object model, fast enough to stream generated text. It read the result back through UIA with no screenshot, and Word's own undo removed it in 88 ms.
- **Still to run:** Notepad, and a PowerPoint re-check with the raw view.

## 10. Proposed order of work

| Phase | Scope | Useful on its own because |
|---|---|---|
| **D1: context and launch** | Context tracker; "open this", "open Word"; selection-aware routing | Swift knows where the owner is, entirely locally |
| **D2: dictate and insert** | Type or paste into the focused control; streamed writing; undo; foreground mode | Dictation and "write a template here", in any app with a text field |
| **D3: app adapters** | Word (object model), Explorer (selection, moves through ADR-011 W2 file tools), Chrome via extension (Gmail compose filled in, owner clicks Send) | The owner's three examples, structured and visible |
| **D4: snapshots and acting** | Structured snapshot, act by reference, checking, gateway risk from element meaning; MCP tools for providers | General structured control in UIA-friendly apps |
| **D5: fallbacks** | Local OCR; screenshot to a vision model with permission | Apps without structure |

D1 and D2 are small and fit next to ADR-011's W1. D3 depends on what the probe finds.

## 11. Questions for the owner

1. **Positioning:** "a voice co-pilot that operates your computer with you, visibly and under your control". Does that describe what you want Swift to be?
2. **Structured first:** levels 1 to 3 through Win32, UIA and app object models, with screenshots only as a permissioned fallback?
3. **The Gmail case:** fill in the compose window and let you click Send (no Google setup), or send through the API with Swift's confirm card (ADR-010), or offer both?
4. **Privacy defaults:** context tracked locally and always on; snapshots sent only when a request needs them, with redaction and a never-read list; screenshots off unless you allow them per app?
5. **Measurements:** run the probe on your daily apps (`spikes/desktop/README.md`) before choosing D3's adapters?

## Sources checked (2026-10-25)

- Chromium native UI Automation default from Chrome 138: developer.chrome.com/blog/windows-uia-support-update
- Chromium accessibility on demand: chromium.googlesource.com/chromium/src/+/HEAD/docs/accessibility/overview.md
- UFO²: microsoft.com/en-us/research/publication/ufo2-the-desktop-agentos/
- MCP on Windows and agent connectors (preview): learn.microsoft.com/windows/ai/mcp/overview
- The managed UI Automation client was checked by running the probe on the development laptop (§9). That Word's object model is registered was checked; the `-Word` test itself is owner-run.
