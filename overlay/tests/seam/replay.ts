// The overlay's side of the seam test (tests/unit/test_seam_replay.py): frames the real backend sent,
// on stdin as JSON, go through the real presenter and question reducers, the same calls main.ts makes
// for each message, and the rows through the Deck (ADR-018). What the screen ends up showing goes to
// stdout, with the acknowledgements main.ts would send back (``P.drawn``). No DOM: what is drawn from this state is still checked by replaying frames in the dev harness.

import { byline } from "../../src/agents.ts";
import * as Q from "../../src/ask.ts";
import { detailsText } from "../../src/answer.ts";
import { commandFolded, commandParts, quoteLines, stepCommands } from "../../src/cardtext.ts";
import * as D from "../../src/deck.ts";
import { canFlag } from "../../src/heardfix.ts";
import { needsReader } from "../../src/panes.ts";
import * as P from "../../src/presenter.ts";

type Frame = { type: string; data: Record<string, any>; n?: number };

const frames: Frame[] = JSON.parse(await new Response(process.stdin as any).text());
const now = 1_000_000;
let pres = P.initial;
let asked: Q.Ask | null = null;
let deck = D.initialDeck;
// The confirm card's frame, as main.ts keeps it (lastConfirm).
let confirmData: Record<string, any> | null = null;
// The words on the card, as main.ts keeps them, and their saved clip (heardClip: the flag corrects it).
let words = "";
let clip: string | null = null;
// The last answer's frame, as main.ts keeps it (lastResult).
let resultData: Record<string, any> | null = null;
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
      const forward = D.wordsComingForward(pres.rows, onCard, d.focus);
      if (forward !== null) [words, clip] = [forward, null];
      pres = P.onRuns(pres, d.focus, d.rows.map((r: any) => ({
        runId: r.run_id, threadId: r.thread_id, title: r.title, state: r.state, activity: r.activity, app: r.app,
        startedMs: r.started_ms, summary: r.summary, words: r.words,
      })), d.waiting);
      deck = D.onRows(deck, pres.focus, pres.rows, now, onCard);
      break;
    }
    case "transcript":
      if (d.final) [words, clip] = [d.text, d.clip ?? null];
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
      resultData = d;
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
  // F5: how many identical requests each edge stands for ("×3").
  behindTimes: settled.edges.map((e) => e.times),
  more: settled.edges.reduce((n, e) => n + e.more, 0),
  stage: P.stageOf(pres),
  cardRun: pres.card.runId,
  cardWords: words,
  // The flag on the heard words (heardfix.ts): the clip it corrects, or null where main.ts draws none.
  heardFlag: words && canFlag(clip, P.stageOf(pres)) ? clip : null,
  question: Q.askVisible(asked, P.stageOf(pres), pres.focus) ? asked!.question : null,
  // Decision 6: the worker's text the question shows under it, as the card draws it (every line, marked).
  questionQuote: Q.askVisible(asked, P.stageOf(pres), pres.focus) ? quoteLines(asked!.quote).map((l) => l.text).join("\n") : null,
  // The line under the question (2026-11-17: "Got it…" while a spoken answer is transcribed, then back to waiting).
  questionPill: Q.askVisible(asked, P.stageOf(pres), pres.focus) ? Q.askPill(asked!, false) : null,
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
  // B4: the answer card on screen, as its blocks give it in words (answer.ts detailsText), the kind of block,
  // and whether it opens in full (Read more): what renderResult draws from the same frame.
  answerKind: P.stageOf(pres) === "result" && resultData?.run_id === pres.card.runId ? resultData!.details?.kind ?? null : null,
  answerText: P.stageOf(pres) === "result" && resultData?.run_id === pres.card.runId ? detailsText(resultData!.details) : null,
  answerLong: P.stageOf(pres) === "result" && resultData?.run_id === pres.card.runId ? needsReader(resultData!.summary, resultData!.details) : null,
  // The answer card's footer, as renderResult draws it (FD-13: never the provider's name).
  // The answer card's one line (F6/F7: "Stopped “…”").
  answerSummary: P.stageOf(pres) === "result" && resultData?.run_id === pres.card.runId ? resultData!.summary ?? null : null,
  answerBy: P.stageOf(pres) === "result" && resultData?.run_id === pres.card.runId ? byline(resultData!.agent) : null,
  // What main.ts would ask to bring forward by itself once the card in front fades (P.promotion, F2).
  promoted: P.promotion(P.tick(pres, Number.MAX_SAFE_INTEGER).p),
  lost,
  broken: [...broken],
  acks,
}));
