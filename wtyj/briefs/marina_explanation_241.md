# EXPLANATION 241 — Appointment alerts using shared alert destinations (TASK-074)

## In one sentence

The system can now send a separate "Appointment confirmed" alert to the operator (email + WhatsApp + the placeholder Telegram/Messenger destinations) using the same destinations Settings already configures for escalation alerts — but the alert is wired and dormant, because no part of the system flips an appointment to "confirmed" yet.

## What's changing and why

Until today, the only operator alert the system could send was an escalation alert (Marina hands the conversation off to a human). Calvin asked for a parallel alert when an appointment with a customer becomes confirmed — same recipients, same delivery channels, but a different subject line and a body that names the customer, channel, topic, time, and location. This brief installs that second alert path end-to-end at the alert layer: the schema, the dispatcher function, the per-channel send logic, the Settings toggle, and the trigger that fires when an appointment's status transitions into "confirmed."

The new alert uses the destinations the operator already configured for escalations: the default support email, the optional alternative email, the WhatsApp operator route established in the previous brief (delivered through Zernio, not Meta), and the Telegram/Messenger placeholders (which still log a "skipped" row because no provider is wired). Settings now has a per-alert-type switch — operators can disable appointment alerts independently from escalation alerts, and vice versa, without touching the channel destinations themselves.

The trigger for sending the alert is real: any code that promotes an appointment row's status into "confirmed" will fire the dispatcher. But no part of the running product does that yet. Today, the only code path that writes appointment rows uses the statuses "detected" and "pending_team_confirmation." So in production, this alert will not fire until a future change adds either an operator dashboard button to confirm an appointment or Marina-side detection of the customer's "yes" reply. The brief acknowledges this gap explicitly and tests exercise the wired path by calling the upsert function directly with the confirmed status.

## Step by step — what the code does now

STEP: Add four new database columns

When the system opens its database connection, it now also runs four "add column if missing" steps. Two columns are added to the alert delivery audit log: an alert type label (defaulting to "escalation" so every existing row is correctly labeled retroactively) and an appointment id (left empty for older rows). Two columns are added to the alert settings row: one toggle for whether escalation alerts are enabled and one for whether appointment alerts are enabled, both starting in the on position so existing tenants keep getting escalation alerts and start getting appointment alerts as soon as an appointment becomes confirmed.

STEP: Generalize the delivery-recording helper

The existing helper that records a delivery attempt (sent / failed / skipped) now also accepts an optional alert type and an optional appointment id, with safe defaults that match how the escalation code already calls it. Existing escalation-side callers do not need any change — they keep recording rows with the default "escalation" label. The appointment-side caller passes "appointment" plus the appointment id and leaves the escalation id empty.

STEP: Add a "have we already sent this one?" check

A new helper looks at the delivery audit log and answers a single question: "Did we already record a sent or failed delivery for this exact appointment, on this exact channel, to this exact destination?" If yes, the dispatcher will skip that destination. Importantly, "skipped" rows do not count as already-sent — a destination that was skipped because the WhatsApp route was not yet bootstrapped is still allowed to retry the next time a confirmation event happens.

STEP: Register the appointment alert dispatcher with the data layer

The data layer holds a placeholder for the appointment dispatcher function, starting as empty. When the dashboard module loads, it puts its own appointment-alert function into that placeholder. This indirection avoids the two modules needing to import each other (which would cause a startup crash). If the placeholder is empty — for example, in a small unit test that never loads the dashboard — the data layer simply skips firing the alert.

STEP: Detect a transition into "confirmed" inside the appointment write path

The single function that writes appointment rows (used by the escalation summary code today and by any future caller) now reads the appointment's old status before it writes the new one. If the row is brand new and the status being written is "confirmed," that counts as a transition. If the row already existed with any non-confirmed status and the new status is "confirmed," that also counts as a transition. If the row already had "confirmed" and is being saved again with "confirmed," that does NOT count as a transition — the dispatcher is not fired. The same is true if the new status is anything other than "confirmed."

STEP: Fire the appointment dispatcher (with safety net)

When a transition is detected and a dispatcher is registered, the system reads the alert settings, checks whether appointment alerts are enabled for this tenant, and if so calls the dispatcher with the appointment's row id, customer name, channel, and a dictionary of all the appointment fields. The whole dispatcher call is wrapped in a safety net so that if the dispatcher throws an error, the appointment row still saves cleanly — operator visibility into the appointment never depends on whether the alert succeeded.

STEP: Build the appointment subject line

A small helper produces the email subject. With both a name and a time, it reads "Appointment confirmed: Calvin — Friday 12:00." With no time set, it falls back to "Appointment confirmed: Calvin." With no name set, it uses "customer." If there is no top-level time label but there is a list of proposed times, it uses the first proposed time.

STEP: Build the appointment body

A second helper produces the body. It opens with "Appointment confirmed" and lists, on separate lines: the customer name (or "(unknown)"), the channel (in human-readable form), the topic (the appointment title, defaulting to "Appointment"), the time (or "(time not set)"), and the location (or "Location not set" when blank). It closes with a one-line prompt to open the dashboard to review or update the appointment.

STEP: The appointment alert dispatcher itself

When called, the dispatcher reads the business name and default email from configuration, fetches the alert settings (which yields the per-channel destinations and the per-alert-type toggles), and builds the subject and body once. Then it walks the channels:

For email, it collects the primary destination (resolving the "default" placeholder to the actual support email) and the optional alternative destination, removing duplicates. If neither is set it records a single skipped row explaining why. For each real recipient, it first asks the dedup helper "have we already sent to this exact address for this appointment?" — if yes, it moves on without logging anything new. Otherwise it sends the email, recording a sent row on success or a failed row (with a truncated error message) on exception.

For WhatsApp, it checks that a destination is configured (skipping with an explanation if not) and that the dedup helper says this destination has not already been delivered. It then asks for the resolved operator WhatsApp route — the Zernio side of the previous brief. If no resolved route exists, it records a "zernio_operator_destination_not_resolved" skipped row. If a route exists, it sends through the same Zernio reply path that customer messages use, recording sent on success, failed if the send returns false, and failed with the exception text if the send throws.

For Telegram and Messenger, it records a "provider not configured" skipped row whenever those channels are enabled, mirroring how escalation alerts handle them today.

Every delivery row this dispatcher writes is tagged with "appointment" as the alert type and the appointment id, with the escalation id left empty. That is what makes them queryable as a separate stream from escalation deliveries.

STEP: Add the per-alert-type gate to the escalation dispatcher too

The existing escalation alert dispatcher now reads the same alert settings, looks at the new escalations toggle, and short-circuits the whole function (no rows written, no provider calls) if the operator has flipped that toggle off in Settings. The toggle defaults to on, so existing behavior is unchanged unless an operator explicitly turns escalation alerts off.

STEP: Extend the Settings endpoint shape

The Settings request model now also accepts an optional alertTypes block with two boolean fields (escalations and appointments), both defaulting to on. The PUT endpoint passes that block through to the save function so it lands in the new database columns. The GET endpoint needs no changes itself — the underlying read function now includes the alertTypes block in every response, both when a real settings row exists and when it falls back to defaults. A frontend that does not know about alertTypes simply ignores the new field; a frontend that knows reads it.

STEP: Persist alertTypes in the upsert

The save function for alert settings now also accepts an optional alertTypes dictionary, converts each boolean to a 0 or 1, and includes those two columns in the all-or-nothing upsert that already preserves the bootstrap-only WhatsApp Zernio columns from the previous brief. If alertTypes is not supplied, both flags default to on.

## Edge cases

- If an appointment is upserted with status "confirmed" while the dispatcher placeholder is still empty (for example, during a unit test that never loads the dashboard), no alert fires and no error is raised. The appointment row still saves normally.
- If the dispatcher itself throws any kind of error — bad config, broken SMTP, network issue inside the WhatsApp send — the appointment row is still committed cleanly. The exception is swallowed silently. This is intentional; it prevents a flaky alert path from blocking an appointment from being recorded.
- If the operator has not configured an alternative email, only the primary email is used. If primary and alternative are the same address, the alternative is dropped and only one email is sent.
- If WhatsApp is enabled in Settings but no destination has been entered, a single "skipped" row with the reason "no whatsapp destination configured" is written and no further WhatsApp work happens.
- If WhatsApp has a destination but the Zernio operator route has not yet been resolved (the bootstrap has not completed), a "skipped" row with the reason "zernio_operator_destination_not_resolved" is written. The appointment will get another chance to send WhatsApp on the next confirmation event after the route resolves — because skipped rows do not block retries in the dedup check.
- If the same appointment becomes confirmed twice (for example, an operator clicks Confirm twice in quick succession at some point in the future), the layer-1 transition check catches it: only the first save where the old status was non-confirmed actually fires the dispatcher. A confirmed-to-confirmed re-save is silent.
- If something stranger happens — a future code path bypasses the upsert and calls the dispatcher directly, or two separate code paths both try to fire — the layer-2 dedup check catches it. For each destination, the system first asks the audit log whether a sent or failed delivery already exists for this appointment-channel-destination combination, and if so, skips it.
- Telegram and Messenger destinations always receive a "skipped" row when enabled, not a real send. The provider integration does not exist yet for those channels, just like in the escalation alert path.
- Existing rows in the delivery audit log from before this brief are now labeled as "escalation" automatically (via the column default). Their appointment id stays empty. This is semantically correct because every row written before this brief was in fact an escalation delivery.
- The dispatcher is wired but dormant in production. Until someone adds either an operator dashboard "Confirm" button or Marina-side detection of a customer saying "yes that time works," no appointment will ever transition to "confirmed" in the running system, and no appointment alert will ever fire. This is a known and documented gap. Tests cover the wired path by calling the upsert function directly with status="confirmed."
- Both alertTypes flags default to on. A tenant who was already running before this brief will start getting appointment alerts the moment a confirmed-status transition happens, without having to opt in. To opt out, the operator can save Settings with appointments set to false.
- A code-only revert restores the previous behavior; the four new database columns survive the revert (SQLite's ALTER ADD is forward-only) and sit unused with their defaults. No data fix is needed.

## What did NOT change

Marina's prompt was not touched. The booking flow was not touched. The customer-facing reply path was not touched. The existing escalation alert behavior — its rich body, its WhatsApp Zernio path, its destinations — is unchanged for any operator who has not explicitly flipped the new escalations toggle to off. The detection signal that promotes an appointment into "confirmed" is intentionally out of scope; that decision (operator button, customer-reply detection, or both) is deferred to a follow-up brief.
