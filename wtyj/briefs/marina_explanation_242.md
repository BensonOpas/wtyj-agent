# EXPLANATION 242 — Operator Confirm appointment endpoint (TASK-074 follow-up)

## In one sentence

When the operator clicks Confirm on an appointment in the dashboard, the system now flips that appointment to "confirmed" and fires the alert dispatcher that was sitting dormant — meaning the configured email, WhatsApp, or Telegram alert about the confirmed appointment actually goes out.

## What's changing and why

Until now, the alert dispatcher built in the previous brief was wired up but had nothing to wake it up. The dispatcher only fires when an appointment moves into the "confirmed" state, and no part of the system ever moved an appointment into that state. So in production, no confirmation alerts had ever been sent, even though the plumbing existed.

This brief plugs that hole on the operator side. There is now a backend endpoint the dashboard can call when the operator clicks the Confirm button on an appointment. The endpoint flips the appointment's status to "confirmed", which causes the dispatcher to send the alert to whichever destinations the tenant has configured. If the operator clicks Confirm a second time (because they double-clicked, or because two operators touched the same row), no second alert goes out. The endpoint reports back whether this was a fresh confirmation or a duplicate, so the dashboard can show a quieter visual response on the duplicate case instead of celebrating it like a brand-new confirmation.

The customer-side path — where Marina would read a customer's "yes Friday at noon works" reply and auto-flip the appointment herself — is intentionally not part of this brief. Only the operator's manual Confirm path exists today. Marina-driven auto-confirmation is being saved for a later brief.

## Step by step — what the code does now

CONFIRM AN APPOINTMENT BY ID (the new helper)

When something asks the system to confirm an appointment by its database id, the system first looks up that appointment row. If no row matches the id, the helper bows out and returns nothing — the caller will turn that into a 404. If a row does exist, the system reads the row's current status and remembers whether it was already "confirmed" before today's call. It then re-saves the appointment through the same upsert function the rest of the appointment lifecycle uses, this time forcing the status to "confirmed". That re-save is what triggers the dispatcher behind the scenes: if the old status was anything other than "confirmed", the transition counts as fresh and the alert goes out; if the old status was already "confirmed", the same upsert function detects no real transition and stays quiet. After the save, the system reads back the row's last-updated timestamp and returns a small package: the appointment id, the new status of "confirmed", the timestamp, and a flag saying whether this was a duplicate confirmation.

The helper accepts an optional "confirmed by" name and an optional note. Today neither one is stored anywhere — the appointments table has no columns for them yet. They are accepted only so that the frontend can start passing them in now and a later brief can wire up persistence without changing the API contract.

THE OPERATOR-FACING ENDPOINT

A new backend endpoint listens at the dashboard URL for an appointment's confirm action. The endpoint requires the same dashboard login that the rest of the dashboard uses, so an unauthenticated request is rejected. When a valid request comes in, the endpoint calls the helper described above. If the helper finds nothing, the endpoint returns a 404 with the plain message "appointment not found". Otherwise it returns the small JSON package: id, status, the confirmed-at timestamp, and the alreadyConfirmed flag. The endpoint accepts an empty request body and falls back to default values, so a dashboard that just wants to say "confirm this one" doesn't have to send anything at all.

THE ALERT DISPATCH (unchanged but now reachable)

Because the helper goes through the same upsert function as every other appointment write, the dispatcher built in the previous brief activates exactly as designed. On a true transition into confirmed, it reads the tenant's alert settings, checks that appointment alerts are switched on for this tenant, and sends the configured alerts. On a non-transition (a re-confirmation) it sees the status was already "confirmed" and stays silent. A second safety net inside the dispatcher additionally checks the audit log for any prior delivery attempt to the same destination for the same appointment, so even if the transition check were ever bypassed, a duplicate alert still wouldn't go out.

## Edge cases

- If the operator clicks Confirm twice quickly, the first click sends the alert and the second click returns alreadyConfirmed=true with no alert sent. The dashboard can use that flag to show a softer "already confirmed" notification instead of a fresh "confirmed!" toast. Acceptable.
- If two operators click Confirm at almost the same moment on the same appointment, both calls go through the upsert. Whichever lands second sees the status already at "confirmed" and is treated as a duplicate. No double alert. Acceptable.
- If the operator confirms an appointment whose id does not exist (deleted row, typo, stale dashboard), the endpoint returns 404 with "appointment not found". The dashboard can show that as a friendly error.
- If someone manually flips an appointment row to "confirmed" directly in the database (bypassing the upsert function), the dispatcher does not fire — the trigger is the upsert path, not the database state. This matches existing behavior and is the intended boundary.
- The "confirmed at" timestamp returned to the dashboard is read from the row's updated-at column, which the upsert function bumps on every save. That means even a duplicate confirmation gets a fresh timestamp returned to the caller, even though no alert was sent. This is a known soft coupling: if a future change makes the upsert skip writes on no-op confirms, the duplicate-confirm timestamp would go stale and would need to be recomputed here.
- The "confirmed by" operator name and any note text the dashboard sends are accepted but thrown away — the appointments table has no columns for them yet. The frontend can start sending them now without breaking; a later brief is needed before they actually get stored.
- Only forward motion is supported. There is no "un-confirm" endpoint. To revert a confirmed appointment back to a pending state, an operator would need to edit the database directly (and that direct edit would not re-trigger any alerts).
- Only the status changes through this endpoint. Customer name, title, proposed times, location — all stay whatever they were last set to. This endpoint is not a general "edit appointment" endpoint.

## What did NOT change

Marina's prompt was not touched. The customer-facing conversation flow was not touched. The appointments table schema was not changed — no new columns, no migrations. The previous brief's dispatcher, two-layer dedup, tenant alert-type gate, and rich-body formatting are all preserved exactly as shipped. The Zernio operator-route work from an earlier brief is consumed transitively when alerts go out but is not called from this endpoint directly. The tenant guard governing inbound webhooks is not relevant here — this is a dashboard-side action inside an already-authenticated tenant container. BlueMarlin was not touched. The customer-side auto-confirm path (Marina detecting "yes" replies) is not part of this work and remains deferred.
