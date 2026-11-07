# Voice and requests side by side: what check 185 found (2026-11-07)

The owner ran check 185 ("Is it going to rain this afternoon?") and reported six problems, and asked for causes and architecture rather than workarounds. Evidence: `swift.log` and `interactions.jsonl` for 17:04–17:20, and the saved clips replayed through the speech model. The branch is `worktree-voice-reliability`. **None of this has run on the real PC yet.**

## What was proven

| # | The owner saw | Cause | Evidence | Fix | Label |
|---|---|---|---|---|---|
| 1 | "Run a command" with a terminal command, to ask about rain | The agent had no way to read the weather except the shell, and every shell command asks. A web fetch runs off the PC, so it can't tell where the PC is | Every rain request used `curl wttr.in`. Asked another way it said "I don't know your city" | A `weather` tool with a fixed address and no arguments, so no card; the agent is told not to use the shell to find things out; a command's card says "Run a command on your PC" | root for the weather; partial for commands in general (below) |
| 2 | "Hey Swift" not registering | There is no wake-word detector. Every utterance goes through full speech recognition, then a text match, and the model often writes "hey" as something else | Replay: "He swift.", "K Swift.", "He's sweet.", "Hail Swift." were 4 of today's 5 saved misses | The matcher takes what the model writes, and a near miss makes the next try easier for 6 s | partial; a real detector would replace it (below) |
| 3 | Three of the same request | The repeat check ran only when the words were known before starting. The hotkey and a bare wake phrase only know them after the capture | 17:06:27 kept one; 17:07:39 by the hotkey started another | One check at the point every request's words are known; asking again replaces the unfinished one in the stack | root |
| 4 | The stack moving by itself | Its side followed the main window, and it remembered wherever it had been dragged | `panes::side`; `overlay.json` held a dragged place | Bottom right always, no drag; bottom left only with the main window in that corner | root |
| 5 | A second request not registering | Two separate causes: a bare "hey Swift" during a request did nothing at all, and a new request said on a card was taken as a change to that card | `_hear_busy` returned on no text. "research the history of tea" became "Changing it" on 3 weather cards, and the weather was never answered | A bare wake phrase opens a new request whatever is on screen. Plainly new requests run beside the card | root |
| 6 | Speech getting in the way | Partly confirmed: Swift ignores the microphone while it talks | `own_voice=12` in one five-minute window; other windows 0. Not the main cause of the misses in #2 | Replies are off; only "Hello" to a bare wake phrase | the owner's decision |

**Scored on saved clips** (the rule for confidence bars): of 305 clips, the matcher finds 64 before and 74 after. All 10 new ones are saved misses, and none is a false match. **The limit:** these clips hold little room chatter, because most speech that isn't for Swift is never saved, so false starts are not well measured. A false start alone only opens the microphone. With words after it, a forgiving match needs the name as said, and it starts a request whose actions still ask on cards. Approving, and changing a card, need the name itself, and tests hold that.

**Reviewed by someone other than the author** (`CLAUDE.md`), twice. The first round reproduced two critical faults: a capture that outlived a lock and started a request, and false titles on a command card. The second reproduced more false titles and a change to a card made on a name that wasn't said. All are fixed or designed out, with tests. The third state of the fixes was not reviewed again.

## What mature assistants do, and what it means here

Apple's account of ["Hey Siri"](https://machinelearning.apple.com/research/hey-siri) is the clearest public one:

- **A detector separate from speech recognition.** A small network scores short frames for the phrase's own sounds. It doesn't write words. Swift's approach writes words and then reads them, which is the root of #2.
- **Two stages.** A very cheap always-on stage wakes a larger check. Swift could use its existing recogniser as the second stage.
- **A second chance.** A near miss makes the system more sensitive for a few seconds, because people repeat themselves. Swift now does this, in text.
- **Personalisation.** Comparing against the owner's voice cuts other people's false starts.

Swift's Deck already has the property that matters for #5: more than one request at a time, each with its own state. What was missing was that the microphone's rules didn't match it. The rule now is that **saying Swift's name always opens a new turn**, whatever is on screen, and only words that point at the card change it.

## What this doesn't solve

- **The wake word is improved, not fixed.** The real fix is a dedicated detector (for example [sherpa-onnx keyword spotting](https://huggingface.co/openEuler/sherpa-kws), whose small models run on CPU and appear to take new phrases without retraining; unverified). It needs a new dependency and a model download, so it's the owner's call. Owner check 191's count should decide it.
- **Latency.** The text match still waits for the end of the utterance, except for the early look at the first 1.3 s.
- **Echo.** "Hello" can overlap the owner's first words. The capture ignores levels while it plays and takes it out of the words, but the audio is still mixed. Unverified on the real PC.
- **The weather tool tells wttr.in the PC's address,** as the `curl` did. It's a third-party service with no uptime promise.
- **Command cards still show the command,** because approving what you can't see is worse, and this is the part of your report that isn't solved. A title like "Read a page from wttr.in" was built and then deleted: two reviews in a row got a false one past its parser (a newline that ran a second command, an `&`), and a false statement on an approval card is worse than a dull one. A plain explanation of an arbitrary command would have to come from the worker's own words, which a card's facts must never do. What reduces these cards is giving the agent more tools that don't need a command, as with the weather.
- **Which requests count as new on a card is a word list.** Anything unclear stays a change, as it did before.
- **"Um what do I do?" and "Then you create new workflows."** The second looks like room speech picked up under the hotkey; the cause is unproven. Neither is addressed here.
