// When the overlay re-asserts "on top" without moving (owner check, 2026-11-09: after "Hey Swift"
// the overlay showed behind other windows; only a hotkey ever raised it). Windows orders topmost
// windows among themselves, so another app made topmost later can cover Swift until it raises again.
import type { Inbound } from "./protocol";

/** Whether this message means Swift is about to need the owner's eyes: heard, a card, a question. */
export function wantsRaise(msg: Inbound): boolean {
  switch (msg.type) {
    case "heard":
    case "confirm.request":
      return true;
    case "ask":
      return msg.data.open === true;
    default:
      return false;
  }
}
