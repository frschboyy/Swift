# Performance (October 2026)

Measured from the owner's own logs (`swift.log` and `interactions.jsonl`, 2026-10-27 to 2026-10-28) on the development laptop: 8 cores, about 24 GB RAM, no dedicated GPU.

The owner's Swift wasn't running during this audit, so idle CPU and memory over a long session could not be sampled live. Those are unverified.

## Startup and coming back

| Measure | Median | p90 | Max | Source |
|---|---|---|---|---|
| Backend ready (`backend_ms`) | 5.6 s | 9.9 s | 10.2 s | "overlay ready" |
| Speech model load (`load_s`) | 16.4 s | 23.7 s | 25.7 s | "speech model loaded" |
| Speech model memory (`private_mb_delta`) | 734 MB | 737 MB | 741 MB | same |
| Speech model primed on return | 876 ms | 1.2 s | 12.8 s | "speech model primed" |
| Unlock or input → listening again | 1.25 s | 2.2 s | 4.7 s | "listening again" |
| Microphone reopened | 0.8 s | – | – | one sample |
| Claude CLI connect (spare or cold) | 2.8 s | 6.4 s | 28.4 s | "claude ready" (194 samples) |

**In plain words:** wake listening needs the speech model, which takes about 16 s after start (up to 26 s). At startup, the spare CLI connects in parallel and took 11.5 s at 06:36 on 2026-10-28. So the first minute after starting is slow (B-05).

## Hearing

| Measure | Median | p90 | Max |
|---|---|---|---|
| STT, per request (`stt_ms`) | 737 ms | 1.66 s | 10.2 s |
| STT, reply window (`follow-up heard`) | 476 ms | 924 ms | 2.6 s |
| Wake transcriptions timed out (20 s) | 2 in two days, both after about 30 min of quiet |

**Open-microphone load:** wake listening transcribes every utterance it hears. In one 5-minute window with a TV on, while the owner was idle-away (06:30), that was 26 utterances. Each is about 0.5–1 s of CPU, so roughly 5–10% of one core with speech in the room and close to nothing in silence. This is an estimate, not a measurement.

## Lanes, from request to answer (`interaction_ms`)

`interaction_ms` counts from when the request starts. For the hotkey (`voice`) that includes speaking: about 3 s of audio. For wake and reply-window requests, timing starts after capture.

| Lane, source | n | Total | Of which model (`duration_ms`) | Swift and CLI around the model (`run_ms − duration_ms`) |
|---|---|---|---|---|
| Local, reply window | 13 | 0 ms (answered at once) | – | – |
| Local, hotkey | 10 | 3.2 s (3.0 s is speaking) | – | about 0.1 s |
| Fast, hotkey or wake | 7 | 0–2.8 s | – | – |
| Agent, reply window | 64 | 7.9 s | 5.3 s | 1.9 s |
| Agent, wake | 15 | 11.3 s | 9.7 s | 1.3 s |
| Agent, hotkey | 23 | 17.1 s | 9.7 s | 2.5 s (plus 4.3 s of speaking) |
| Workflow, wake | 33 | 9.8 s | 7.0 s | 2.0 s |
| Workflow, hotkey | 35 | 19.0 s | 10.3 s | 2.0 s (plus 5.9 s of speaking) |

**Where the time goes:** for agent and workflow requests the model is 65–85% of the time. Swift's own routing is in milliseconds, and the light lane measured 1.8–2.5 s warm earlier. The rest, 1.3–2.5 s, is the CLI around the model: `set_model`, the MCP handshake, and the first and last stream events. Starting a run on the spare saves the 2.8 s median connect.

## Changes in this audit that affect time

- **A-07** (each run kills only its own CLI): a concurrent run no longer crashes and has to be asked again. That was 8 s lost at 01:52 on 2026-10-28.
- **A-11** (the same request again keeps the one running): no second 8–17 s run and second card.
- **A-03:** a fetch of an address the model made up is refused at once. The model searches instead, which can add a step (about 1–2 s) to research that guessed URLs.

No speed-up was claimed without a measurement, and none was made to timing-sensitive code.

## Opportunities, measured but not built

1. **Start the spare after the speech model at startup** (it already waits on return). At 06:36 both started together: the CLI took 11.5 s and the model 16.4 s.
2. **Keep the spare through a short lock.** Today it is released after a while away; reconnecting costs 3–8 s.
3. **Local answers for thread questions** ("what did I just ask?") instead of the light model.
4. **The web lane** (Phase I) for weather and news: today 10–17 s on the agent.
