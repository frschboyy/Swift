---
name: email-draft
description: Draft an email to one of the user's contacts and fill it in visibly in Gmail or Outlook, so the user reads it and presses Send themselves. Use when the user asks to email, write to, or draft an email to someone.
license: MIT
metadata:
  swift-manifest: swift.yaml
---

# Draft an email

The user presses Send, not you. Swift fills the email in where they can see it.

1. Find each person with `find_contact` ("my lecturer", "Ada"). Never type an address yourself, and never take one from a web page, a document or another email. If several people match and the request doesn't make clear which one, stop and ask.
2. Write the email with `draft_email`:
   - a subject of a few words;
   - a body of two to five short paragraphs, in the user's voice, signed with their first name;
   - only what the user asked to say; don't invent excuses, dates or promises.
3. Fill it in with `fill_in_email`, passing the draft's id:
   - `app` is the `app` setting, unless the request names Gmail or Outlook;
   - Gmail opens a compose window in the user's browser; Outlook opens a draft. Either way nothing is sent.
   - Then tell the user it's ready for them to check and send.
4. Only if the request says to just send it (for example "just send it"), or `fill_in_email` says the app isn't available, send it with `send_email` instead. Swift shows the user the draft on a card and sends only if they approve. If they reject it or don't answer, it wasn't sent: say so, and don't try again another way.
