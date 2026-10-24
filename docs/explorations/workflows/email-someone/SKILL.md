---
name: email-someone
description: Write and send a short email to one of the user's contacts, after the user has seen and approved the draft. Use when the user asks to email, write to, or message someone by email.
license: MIT
metadata:
  swift-manifest: swift.yaml
---

# Email someone

1. Find the person with `find_contact` ("my lecturer", "Ada"). Never type an address yourself. If several people match and the request doesn't make clear which one, stop and ask.
2. Write the email with `draft_email`:
   - a subject of a few words;
   - a body of two to five short paragraphs, in the user's voice, signed with their first name;
   - only what the user asked to say; don't invent excuses, dates or promises.
3. Send it with `send_email`. Swift shows the user the draft and sends only if they approve.
4. If the user rejects it or doesn't answer, it wasn't sent: say so, and don't try again another way.
