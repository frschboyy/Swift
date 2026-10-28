from test_dialogue import *

async def test_dbg() -> None:
    session, out, records, agent, stt = make(Asker, wake_end_silence_s=0.05)
    run_id = await started(session, out, agent, stt, "Hey Swift, plan the trip and ask me where")
    await until(lambda: session._answer_task is not None and session.recorder.recording)
    stt.text = "Paris"
    rec = session.recorder
    for level in (0.9, 0.9, 0.9):
        rec.on_level(level); await asyncio.sleep(0.01)
    print("LV", [m.data for m in out.messages if m.type == "level"][:5], session._ptt_held, session.endpoint)
    for _ in range(20):
        rec.on_level(0.0); await asyncio.sleep(0.01)
    print("N", len([m for m in out.messages if m.type == "level"])); print("REC", rec.recording, session._released, session._answer_task)
