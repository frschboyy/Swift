---
name: calendar-event
description: Add an event to the user's Google Calendar after they have seen it and approved it. Use when the user asks to add, put or schedule something in their calendar.
license: MIT
metadata:
  swift-manifest: swift.yaml
---

# Add a calendar event

1. Work out the event from the request:
   - a short title, in the user's words ("Lunch with Ada", "Dentist");
   - the start, as a local date and time (`2026-10-30T12:30`), or just a date (`2026-10-30`) for an all-day event. Today's date and the time zone are given below the playbook; resolve "tomorrow", "next Friday" and "at noon" from them;
   - the end, only if the request gives one or a length ("for two hours"); otherwise Swift makes it an hour;
   - a location, only if the request gives one.
   If the date or the time can't be worked out from the request, stop and ask; don't guess.
2. Create it with `create_calendar_event`. Swift shows the user the event on a card and adds it only if they approve.
3. If they reject it or don't answer, it wasn't added: say so, and don't try again another way. Otherwise answer with one sentence: what was added, and when.
