# OUTPUT 246 — Hard-takeover WhatsApp /reply: send operator text verbatim, store as role=operator

## What was done

Surgical fix for issue #11. The `/escalations/{id}/reply` WhatsApp branch in `wtyj/dashboard/api.py:2418` was unconditionally routing operator text through `marina_agent.process_message()` regardless of escalation mode. When Calvin tested hard-takeover with abusive text, Marina (correctly) refused to engage and generated a safety refusal; the branch sent that refusal verbatim to the customer and stored it as role='assistant' (rendered as MARINA in the dashboard). Per-step shipped:

1. **Split the WhatsApp branch by escalation mode** at `wtyj/dashboard/api.py:2418-2522`. New early-return hard-mode block (above the existing soft path): when `esc.get("mode") == "hard"`, send `req.text` verbatim via `send_whatsapp_message`, store via `wa_store_message(customer_id, "operator", operator_reply)`, return `{"ok": True, "reply": operator_reply, "channel": "whatsapp", "role": "operator"}`. Includes the same Brief 215 try/except learning save the original soft path had. Soft/legacy/no-mode path is BIT-for-BIT unchanged below the new block — reviewer can verify by diffing.
2. **3 new tests** appended to `wtyj/tests/social/test_213_escalation_control.py` (per Brief 236 rule — Brief 213's existing per-source-module file for takeover/escalation control). Tests reuse the file's existing `_login()` / `_auth(token)` / `client = TestClient(app)` helpers (lines 20-29). Tests cover: (a) hard-mode WhatsApp /reply sends verbatim AND `marina_agent.process_message` is NEVER called (asserted via monkeypatched fail-if-called), (b) stored row has role='operator' AND not role='assistant', (c) regression — soft-mode behavior unchanged (still routes through Marina, still stores role='assistant').

**Brief-reviewer:** PASS round 1 zero issues. Reviewer verified all anchors, monkeypatch targets, helper reuse, and Rule compliance (no second Claude call; routing on structured value `esc.get("mode")` not on text content; no Python language classifier; no static reply templates). Noted the brief's stale "1058 = 1055 baseline + 3 new" math against MEMORY.md's 1015 — actually current baseline IS 1055 post-Brief-245; the math is correct.

## Tests

1058 passing / 0 failures (1055 baseline + 3 new = 1058). Targeted file `wtyj/tests/social/test_213_escalation_control.py` runs 14/14 (was 11; added 3).

## Frontend contract for SR

**No new endpoint, no new request shape.** The frontend keeps calling the same `POST /dashboard/api/escalations/{id}/reply` endpoint with the same `{message: "..."}` body for both modes.

**New response field for hard-mode WhatsApp:** `"role": "operator"` is now present in the response body when the escalation is hard mode (and `"channel": "whatsapp"` for clarity). The frontend can use this to render the just-sent message in the conversation trail with the correct role styling.

**Backend storage contract:** `whatsapp_threads` rows for hard-mode operator replies now have `role='operator'` (matching the email branch's Brief 210 behavior, which has been writing `role='operator'` for ~6 weeks). The frontend's existing email-side render rule for `role='operator'` should apply identically to WhatsApp-side `role='operator'` — if a gap exists in the WhatsApp render path, that's a separate frontend brief.

## Deployment

Source commit pending. Will deploy via the standard CI pipeline. All 4 containers expected healthy post-deploy. Briefs 238 tenant guard / 239 rich body / 240 Zernio route / 241 dispatcher / 242 confirm endpoint / 243 deep-link buttons / 244 identity-leak fixes / 245 QA simulator all preserved (no shared code paths touched).

## Out of scope (deferred per brief Step 3)

- **Soft-mode "what if Marina would refuse to reformulate operator's coaching text"** — separate bug not observed in Calvin's test. Defer to future brief if a real case is observed.
- **Pre-send safety filter for hard-mode operator text** — hard mode is operator-takes-responsibility per issue #11's "acceptable hard operator reply still sends correctly". No AI moderation in hard mode by design.
- **Backfill of historical mistakenly-stored Marina-refusal rows** — out of scope; rare; specific to Calvin's one test message.
- **Same fix for `/escalations/{id}/guidance`** — `/guidance` already 409s on hard mode at api.py:2538-2540 (Brief 214); no change needed.
