# OUTPUT 176 — Marina context-aware fallback reply

## What was done

Added `_build_contextual_fallback_reply()` helper to `marina_agent.py` at module level (right before `process_message`). It takes `thread_fields`, `channel`, `signature`, `svc_label`, `party_label` and returns a reply string that acknowledges what's already known and asks only for what's missing. Wired it into the existing fallback dict construction in `process_message`, replacing the static "tell me trip/date/guests" string. Removed the WhatsApp override block — the helper branches on `channel` natively and returns a terse (<40 word, no signature) reply for WhatsApp vs. a full email reply with signature for email.

Four branches per channel:
1. **Empty fields** → classic first-contact wording (asks for service + date + guests).
2. **Partial fields** → acknowledges name/service/guests inline, asks for missing date.
3. **All fields known** → does NOT re-ask; asks the customer to resend their last message ("resend" / "last message" keywords).
4. **WhatsApp variants** → short ack + short ask; same branching logic, compressed wording.

Preserved Brief 174's `internal_note == "Fallback response — Claude API call failed or returned unparseable output."` invariant exactly so the existing internal_note fallback-detection tests keep passing.

## Tests

**833 passing / 0 failures** (828 baseline from Brief 175 + 5 new in `test_176_contextual_fallback.py`).

One regression had to be patched: `test_069_whatsapp_agent.py::test_process_message_whatsapp_failure_fallback_reply` was asserting `"send that again"` from the old hardcoded string. Updated it to the Brief 176 contract: assert `internal_note` equals the fallback marker AND reply word count < 40.

## Deployment

Source committed `8d8f2bf`, pushed to main. Background deploy fired to both containers. Code-only change — no schema, no data migration.

## Unexpected

Nothing surprising in execution. The brief-reviewer caught one broken assertion (`or` short-circuit making a "not in" check trivially pass) in round 1 which I patched to four separate substring checks before round 2 approval. The helper ran clean on first test execution.
