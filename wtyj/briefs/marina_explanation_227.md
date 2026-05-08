# EXPLANATION 227 — Decision-first escalation summary

## In one sentence
When the AI agent escalates a conversation to a human, the system now produces a short structured briefing telling the operator who the customer is, what they want, what choice the operator has to make, and a list of concrete buttons they can click — instead of leaving the operator to read the whole conversation and guess.

## What's changing and why

Until now, when the AI agent decided it needed a human, the operator opened the dashboard and saw a vague summary like "Calvin is asking about scheduling and suggested a time." If the customer had actually proposed two specific slots — say Thursday at 9:00 and Thursday at 12:00 — those slots never showed up. The operator had to scroll the transcript, find them, and figure out the choice on their own. The dashboard's frontend was already built to display a richer briefing (a reason paragraph, a "what the customer wants" line, a "what you have to decide" line, and a row of recommended action buttons), but the backend was never sending those fields, so the frontend fell back to a generic text parser that did its best with the raw alert.

This change has the backend generate that structured briefing itself, using a separate Claude call dedicated to that one job, every time a new escalation is created. The result is saved alongside the escalation row and surfaced everywhere the dashboard reads escalation data. It also fixes a related annoyance: if the agent escalates the same conversation a second time before the operator has resolved the first one, the system now updates the existing escalation in place rather than creating a duplicate row in the operator's queue.

## Step by step — what the code does now

STEP: Database now has a slot for the structured briefing

When the system starts up, it makes sure the escalations table has a column to hold the structured briefing as a block of saved text. If the column already exists from a previous run, it leaves it alone. Existing rows have an empty briefing — only newly created escalations get a populated one.

STEP: A separate, dedicated briefing generator

A new module owns the job of writing the briefing. It takes the channel (whatsapp, email, instagram, etc.), the customer's id, the customer's name, the escalation mode (soft or hard), and the recent conversation history. It hands all of that to Claude with a strict instruction: read the conversation between the customer and the AI agent, and produce five things — a one-paragraph reason for pulling in the human, a one-sentence "what the customer wants," a one-sentence "what the operator must decide," a list of three to five concrete action buttons (each one a specific action like "Confirm Thursday at 09:00," not a category like "Pick a time"), and a small details block recording the intent type, every time slot the customer proposed in their own wording, and a short topic label.

The instruction explicitly bans Claude from being vague: if the customer mentioned exact times, those exact times must appear in the buttons and in the proposed-times list. For scheduling escalations, "Suggest another time" and "Switch to human takeover" are always added as fallback buttons.

If Claude succeeds, the module returns the briefing as a structured object. If anything goes wrong — no API key, network failure, malformed response, missing tool output — the module logs the failure and returns nothing. It never raises.

STEP: A new hook on escalation creation

The system already had a pattern where escalation creation calls a registered alert dispatcher to send the operator's email. The same pattern is now mirrored for the briefing generator: a separate slot, set once at startup, called separately from the alert dispatcher. They each run inside their own try/catch, so a Claude hiccup can't break email delivery and an email failure can't break briefing generation.

The dashboard is what wires the generator into that slot at startup. The wiring layer pulls the relevant conversation history for the channel — email pulls from the email thread, Instagram/Facebook/Messenger pulls from the DM history, anything else (mostly WhatsApp) pulls from the WhatsApp history, with the last 20 messages — then calls the briefing generator with that history and returns whatever it gets back.

STEP: Escalation creation now dedups and saves the briefing

When the agent decides to escalate, the system first checks whether an unresolved escalation already exists for that same customer. If one does, the system updates that existing row's subject, body, name, and timestamp instead of inserting a new row. The original row keeps its id, so any email thread or learning entry already attached to it stays attached. If no unresolved escalation exists, it inserts a fresh row as before.

After the row is in place (whether new or updated), the system marks the conversation status as open, fires the existing alert dispatcher to send operator email, then calls the new briefing dispatcher. If the briefing dispatcher returns a structured object, the system saves it as a block of text on the same row. If the dispatcher returns nothing or raises, the row stays as is with an empty briefing slot.

STEP: The escalations list now includes the briefing

When the dashboard asks for all escalations, the response includes, for each row, three new fields: the full briefing object, the recommended-options list lifted out for convenience, and the extracted-details block lifted out for convenience. If the briefing slot is empty (older row, or generation failed), all three fields come back empty and the frontend falls back to its generic text parser.

STEP: The conversation detail endpoint now includes the briefing

When the dashboard opens a single conversation, the response now also includes the briefing for the most recent unresolved escalation on that conversation, plus the same lifted recommended-options and extracted-details. This means the operator's escalation panel can render the structured briefing without making a second network call. There's also a new helper that fetches just the briefing for a given customer id, used by the conversation detail path.

## Edge cases

- If Claude is down or returns garbage, the escalation row is still created and the briefing slot stays empty. The operator sees the dashboard's older generic-text summary instead. The failure is logged so the rate can be monitored.
- If the system has no Anthropic API key in its environment, the generator returns nothing immediately without calling Claude. Same outcome as a failure: empty briefing, fallback parser kicks in.
- If the agent escalates the same conversation a second time while the first escalation is still pending, the existing row is updated in place. The row id stays the same. The briefing is regenerated and overwrites the old one. The operator does not get a duplicate entry in their queue.
- The dedup key is the customer id alone, not customer-id-plus-channel. A WhatsApp number and an email address are different ids by definition, so this is not a concern in practice.
- Briefing generation runs synchronously during escalation creation and adds roughly one to two seconds of Claude latency on top of the existing email-send time. Escalations are rare, so the trade-off was accepted in favor of avoiding a "summary pending" intermediate state in the dashboard.
- Older escalations created before this change have an empty briefing slot forever. They are not backfilled. The frontend's existing generic-text parser handles them as it always did.
- The dedup logic only applies to escalation rows. Notifications of type "relay" (where the AI agent asks the operator team a question, a different flow) do not trigger briefing generation and do not dedup against escalations.
- The conversation history fed to Claude is capped at the last 20 messages. If a conversation is very long and the relevant exchange happened earlier, those older messages are not included in the briefing prompt.
- If pulling the conversation history fails for any reason, the generator runs against an empty transcript and Claude is told there is no message history available. It will probably return a low-quality briefing in that case rather than nothing.

## What did NOT change

The AI agent's prompt, the rules about when an escalation fires, the alert email content, the operator's resolve flow, and customer-facing replies are all untouched. The agent still decides to escalate using the same logic as before. The operator's email still arrives the same way. Only what shows up inside the dashboard's escalation panel — and only when the operator opens it — has changed. The booking flow, the agent's reply path, and the rest of the customer experience are not affected by this change.
