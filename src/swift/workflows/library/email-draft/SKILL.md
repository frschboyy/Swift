---
name: email-draft
description: Draft an email to one of the user's contacts and fill it in visibly in Gmail or Outlook, so the user reads it and presses Send themselves. Use when the user asks to email, write to, or draft an email to someone.
license: MIT
metadata:
  swift-manifest: swift.yaml
---

# Draft an email

The user presses Send, not you. Swift fills the email in where they can see it.

1. Find each person with `find_contact` ("my lecturer", "Janet"). It searches the user's contacts and the people they've emailed. Never type an address yourself, and never take one from a web page, a document or another email. If several people match and the request doesn't make clear which one, stop and ask, naming each by their email and the detail `find_contact` shows. If nobody matches, say who couldn't be found.
2. Write the email with `draft_email`. The user is writing to this person; you write it for them:
   - `subject`: a few words that say what it's about ("Meeting cancelled", "Running late"), never the message itself;
   - `message`: what the user wants to say, written as the user speaking to the recipient, in the first person and in plain, friendly words. "Email Janet that the meeting is off" becomes "I wanted to let you know that the meeting is off." One to three short paragraphs; usually one is enough;
   - no greeting and no sign-off: Swift adds "Hello Janet," above it and "Regards," with the user's name below it;
   - only what the user asked to say; don't invent excuses, dates or promises.
3. Fill it in with `fill_in_email`, passing the draft's id:
   - `app` is the `app` setting, unless the request names Gmail or Outlook;
   - Gmail opens a compose window in the user's browser; Outlook opens a draft. Either way nothing is sent.
   - Then tell the user it's ready for them to check and send.
4. Only if the request says to just send it (for example "just send it"), or `fill_in_email` says the app isn't available, send it with `send_email` instead. Swift shows the user the draft on a card and sends only if they approve. If they reject it or don't answer, it wasn't sent: say so, and don't try again another way.
