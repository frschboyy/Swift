// The overlay's side of the seam test (tests/unit/test_seam_replay.py): frames the real backend sent,
// on stdin as JSON, go through the real presenter and question reducers, the same calls main.ts makes
// for each message, and the rows through the Deck (ADR-018). What the screen ends up showing goes to
// stdout, with the acknowledgements main.ts would send back (``P.drawn``). No DOM: what is drawn from this state is still checked by replaying frames in the dev harness.

import * as Q from "../../src/ask.ts";
import { commandFolded, commandParts, stepCommands } from "../../src/cardtext.ts";
import * as D from "../../src/deck.ts";
import * as P from "../../src/presenter.ts";

type Frame = { type: string; data: Record<string, any>; n?: number };

const frames: Frame[] = JSON.parse(await new Response(process.stdin as any).text());
const now = 1_000_000;
let pres = P.initial;
let asked: Q.Ask | null = null;
let deck = D.initialDeck;
// The confirm card's frame, as main.ts keeps it (lastConfirm).
let confirmData: Record<string, any> | null = null;
// The words on the card, as main.ts keeps them.
let words = "";
const lost: string[] = [];
const broken = new Set<string>();
// What main.ts tells the backend it drew (``screen``), for the test to hand back to the session.
const acks: ReturnType<typeof P.drawn>[] = [];

function answer(kind: "result" | "error", d: Record<string, any>, ms: number | null): void {
  const r = P.onAnswer(pres, { kind, runId: d.run_id, threadId: d.thread_id, summary: d.summary, ms }, now);
  pres = r.p;
  // Refused, its row must say how it ended: otherwise the owner never hears the answer.
  if (!r.shown && !pres.rows.some((row) => row.runId === d.run_id)) lost.push(`${kind} ${d.run_id ?? ""}: ${d.summary ?? d.message ?? ""}`);
}

for (const { type, data: d, n } of frames) {
  switch (type) {
    case "state":
      pres = P.onState(pres, d.state, d.run_id ?? null, d.thread_id ?? null).p;
      break;
    case "runs": {
      const onCard = pres.focus ?? pres.card.runId;
      words = D.wordsComingForward(pres.rows, onCard, d.focus) ?? words;
      pres = P.onRuns(pres, d.focus, d.rows.map((r: any) => ({
        runId: r.run_id, threadId: r.thread_id, title: r.title, state: r.state, activity: r.activity, app: r.app,
        startedMs: r.started_ms, summary: r.summary, words: r.words,
      })), d.waiting);
      deck = D.onRows(deck, pres.focus, pres.rows, now, onCard);
      break;
    }
    case "transcript":
      if (d.final) words = d.text;
      break;
    case "ask":
      asked = Q.onAsk(asked, d as Q.AskData, now);
      break;
    case "confirm.request":
      pres = P.onConfirm(pres, d.request_id, d.run_id, now);
      confirmData = d;
      break;
    case "confirm.hold":
      pres = P.onConfirmHold(pres, d.request_id, d.held, now);
      break;
    case "countdown":
      pres = P.onCountdown(pres, d.request_id, d.left_s, d.running, now);
      break;
    case "presence":
      pres = P.onPresent(pres, d.state === "here");
      break;
    case "followup":
      pres = P.onFollowup(pres, d.open, d.seconds, now);
      break;
    case "result":
      if (asked?.runId === d.run_id) asked = null;
      answer("result", d, null);
      break;
    case "error":
      if (d.code !== "bad_message") answer("error", d, 1000);
      break;
  }
  for (const v of P.violations(pres)) broken.add(`${v} (after ${type})`);
  const askId = Q.askVisible(asked, P.stageOf(pres), pres.focus) ? asked!.id : "";
  if (P.CARD_FRAMES.has(type)) acks.push(P.drawn(pres, n ?? 0, askId));
}

const led = P.confirmVisible(pres) && confirmData?.request_id === pres.pendingConfirm
  && commandFolded(confirmData.tool, confirmData.purpose);

// Well after the last frame: every request old enough to have its edge.
const settled = D.deckView(deck, pres.rows, Number.MAX_SAFE_INTEGER);

process.stdout.write(JSON.stringify({
  behind: settled.edges.map((e) => e.row.runId),
  behindStates: settled.edges.map((e) => e.row.state),
  more: settled.edges.reduce((n, e) => n + e.more, 0),
  stage: P.stageOf(pres),
  cardRun: pres.card.runId,
  cardWords: words,
  question: Q.askVisible(asked, P.stageOf(pres), pres.focus) ? asked!.question : null,
  confirm: P.confirmVisible(pres) ? pres.pendingConfirm : null,
  // The countdown the card draws (T-08): what the backend's clock last said.
  countdown: P.confirmLeftMs(pres, now),
  // B1: what a command card leads with (the agent's words), and whether its command is folded under it.
  confirmLead: led ? confirmData!.purpose : null,
  // The command's first line, always in view under the lead, and what is folded under it ("" for nothing).
  commandHead: led && !confirmData!.step ? commandParts(confirmData!.detail).head : null,
  commandFolded: led && !confirmData!.step ? commandParts(confirmData!.detail).rest : null,
  // B2: the commands a step card approves, all listed in view, none folded; null on any other card.
  confirmStep: led ? stepCommands(confirmData!.tool, confirmData!.purpose, confirmData!.step, confirmData!.detail) : null,
  lost,
  broken: [...broken],
  acks,
}));
