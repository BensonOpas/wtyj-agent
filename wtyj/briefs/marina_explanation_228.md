# EXPLANATION 228 — Appointments backend (thread-based, derived from escalation summaries)

## In one sentence
The dashboard now has a real backend list of appointments that fills itself in whenever a customer's conversation gets escalated to humans for scheduling, instead of the frontend re-guessing them every time someone opens the inbox.

## What's changing and why

Before this change, the Appointments page in the dashboard had no backend behind it. The frontend was scanning the text of whatever conversation an operator happened to have open, looking for things that looked like days and times, and showing those as appointments. That meant every time a page loaded the parser ran again, nothing was saved, and if an operator never opened a particular conversation, the appointment for it never showed up. With two operators using the dashboard, neither of them shared what the other had seen.

Now the system stores appointments in its own table. Whenever a customer conversation gets escalated to humans and the AI's escalation summary says the customer is trying to schedule something, an appointment row is created or updated automatically. There is no extra AI call for this — the work is reused from the escalation summary that already runs. Operators see appointments that persist between sessions, and a brand-new endpoint at `/appointments` hands the list back in the exact shape SR's frontend expects.

## Step by step — what the code does now

STEP: New appointments storage area

When the system starts up, it makes sure there is a dedicated storage table for appointments. Each appointment is tied to one conversation, holding the customer's name, the meeting topic, a headline date/time string, the full list of times the customer proposed, an optional location, a status (currently either "detected" or "pending_team_confirmation"), and timestamps for when it was first seen and last updated. Only one appointment exists per conversation — repeat scheduling chatter on the same thread updates the existing row instead of piling up duplicates.

STEP: Saving or updating an appointment

When the system has a fresh appointment to record, it looks up whether one already exists for that conversation. If it does, the system overwrites the channel, customer name, topic, headline time, list of proposed times, location, and status, and stamps the update time. If it doesn't, the system creates a new row with the same fields plus the creation time. The headline date/time is just the first proposed time the customer mentioned, while the full list is kept as well so a detail view can show every option the customer floated.

STEP: Listing appointments for the dashboard

When the dashboard asks for the appointment list, the system reads every appointment, newest-updated first, and reshapes each one into the format the frontend uses (camelCase field names, ISO timestamps, the proposed times as a real list). If a row's stored proposed-times list is corrupted somehow, the system silently falls back to an empty list rather than crashing the whole response.

STEP: The escalation-summary hook that creates appointments

Whenever a customer is escalated to humans, the system already generates a Claude-written summary of why the conversation was handed off. After that summary comes back, the system now also peeks inside its "extracted details" section. If the customer's intent was scheduling, the system grabs the topic the AI extracted (defaulting to "Meeting" if missing) and the list of proposed times. For email conversations, the appointment's conversation key is prefixed so it matches the routing the frontend uses for email threads everywhere else. For WhatsApp, Instagram, Facebook, and Messenger, the customer's normal conversation ID is used directly. The system then upserts an appointment row with status "pending_team_confirmation" if the customer mentioned at least one time, or "detected" if scheduling was the intent but no specific times were proposed yet. If anything inside this whole side-write fails — bad data, missing thread, anything — the failure is swallowed and the original escalation summary still saves successfully. Appointments are best-effort; escalations are not.

STEP: New endpoint operators' frontend can call

There is a new `/appointments` endpoint protected by the same login check as the rest of the dashboard. It returns the full list of appointments under two different top-level keys ("items" and "appointments") so SR's frontend code works regardless of which envelope shape it expects. If there are no appointments yet, both keys return empty lists.

## Edge cases

- If a customer has a scheduling conversation that the AI handles end-to-end without ever escalating to a human, no appointment row is created. This is intentional for unboks, where every scheduling intent is meant to escalate anyway. For a future tenant where the AI should book directly, this would need a separate hook.
- If a customer brings up scheduling twice in the same conversation (for example, proposes Thursday, then later proposes Friday), the appointment row is updated in place. The headline time and topic reflect the latest summary, not the first one. The old proposed times are overwritten, not merged.
- If the AI's summary says scheduling but lists no times, an appointment still appears, marked "detected," with a blank headline time. Operators see it as a candidate so they know a scheduling thread exists, even if there's nothing concrete yet.
- If the AI's summary says something other than scheduling — refunds, complaints, pricing questions, anything else — no appointment row is written. The escalation itself still goes through normally.
- If the appointment write fails for any reason (bad data, missing thread, database hiccup), the failure is silently swallowed so it can't block the escalation summary from saving. Operators may notice a missing appointment that should have been written; they can refresh, or wait for the next escalation on the same thread to retry.
- Email conversations use a special prefix on the appointment's conversation key so clicking through to the thread routes to the right place. If the email thread can't be found (rare, but possible in unusual states), the system falls back to using the customer's bare ID instead of the prefixed key — the frontend may not route as cleanly in that case, but the appointment still appears.
- The status field currently only ever takes two values: "detected" and "pending_team_confirmation." The other states SR's spec mentions ("confirmed," "cancelled," "completed") are deferred to a future change because they require operator actions that don't exist yet. Operators won't see those statuses today.
- The appointments table is created if missing and never dropped. Rolling back this change leaves the table in place but harmless — old code simply ignores it.

## What did NOT change

Nothing in Marina or the AI's prompts was touched. No new Claude calls were added — the appointment data is reused from the escalation summary that was already being generated. The escalation flow itself, customer-message handling, booking logic for tenants like BlueMarlin, and the existing escalations endpoint behave exactly as they did before. This is a side-channel that observes existing escalation data and turns part of it into a new persisted view; it does not interfere with how customers are handled or replied to.
