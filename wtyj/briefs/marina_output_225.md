# OUTPUT 225 — Email reply endpoint for non-escalated threads

## What was done
Added `POST /messages/conversations/{conversation_id:path}/email/reply` to `wtyj/dashboard/api.py` (immediately above the Brief 218 forward/delete section). New `EmailReplyRequest` Pydantic model accepts `body` + ignored-for-now `mode` and `attachments`. Handler resolves `conversation_id` through the same path-resolver pattern as forward/delete (strip `email::` prefix, fall back to `_find_email_thread_key_for` for bare email addresses), pulls `customer_email` from `parts[1]` and `raw_subject` from `parts[2]` of the `subj:<email>:<subject>` thread_key, sends operator text verbatim via `smtp_send`, appends to thread state via `email_append_assistant_message`, returns `{ok: true, channel: "email"}`. No state_registry changes — all helpers already existed.

## Tests
1039 passing / 0 failures (baseline 1033 + 6 new).

## Unexpected findings
Round 1 of brief-reviewer FAILED with 4 blockers, all stemming from misreading the production thread_key shape. The handler initially used `parts[0]` for subject (which is the literal `"subj"` token), and the test fixture used a non-existent `EMAIL_STATE_PATH` env var with non-conforming seeded thread keys. Patched in round 2 to mirror the proven Brief 218 pattern (monkeypatch `state_registry._get_email_state_path` directly, use `webhook_server.app` via TestClient, seed `subj:<email>:<subject>` keys). PASS round 2. Lesson reinforced: when extending a route family, copy the sibling test file's fixture and seed shape verbatim before customizing.

## Deployment
Source committed and pushed; deploy still to fire.
