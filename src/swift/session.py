"""Interaction state machine (PLAN.md §1, §3).

The backend is authoritative: the overlay only renders the ``state`` and
content messages sent from here. One interaction runs at a time:

    idle -> listening -> transcribing -> working <-> confirm -> result | error

``result`` and ``error`` count as at rest: a new interaction may start from
them, and the overlay fades the card on its own timer.

Push-to-talk is ignored while an interaction runs, except in ``confirm``: then
the owner may answer the card by voice (ADR-007 §8). The state stays
``confirm``; ``confirm.voice`` messages tell the card it is listening,
transcribing, or didn't understand. "approve"/"reject" answer the card like a
click, "stop"/"cancel" cancel the run like Esc, anything else leaves it open.

A request to Claude within ``followup_s`` of the previous answer carries that
exchange (request, answer, approved actions) as context, so "now commit it"
works although every run is a fresh Claude Code process (ADR-007 §9). Only
one exchange is kept; an error, a cancelled run or "new topic" clears it.

Push-to-talk (``ptt`` down/up) records from the microphone, transcribes
locally and routes the transcript (ADR-007): commands to Swift ("stop",
"repeat that") and time/date are handled here; everything else goes to the
configured executor with a demand estimate that picks its starting model. ``debug.run``
plays a scripted interaction (fake mic level, canned transcript) through
``MockExecutor`` instead.

The owner talks to Swift; executors are providers working for it (ADR-008).
Every ``state``/``step``/``confirm.request``/``result``/``error`` sent for a run
carries ``agent`` (the provider's id and name, from ``ProviderInfo``) so the
overlay can say "Claude Code is reading" without knowing any provider. Results
Swift produced itself carry ``agent: null``. Requests start on the first
available provider (``Providers``); a skipped one is reported as a hand-off step.
Called by an agent's name ("hey Claude"), Swift says who it is, at most once an hour.
"""

from __future__ import annotations

import asyncio
import contextlib
import math
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import datetime
from itertools import count
from pathlib import Path
from typing import Any

from loguru import logger

from swift import identity
from swift.audio.recorder import MAX_SECONDS, SAMPLE_RATE, MicError, Recorder, save_wav
from swift.executors.base import SWIFT, ExecResult, Executor, ExecutorUnavailable
from swift.executors.mock import MockExecutor
from swift.executors.providers import Providers, Started, provider_of
from swift.ipc.protocol import Message, now_ms, outbound
from swift.routing import Route
from swift.routing import route as default_router
from swift.routing.demand import estimate
from swift.routing.local import LocalOpener, OpenTarget
from swift.routing.rules import strip_wake
from swift.stt.transcriber import SttUnavailable, Transcriber

Send = Callable[[Message], Awaitable[None]]
OnFinish = Callable[[dict[str, Any]], None]

DEMO_TRANSCRIPTS = {
    "happy": "Find the open to-dos in this project.",
    "confirm": "Add a next steps section to my notes.",
    "error": "Check which packages are out of date.",
    "long": "Run the tests and tell me how it went.",
}

MIN_SPEECH_S = 0.3
# After saying "No, I'm Swift" once, don't say it again for this long.
CLARIFY_EVERY_S = 3600.0

HELP_TEXT = (
    "Hold the hotkey and ask for anything in your project: questions, changes, commands. "
    "Say \u201cstop\u201d or press Esc to cancel, \u201crepeat that\u201d to see the last answer, "
    "and \u201cuse opus\u201d at the start to ask for the strongest model."
)
# The mic stays open this long after the hotkey is released: people let go
# while still saying the last word.
TAIL_S = 0.3
# A request this soon after the previous Claude answer carries that exchange as context.
FOLLOWUP_S = 300.0
CONFIRM_VOICE_HINT = "Say “approve” or “reject”, or click."


@dataclass(frozen=True)
class Exchange:
    """The previous request to the executor, kept for one follow-up (ADR-007 §9)."""

    id: str
    request: str
    answer: str
    approved: tuple[str, ...]
    at: float

    def as_context(self, now: float) -> str:
        lines = [
            f"[Context: the previous voice request, {int(now - self.at)} s ago. "
            "Use it only if the current request refers to it.]",
            f"Previous request: {_clip(self.request, 300)}",
            f"Previous answer: {_clip(self.answer, 800)}",
        ]
        if self.approved:
            lines.append("Actions the user approved: " + "; ".join(_clip(a, 120) for a in self.approved[-5:]))
        return "\n".join(lines) + "\n\n[Current request]\n"


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class UserFacingError(Exception):
    """A failure the owner can act on: shown as an error card with a hint."""

    def __init__(self, code: str, message: str, hint: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


class Session:
    def __init__(
        self,
        send: Send,
        executor: Executor,
        *,
        debug_executor: MockExecutor | None = None,
        recorder: Recorder | None = None,
        transcriber: Transcriber | None = None,
        ptt_label: str = "the push-to-talk hotkey",
        demo_speed: float = 1.0,
        max_record_s: float = MAX_SECONDS,
        tail_s: float = TAIL_S,
        audio_dir: Path | None = None,
        on_finish: OnFinish | None = None,
        router: Callable[[str], Route] | None = default_router,
        opener: LocalOpener | None = None,
        followup_s: float = FOLLOWUP_S,
        fallbacks: tuple[Executor, ...] = (),
    ) -> None:
        self._send = send
        self.executor = executor
        # The default provider first, then the ones tried when it's unavailable.
        self.providers = Providers([executor, *fallbacks])
        self._clarified_at: float | None = None
        self._note: str | None = None
        self.debug_executor = debug_executor
        self.recorder = recorder
        self.transcriber = transcriber
        self.ptt_label = ptt_label
        self.demo_speed = demo_speed
        self.max_record_s = max_record_s
        self.tail_s = tail_s
        # Debug only: every recording is saved here as <interaction id>.wav.
        self.audio_dir = audio_dir
        self.on_finish = on_finish
        # None sends every transcript to the executor unchanged (tests, demos).
        self.router = router
        # Resolves and starts "open ..." requests; None sends them to the executor.
        self.opener = opener
        # 0 turns follow-up context off.
        self.followup_s = followup_s
        self._last_exchange: Exchange | None = None
        # The last answer, with the agent that produced it (None: Swift), for "repeat that".
        self._last_result: tuple[str, ExecResult, dict[str, str] | None] | None = None
        self._local_ids = count(1)
        self._released: asyncio.Event | None = None
        self.state = "idle"
        self._task: asyncio.Task[None] | None = None
        self._active: tuple[Executor, str] | None = None
        self._confirm_ids: set[str] = set()
        # Confirm card titles by request id, and the ones approved in this run.
        self._confirm_titles: dict[str, str] = {}
        self._approved: list[str] = []
        self._confirm_voice: asyncio.Task[None] | None = None
        self._record: dict[str, Any] | None = None
        self._run_started: float | None = None

    @property
    def busy(self) -> bool:
        """True while an interaction task is running, even before its first state change."""
        return self._task is not None and not self._task.done()

    # ---- inbound -----------------------------------------------------------

    async def handle(self, msg: Message) -> None:
        match msg.type:
            case "debug.run":
                await self._start_demo(msg.data["scenario"])
            case "debug.ask":
                await self._start_text(msg.data["text"])
            case "ready":
                logger.info("overlay ready", startup_ms=msg.data["startup_ms"], backend_ms=msg.data.get("backend_ms"))
            case "cancel":
                await self.cancel()
            case "confirm.reply":
                await self._confirm_reply(msg.data["request_id"], msg.data["decision"] == "approve")
            case "ptt" if msg.data["state"] == "down":
                await self._start_voice()
            case "ptt":
                if self._released is not None:
                    self._released.set()
            case _:
                logger.warning("unhandled message", kind=msg.type)

    async def cancel(self) -> None:
        if self._task is None or self._task.done():
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass

    async def close(self) -> None:
        await self.cancel()

    # ---- interaction -------------------------------------------------------

    async def _set_state(self, state: str, **extra: Any) -> None:
        self.state = state
        await self._send(outbound("state", state=state, **extra))

    async def _start_demo(self, scenario: str) -> None:
        if self.debug_executor is None:
            logger.warning("debug.run ignored: debug mode is off")
            return
        if self.busy:
            logger.info("debug.run ignored: busy", state=self.state)
            return
        transcript = DEMO_TRANSCRIPTS[scenario]
        record: dict[str, Any] = {"source": "debug.run", "executor": "mock", "scenario": scenario}

        async def capture(rec: dict[str, Any]) -> str:
            await self._set_state("listening")
            await self._fake_listening(transcript)
            await self._set_state("transcribing")
            t0 = time.monotonic()
            await asyncio.sleep(0.6 * self.demo_speed)
            rec["stt_ms"] = int((time.monotonic() - t0) * 1000)
            return transcript

        async def start(text: str) -> str:
            assert self.debug_executor is not None
            return await self.debug_executor.start(text, scenario=scenario)

        self._task = asyncio.create_task(self._interaction(record, capture, self.debug_executor, start))

    async def _start_text(self, text: str) -> None:
        """Debug mode only: run the configured executor on typed text."""
        if self.debug_executor is None:
            logger.warning("debug.ask ignored: debug mode is off")
            return
        if self.busy or not text.strip():
            return
        record: dict[str, Any] = {"executor": getattr(self.executor, "name", "?"), "source": "debug.ask"}

        async def capture(rec: dict[str, Any]) -> str:
            return text.strip()

        self._task = asyncio.create_task(self._interaction(record, capture, self.executor, self.executor.start))

    async def _start_voice(self) -> None:
        if self.recorder is None or self.transcriber is None:
            logger.warning("ptt ignored: no recorder or transcriber")
            return
        if self.busy:
            open_request = self._open_confirm()
            if open_request is not None and (self._confirm_voice is None or self._confirm_voice.done()):
                self._released = asyncio.Event()
                self._confirm_voice = asyncio.create_task(self._answer_by_voice(open_request))
            else:
                logger.info("ptt ignored: busy", state=self.state)
            return
        # Created before the task so a quick release can't be missed.
        self._released = asyncio.Event()
        record: dict[str, Any] = {"source": "voice", "executor": getattr(self.executor, "name", "?")}
        self._task = asyncio.create_task(
            self._interaction(record, self._capture_voice, self.executor, self.executor.start)
        )

    async def _capture_voice(
        self, record: dict[str, Any], phase: Callable[[str], Awaitable[None]] | None = None
    ) -> str | None:
        """Record while the hotkey is held, then transcribe. None means 'nothing to do'.

        ``phase`` reports listening / transcribing / idle (default: the interaction state).
        """
        assert self.recorder is not None and self.transcriber is not None and self._released is not None
        phase = phase or self._set_state
        await phase("listening")
        levels: asyncio.Queue[float] = asyncio.Queue()
        try:
            self.recorder.start(levels.put_nowait)
        except MicError as exc:
            raise UserFacingError("mic_unavailable", str(exc), exc.hint) from None

        async def forward_levels() -> None:
            while True:
                await self._send(outbound("level", rms=round(await levels.get(), 3)))

        forwarder = asyncio.create_task(forward_levels())
        try:
            try:
                await asyncio.wait_for(self._released.wait(), self.max_record_s)
                await asyncio.sleep(self.tail_s)
            except TimeoutError:
                logger.info("recording reached the time limit")
        finally:
            forwarder.cancel()
            audio = self.recorder.stop()

        record["audio_s"] = round(len(audio) / SAMPLE_RATE, 2)
        record["first_audio_ms"] = getattr(self.recorder, "first_audio_ms", None)
        record["preroll_ms"] = getattr(self.recorder, "preroll_ms", None)
        if self.audio_dir is not None and len(audio):
            path = self.audio_dir / f"{record['id']}.wav"
            try:
                save_wav(path, audio)
                record["audio_file"] = str(path)
            except OSError as exc:
                logger.warning("could not save the recording", error=str(exc))
        if record["audio_s"] < MIN_SPEECH_S:
            record["reason"] = "too_short"
            await phase("idle")
            return None

        await phase("transcribing")
        try:
            result = await self.transcriber.transcribe(audio)
        except SttUnavailable as exc:
            raise UserFacingError("stt_unavailable", str(exc), exc.hint) from None
        record["stt_ms"] = result.stt_ms
        if result.peak_db is not None:
            record["peak_db"] = result.peak_db
        if result.raw_text is not None:
            record["transcript_raw"] = result.raw_text
        if not result.text:
            raise UserFacingError(
                "no_speech",
                "I didn't catch that.",
                f"Hold {self.ptt_label} while you speak, and release when you're done.",
            )
        return result.text

    async def _interaction(
        self,
        record: dict[str, Any],
        capture: Callable[[dict[str, Any]], Awaitable[str | None]],
        executor: Executor,
        start: Callable[[str], Awaitable[str]],
    ) -> None:
        record = {
            "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "id": uuid.uuid4().hex,
            **record,
            "steps": [],
            "approvals": [],
        }
        self._record = record
        started = time.monotonic()
        try:
            transcript = await capture(record)
            if transcript is None:
                record["status"] = "cancelled"
                return
            record["transcript"] = transcript
            await self._send(outbound("transcript", text=transcript, final=True))

            routed = self.router is not None and record.get("source") in ("voice", "debug.ask")
            decision = self.router(transcript) if routed else None  # type: ignore[misc]
            target: OpenTarget | None = None
            if decision is not None and decision.action == "open":
                target = self.opener.resolve(decision) if self.opener is not None else None
                if target is None:  # not a configured name: Claude Code decides
                    request = strip_wake(decision.text) or decision.text
                    decision = replace(
                        decision, route="claude", action=None, target=None, app=None, text=request,
                        demand=estimate(request) or "standard",
                    )
            if decision is not None:
                record["route"] = decision.route
                if decision.addressed_as:
                    record["addressed_as"] = decision.addressed_as
                    self._note = self._clarify(decision.addressed_as)
                if decision.route != "claude":
                    record["action"] = decision.action
                    if target is not None:
                        record["target"] = target.name
                    await self._handle_here(decision, record, target)
                    return
                record["demand"] = decision.demand
                if decision.override:
                    record["override"] = decision.override

            try:
                if decision is not None:
                    launch = await self.providers.start(
                        self._with_context(decision.text, record), demand=decision.demand, override=decision.override
                    )
                else:
                    launch = Started(executor, await start(transcript))
            except ExecutorUnavailable as exc:
                raise UserFacingError("executor_unavailable", str(exc), exc.hint) from None
            result = await self._run(launch, record)
            await self._finish(result, record)
            if decision is not None:
                self._remember(record, decision.text, result)
        except asyncio.CancelledError:
            record["status"] = "cancelled"
            if self._active is not None:
                self._last_exchange = None
            if self._active is not None:
                active_executor, run_id = self._active
                await active_executor.cancel(run_id)
                await self._send_result(run_id, ExecResult("cancelled", "Cancelled."), self._agent())
            else:
                await self._set_state("idle")
            raise
        except UserFacingError as exc:
            record["status"] = "error"
            record["error"] = exc.code
            self._last_exchange = None
            await self._set_state("error")
            await self._send(outbound("error", code=exc.code, message=exc.message, hint=exc.hint))
        except Exception:
            logger.exception("interaction failed")
            record["status"] = "error"
            self._last_exchange = None
            await self._set_state("error")
            await self._send(
                outbound("error", code="internal", message="Swift hit an internal error.", hint="Details are in swift.log.")
            )
        finally:
            voice = self._confirm_voice
            if voice is not None and not voice.done() and voice is not asyncio.current_task():
                voice.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await voice
            self._confirm_voice = None
            self._note = None
            if self._run_started is not None and "run_ms" not in record:
                record["run_ms"] = int((time.monotonic() - self._run_started) * 1000)
            self._run_started = None
            self._active = None
            self._record = None
            self._released = None
            self._confirm_ids.clear()
            self._confirm_titles.clear()
            self._approved = []
            record["interaction_ms"] = int((time.monotonic() - started) * 1000)
            record.setdefault("status", "error")
            unanswered = "cancelled" if record["status"] == "cancelled" else "no_answer"
            for approval in record["approvals"]:
                approval.setdefault("decision", unanswered)
            if self.on_finish is not None:
                self.on_finish(record)

    async def _handle_here(self, decision: Route, record: dict[str, Any], target: OpenTarget | None = None) -> None:
        """Commands and questions Swift answers itself: no executor, no network."""
        action = decision.action
        if action == "open" and target is not None and self.opener is not None:
            try:
                await asyncio.to_thread(self.opener.launch, target)
            except OSError as exc:
                logger.warning("open failed", target=target.name, error=str(exc))
                record["status"] = "error"
                record["error"] = "open_failed"
                await self._set_state("error")
                await self._send(
                    outbound("error", code="open_failed", message=f"Couldn't open {target.name}.", hint="Check the path in config.yaml's local section.")
                )
                return
            record["status"] = "done"
            await self._send_result(f"local-{next(self._local_ids)}", ExecResult("done", f"Opened {target.name.title()}."))
            return
        if action in ("stop", "cancel", "mute"):
            record["status"] = "cancelled"
            await self._set_state("idle")
            return
        if action == "new_topic":
            self._last_exchange = None
        if action == "repeat" and self._last_result is not None:
            record["status"] = "done"
            await self._send_result(*self._last_result)
            return
        if action == "identity":
            # The answer is the clarification itself: no note under it.
            answer = self._note or (
                identity.clarification(decision.addressed_as, self.providers.agents())
                if decision.addressed_as else identity.introduction(self.providers.agents())
            )
            self._note = None
            record["status"] = "done"
            await self._send_result(f"local-{next(self._local_ids)}", ExecResult("done", answer))
            return
        now = datetime.now()
        answers = {
            "time": f"It's {now.strftime('%H:%M')}.",
            "date": f"It's {now.strftime('%A')}, {now.day} {now.strftime('%B %Y')}.",
            "help": HELP_TEXT,
            "repeat": "There's nothing to repeat yet.",
            "approve": "There's nothing waiting for approval.",
            "reject": "There's nothing waiting for approval.",
            "new_topic": "Okay, starting fresh: the next request won't see the last one.",
        }
        record["status"] = "done"
        await self._send_result(f"local-{next(self._local_ids)}", ExecResult("done", answers.get(action or "", "Done.")))

    async def _fake_listening(self, transcript: str) -> None:
        """Synthesize a speech-like mic level and a growing partial transcript."""
        words = transcript.split()
        frames = max(1, int(1.8 * 30 * min(self.demo_speed, 1.0))) if self.demo_speed else 1
        for i in range(frames):
            phase = i / 30
            rms = 0.15 + 0.55 * abs(math.sin(phase * 7.0)) * (0.6 + 0.4 * math.sin(phase * 2.3))
            await self._send(outbound("level", rms=round(max(0.0, min(1.0, rms)), 3)))
            if i % 6 == 5:
                shown = words[: min(len(words), (i + 1) // 6 * max(1, len(words) // 8))]
                await self._send(outbound("transcript", text=" ".join(shown), final=False))
            await asyncio.sleep(self.demo_speed / 30)

    def _agent(self) -> dict[str, str] | None:
        """The provider of the active run as the overlay's ``agent``; None when it is Swift itself."""
        if self._active is None:
            return None
        provider = provider_of(self._active[0])
        return None if provider.is_swift else provider.as_agent()

    def _clarify(self, called: str) -> str | None:
        """"No, I'm Swift." for being called by an agent's name; None if said within the last hour."""
        now = time.monotonic()
        if self._clarified_at is not None and now - self._clarified_at < CLARIFY_EVERY_S:
            return None
        self._clarified_at = now
        return identity.clarification(called, self.providers.agents())

    async def _run(self, started: Started, record: dict[str, Any]) -> ExecResult:
        executor, run_id = started.executor, started.run_id
        self._active = (executor, run_id)
        provider = started.provider
        agent = self._agent()
        record["provider"] = provider.id
        if started.skipped:
            record["skipped"] = [p.id for p, _ in started.skipped]
        await self._set_state("working", run_id=run_id, agent=agent)
        t0 = self._run_started = time.monotonic()
        for skipped, _ in started.skipped:
            # Swift's own step: who couldn't take the request and who did.
            await self._send(
                outbound(
                    "step", run_id=run_id, text=f"{skipped.name} isn't available, so {provider.name} is taking this",
                    kind="handoff", ts=now_ms(), activity="starting", agent=SWIFT.as_agent(), subagent=False,
                )
            )
        async for event in executor.events(run_id):
            t_ms = int((time.monotonic() - t0) * 1000)
            if event.type == "step":
                record["steps"].append({"t_ms": t_ms, "text": event.text, "activity": event.activity})
                await self._send(
                    outbound(
                        "step", run_id=run_id, text=event.text, kind="tool", ts=event.ts,
                        activity=event.activity, agent=agent, subagent=event.subagent,
                    )
                )
            elif event.type == "confirm" and event.request_id is not None:
                self._confirm_ids.add(event.request_id)
                self._confirm_titles[event.request_id] = event.text
                record["approvals"].append({"tool": event.tool, "request_id": event.request_id, "asked_ms": t_ms})
                await self._set_state("confirm", run_id=run_id, agent=agent)
                await self._send(
                    outbound(
                        "confirm.request",
                        request_id=event.request_id,
                        run_id=run_id,
                        title=event.text,
                        detail=event.detail or "",
                        tool=event.tool or "",
                        agent=agent,
                    )
                )
        result = await executor.result(run_id)
        record["run_ms"] = int((time.monotonic() - t0) * 1000)
        return result

    async def _confirm_reply(self, request_id: str, approve: bool, source: str = "click") -> None:
        if self._active is None or request_id not in self._confirm_ids:
            logger.warning("confirm.reply for an unknown request ignored")
            return
        self._confirm_ids.discard(request_id)
        executor, run_id = self._active
        if approve and request_id in self._confirm_titles:
            self._approved.append(self._confirm_titles[request_id])
        if (entry := self._approval(request_id)) is not None:
            entry["decision"] = "approve" if approve else "reject"
            entry["answered_ms"] = int((time.monotonic() - self._run_started) * 1000) if self._run_started else None
            entry["source"] = source
        await executor.reply(request_id, approve)
        if approve:
            await self._set_state("working", run_id=run_id, agent=self._agent())

    def _approval(self, request_id: str) -> dict[str, Any] | None:
        if self._record is None:
            return None
        return next((c for c in self._record["approvals"] if c["request_id"] == request_id), None)

    def _open_confirm(self) -> str | None:
        """The request id of the confirm card on screen, if any."""
        if self.state != "confirm" or self._record is None:
            return None
        pending = [c["request_id"] for c in self._record["approvals"] if c["request_id"] in self._confirm_ids]
        return pending[-1] if pending else None

    async def _answer_by_voice(self, request_id: str) -> None:
        """Push-to-talk on an open confirm card: approve, reject, or stop the run."""
        entry = self._approval(request_id)
        assert entry is not None and self._record is not None
        heard: list[str] = entry.setdefault("heard", [])
        capture: dict[str, Any] = {"id": f"{self._record['id']}-c{len(heard) + 1}"}

        async def phase(name: str, text: str = "") -> None:
            await self._send(outbound("confirm.voice", request_id=request_id, phase=name, text=text))

        try:
            text = await self._capture_voice(capture, phase)
        except UserFacingError as exc:
            await phase("hint", f"{exc.message} {CONFIRM_VOICE_HINT}")
            return
        if text is None:
            return
        heard.append(text)
        if request_id not in self._confirm_ids:  # answered by click meanwhile
            return
        decision = (self.router or default_router)(text)
        if decision.route == "control" and decision.action in ("approve", "reject"):
            logger.info("confirm answered by voice", decision=decision.action)
            await self._confirm_reply(request_id, decision.action == "approve", source="voice")
        elif decision.route == "control" and decision.action in ("stop", "cancel", "mute"):
            entry["source"] = "voice"
            if self._task is not None:
                self._task.cancel()  # like Esc; the interaction cleans up
        else:
            await phase("hint", f"Heard “{_clip(text, 60)}”. {CONFIRM_VOICE_HINT}")

    def _with_context(self, request: str, record: dict[str, Any]) -> str:
        """Prepend the previous exchange when it is recent enough (ADR-007 §9)."""
        last, now = self._last_exchange, time.monotonic()
        if last is None or self.followup_s <= 0 or now - last.at > self.followup_s:
            return request
        record["context"] = {"previous": last.id, "age_s": int(now - last.at)}
        return last.as_context(now) + request

    def _remember(self, record: dict[str, Any], request: str, result: ExecResult) -> None:
        if result.status in ("done", "rejected"):
            self._last_exchange = Exchange(record["id"], request, result.summary, tuple(self._approved), time.monotonic())
        else:
            self._last_exchange = None

    async def _finish(self, result: ExecResult, record: dict[str, Any]) -> None:
        record["status"] = result.status
        record.update(result.meta)
        assert self._active is not None
        await self._send_result(self._active[1], result, self._agent())

    async def _send_result(self, run_id: str, result: ExecResult, agent: dict[str, str] | None = None) -> None:
        """Swift presents the outcome; ``agent`` says who did the work (None: Swift itself)."""
        if result.status == "error":
            hint = provider_of(self._active[0]).error_hint if self._active else SWIFT.error_hint
            await self._set_state("error", run_id=run_id, agent=agent)
            await self._send(
                outbound("error", code="executor_failed", message=result.summary, hint=hint, agent=agent)
            )
            return
        if result.status == "done":
            self._last_result = (run_id, result, agent)
        note, self._note = self._note, None
        await self._set_state("result", run_id=run_id, agent=agent)
        await self._send(
            outbound(
                "result", run_id=run_id, status=result.status, summary=result.summary, details=result.details,
                agent=agent, note=note,
            )
        )
