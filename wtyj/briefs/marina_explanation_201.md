# EXPLANATION 201 — dm_agent em-dash strip + dashboard message field aliases

## In one sentence

Calvin (the unboks DM agent) stops sending em-dashes in replies, and operators can now click into any conversation on the dashboard and actually see the message bubbles instead of a blank panel.

## What's changing and why

Two unrelated bugs surfaced from the same testing session, and both are fixed in one small deploy.

The first bug: Calvin's brand voice rules tell him "never use em-dashes," but the model ignores that rule consistently. Every reply Calvin sent during testing on the unboks WhatsApp number contained at least one em-dash. Asking the model nicely doesn't work, so the system now scrubs em-dashes out of replies after the model produces them. The replacement character is a plain comma — the simplest swap that's deterministic and reversible.

The second bug: after last week's cutover that pointed the unboks dashboard at our Python backend, the inbox list correctly showed the two unboks conversations, but clicking into a conversation produced an empty message panel. The dashboard's frontend was looking for fields named "content" and "timestamp" on each message, but our backend was returning the same data under the older names "text" and "created_at." The frontend silently rendered nothing. The fix: our backend now sends both name pairs on every message, so the frontend gets what it expects without breaking any other client that relies on the old names. The backend also now includes a unique row identifier on each message so the frontend has a stable key to track each bubble.

## Step by step — what the code does now

REPLY POST-PROCESSING IN THE DM AGENT: when Calvin generates a reply for a WhatsApp, Instagram, or Facebook DM, the system runs a short cleanup pass before sending. It already stripped unfilled booking placeholders and stray markdown formatting. It now also walks through the reply text and replaces every em-dash character with a comma. En-dashes and regular hyphens are left alone. If the model writes "Hello — how can I help?" the customer receives "Hello , how can I help?" — slightly awkward typography, but consistent and never an em-dash.

CONVERSATION HISTORY LOOKUP: when something asks the database for the full message history of a phone number, the lookup now returns each row's database identifier alongside the role, the text, and the timestamp. This is additive — every part of the system that already used role, text, or timestamp keeps working unchanged. Three places in the codebase consume this history (the dashboard's conversation detail endpoint, the dashboard's reply-suggestion endpoint, and the social agent's escalation log builder) and all three only read fields by name, so adding a new field doesn't disturb them.

DASHBOARD CONVERSATION DETAIL ENDPOINT: when the dashboard asks the backend for a single conversation by phone number, the backend pulls the full message history, then walks through each message and adds two extra fields. The first new field, "content," carries the same text as the existing "text" field. The second, "timestamp," carries the same value as the existing "created_at" field. The original fields stay in place. The frontend reads the new names; older clients that read the old names keep working.

EMAIL CONVERSATIONS: the email branch of the same endpoint is untouched — it returns whatever the email helper produces, exactly as before. Only the WhatsApp branch gained the alias enrichment.

## Edge cases

- If the model writes "word — word" with spaces around the em-dash, the customer sees "word , word" with single-space-comma-single-space. Operators have accepted this awkward spacing as the trade-off for a one-line fix; iteration on typography can come later if it bothers anyone.
- If the model never produces an em-dash, the reply passes through untouched. There are no false replacements.
- If the dashboard backend is hit by an older client that reads "text" and "created_at," it still works — those original fields are preserved on every message.
- If a conversation is empty (no messages stored yet), the message list comes back empty and no enrichment loop runs. Nothing breaks.
- The dashboard frontend still has no defensive fallback if the backend ever drops the "content" field again. The aliases are a workaround on the backend side; the frontend remains brittle, and a follow-up note has been logged for the frontend team.
- The dashboard frontend also still doesn't refresh authentication tokens when they expire. Operators who leave the dashboard idle for too long will see broken behavior on their next click and need to log in again. This is unrelated to today's fix and has been logged as a follow-up.

## What did NOT change

Marina's email and booking-flow agent is untouched — this brief only modifies Calvin's DM path. The booking flow, the customer-data handling, the Claude prompt content, and the brand voice rules in the unboks client config are all unchanged. The database schema is unchanged — no migration, no new columns, just an extra column being read out that was already stored. The list view of conversations on the dashboard is unchanged and was already working through the frontend's defensive preview reader. The legacy `api.wetakeyourjob.com` endpoint shape continues to return the original field names so any existing consumer of that endpoint sees no difference.
