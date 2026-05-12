# EXPLANATION 264 — Server-side Agent learning preference settings (GET/PUT /settings/agent-learnings)

## In one sentence
Each tenant now has two on/off switches for Agent learning behavior stored on the server (instead of in the browser), so a teammate's preference setting follows the account everywhere instead of being trapped on one laptop.

## What's changing and why

Calvin asked for two switches in the dashboard that control how the Agent learning feature behaves: one that decides whether the operator sees a "save this as a learning" suggestion after every reply, and one that decides whether the system should automatically create a draft learning every time an operator types a reply. Replit's first pass put both switches in the browser's local storage. That worked for a single operator on a single device, but as soon as the same operator opened the dashboard on their phone, or a teammate signed in from another laptop, the switches would silently reset. Local storage is tied to one browser on one machine — it doesn't sync.

This change moves the storage of those two switches to the backend, scoped per tenant. BlueMarlin's switches live in BlueMarlin's database, Adamus's switches live in Adamus's database, and so on — there's no cross-contamination. The frontend can now ask the server "what are the current switch positions?" when the settings page loads, and tell the server "the operator just changed this switch" when one is toggled. Whoever signs in next sees the same state.

Important scope note: this change only stores the switches. The first switch (show suggestion after replies) is purely a frontend display setting, so once SR wires the dashboard to the new endpoints, it works end-to-end. The second switch (auto-create pending learnings) is stored, but flipping it ON does not yet actually trigger auto-creation — that piece of wiring lives in the reply-handling code path and is deliberately held back for a follow-up brief so the storage layer ships clean and gets reviewed on its own merits.

## Step by step — what the code does now

READ THE TWO SWITCH POSITIONS

When the system needs to know the current switch positions, it looks up two named entries in the generic key-value settings table the tenant already had. The settings table stores everything as text, so the system reads the raw text for each switch and converts it back to a true/false answer. If a switch has never been saved (fresh tenant, never touched), the system falls back to the documented default: the "show suggestion" switch defaults to ON, and the "auto-create pending learnings" switch defaults to OFF. The result is bundled into the camelCase shape the frontend expects.

GET ENDPOINT — LOAD CURRENT SWITCH POSITIONS

The frontend calls this when the settings page loads. The endpoint requires the same login check every other dashboard endpoint uses. It then runs the read step described above and returns the current state of both switches. A brand-new tenant that has never saved either switch will get back "show suggestion = true, auto-create = false" — the defaults — without any database row ever being created.

PUT ENDPOINT — SAVE NEW SWITCH POSITIONS

The frontend calls this when an operator flips either switch. The endpoint expects a payload with both switches included. Before the system touches the database, it validates that both values are real true/false booleans — not the word "yes," not the number 1, not the string "true." If the validation fails, the request is rejected with a clear validation error (HTTP 422) and nothing is saved. If validation passes, the system writes both switch positions to the settings table as the text "true" or "false," then reads them back and returns the saved state so the frontend can confirm what landed.

THE STRICT-BOOLEAN DECISION

The validation step uses a strict-boolean type rather than the loose default. The loose default would have quietly accepted strings like "yes," "on," or "1" and turned them into true behind the scenes. That sounds friendly, but it hides bugs — if the frontend ever sent the wrong shape, the server would happily save a coerced value and nobody would notice until the behavior diverged from what the operator clicked. Strict-boolean refuses anything that isn't literally true or false, so a frontend mistake gets caught at the door instead of silently corrupted.

NO REPLY-PATH CHANGES

The reply handler, the operator takeover flow, and the pending-learning creation code are all untouched. A test in the new test set explicitly proves this: it counts the pending learnings, flips the auto-create switch to ON via the new save endpoint, and counts again — the count is unchanged. The switch is stored, but until the follow-up brief wires it into the reply path, flipping it ON has no real-world effect beyond persisting the operator's preference.

## Edge cases

- If a tenant has never saved either switch, the GET endpoint returns the defaults (show suggestion ON, auto-create OFF) without writing anything to the database. The first save creates the rows.
- If only one switch has ever been saved and the other has not, the GET endpoint returns the saved value for the one that exists and the default for the one that's missing. Per-switch fallback, not all-or-nothing.
- If the frontend sends a non-boolean payload (the word "yes," null, a number, a missing field), the request is rejected with HTTP 422 and nothing is saved. The previously saved switch positions stay intact — no partial write.
- If two operators on the same tenant flip switches at the same time, whichever PUT call lands last wins. Both calls succeed individually; there's no merge logic. Acceptable — settings changes are rare and operator-initiated, not high-frequency.
- If a deploy gets rolled back after switches have been saved, the rows stay on disk but the older code doesn't read them. Harmless dead data; the next forward deploy picks them up again.
- Calvin's spec mentioned "safe 400" for invalid payloads. The implementation returns 422 instead, which is the industry-standard validation-error status. The body still contains a clear Pydantic validation detail — no crash, no information leak. If Calvin specifically wants 400, that's a one-line follow-up override.
- Flipping the auto-create switch ON does NOT yet cause operator replies to auto-create pending learnings. This is the documented deferred scope — the switch is stored only. Operators who turn it on today will see zero behavioral change until the follow-up brief ships the reply-path wiring.

## What did NOT change

Marina's prompt, the booking flow, the customer-facing reply logic, and the existing learning-approval flow (Brief 263) are all untouched. The reply endpoints, the operator takeover path, the prompt-injection filter that decides which approved learnings reach the Agent — none of those were modified. No database schema migration was needed; the existing key-value settings table absorbed the two new entries without any structural change. Brief 264 is purely additive: two new endpoints and one helper sitting next to the source-of-truth endpoints. The localStorage fallback the frontend may keep around as a transitional safety net continues to work during any rollback window without interfering with the new server-side storage.
