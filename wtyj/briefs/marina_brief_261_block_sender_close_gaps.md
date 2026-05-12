# BRIEF 261 — Block sender: close Brief 220 gaps (reason, blocked_by, inbox filtering, /blocked-senders alias)
**Status:** Draft | **Files:** `wtyj/shared/state_registry.py`, `wtyj/dashboard/api.py`, `wtyj/tests/dashboard/test_220_block_conversation.py` | **Depends on:** Brief 220 (block foundation) | **Blocks:** issue #30 verification

## Context

Issue #30 P1 asks for a universal Block action across channels. Brief 220 already shipped the backend foundation: `conversation_status.blocked` column at `wtyj/shared/state_registry.py:343`, `set_blocked()` / `get_blocked()` helpers at lines 1855/1876, `POST /messages/conversations/{conversation_id:path}/block` + `/unblock` at `dashboard/api.py:2639,2654`, `GET /settings/blocked-conversations` at line 2663, and per-channel suppression hooks at `email_poller.py:685` (inbound email dropped), `webhook_server.py:262` (WhatsApp), `webhook_server.py:210` (Zernio operator route), and `webhook_server.py:348` (IG/FB DMs). When the operator blocks a conversation, future inbound is dropped BEFORE Marina or the escalation pipeline runs — Brief 220's suppression layer is complete.

Issue #30's spec has four gaps vs the existing implementation:

1. **Inbox listings don't filter blocked rows.** `wa_list_conversations` at `state_registry.py:1517-1535` joins `conversation_status` only on `cs.deleted` — blocked rows still appear in the active inbox. `email_list_conversations` at `state_registry.py:1115-1172` only filters `flags.deleted`, never checks the blocked state. So when an operator clicks Block on a spam conversation today, the conversation IS suppressed for future inbound, but it STAYS visible in the active inbox list (because the most-recent message is already stored). Calvin's #30 rule 6: *"Future messages from blocked senders should not appear in active Inbox."*

2. **No `reason` field captured.** Calvin's spec rule 12: *"Blocking must be auditable: who/when/channel/identifier/reason if available."* Today `set_blocked()` accepts only `(conversation_id, blocked, channel)` — no reason. Issue #30 spec proposes optional reason values: `spam` / `abusive` / `wrong contact` / `other`.

3. **No `blocked_by` operator audit field.** Same rule 12 — "who" is missing. Today `bm_logger.log("conversation_blocked", conversation_id=...)` records the event in the log stream but the `conversation_status` row carries no operator identity. The dashboard auth model is password-only (no per-operator identity in `_check_auth`), so `blocked_by` must be a free-form string the client provides — frontend can populate it with the dashboard's operator label, or default to a generic `"operator"` string.

4. **Endpoint path naming doesn't match Calvin's spec.** Calvin's spec proposes `GET /blocked-senders` and `DELETE /blocked-senders/{id}/unblock`. Existing path is `GET /settings/blocked-conversations`. Brief 261 adds the `/blocked-senders` path as an alias (not a rename — `/settings/blocked-conversations` keeps working for any existing dashboard wiring) and returns the same shape extended with `reason` + `blocked_by`.

Calvin chose "close the 4 gaps only" (scope confirmed in J2-30 session 2026-05-12). No rebuild of Brief 220 — its foundation stays intact.

## Why This Approach

Three options considered:

1. **Close the 4 gaps inline on top of Brief 220 (chosen)** — additive SQL migration adds `reason` + `blocked_by` columns, `set_blocked` signature extended, listing filters tightened, `/blocked-senders` aliased to the existing handler. ~150 LOC + 5 tests. Reuses Brief 220's suppression-hook plumbing (all four inbound paths already check `get_blocked`); the four gaps are surface-only.

2. **Add a separate `block_history` audit table** — would capture each block/unblock event independently of the `conversation_status` row, so the audit trail survives an unblock or schema change. Heavier scope; not required by Calvin's spec (he asked for "auditable" not "audit trail across the row lifecycle"). Deferred unless Calvin asks for it in a follow-up.

3. **Rename `/settings/blocked-conversations` to `/blocked-senders` (no alias)** — cleaner but breaks any existing frontend wiring. Brief 220's endpoint may already be referenced by SR's Replit frontend or by `wtyj/docs/endpoint_inventory.md`. Adding the new path as an alias avoids the breakage risk for zero extra cost.

Trade-off accepted (option 1): the existing inconsistency between how the email path resolves block state (`email_poller.py:685` calls `get_blocked(from_email)` with the raw email address) and how the frontend likely calls `/block` (with the `email::subj:foo@bar.com:subject` thread-key conversation_id) is NOT addressed by this brief. If the frontend blocks with the thread-key form, the email_poller's suppression at `from_email` won't fire. Brief 261 fixes the LIST-filter gap by checking `get_blocked(email_address_extracted_from_thread_key)`, but the right long-term fix is to normalize the conversation_id at the API boundary. Out of scope for #30; documented as a known issue in the OUTPUT for a follow-up brief.

## Instructions

1. **Schema migration in `wtyj/shared/state_registry.py`** — extend the existing migration block at line 343 (where `blocked INTEGER` was added by Brief 220). Add two more `ALTER TABLE` statements, each wrapped in the same `try/except sqlite3.OperationalError: pass` pattern Brief 220 used:
   ```python
   try:
       conn.execute("ALTER TABLE conversation_status ADD COLUMN reason TEXT")
   except sqlite3.OperationalError:
       pass
   try:
       conn.execute("ALTER TABLE conversation_status ADD COLUMN blocked_by TEXT")
   except sqlite3.OperationalError:
       pass
   ```
   Place these immediately after the existing `blocked INTEGER` ALTER. Migration is idempotent — re-running on a DB that already has the columns is a no-op.

2. **Extend `set_blocked()` signature** at `state_registry.py:1855`:
   ```python
   def set_blocked(conversation_id: str, blocked: bool,
                    channel: str = "", reason: str = "",
                    blocked_by: str = "") -> None:
   ```
   - When `blocked=True`, INSERT/UPDATE `reason` + `blocked_by` columns alongside the existing `blocked` flag. Both default to empty string.
   - When `blocked=False` (unblock), clear `reason` + `blocked_by` (set to empty string) so the row doesn't carry stale audit fields. The block event itself is recorded in `bm_logger` events for history.
   - Update the SQL UPSERT at line 1867 to include the two new columns.

3. **Extend `list_blocked_conversations()`** at `state_registry.py:1889` to SELECT `reason` + `blocked_by` columns and include them in the returned dicts. **Preserve the existing camelCase keys for backward compatibility** (per the function's own docstring at line 1892: *"Each row carries camelCase keys: conversationId, channel, updatedAt"*). Brief 261 ADDS two camelCase fields, does NOT rename any existing ones:
   ```python
   # Existing Brief 220 fields (must remain unchanged):
   {
       "conversationId": "<id>",
       "channel": "<email/whatsapp/instagram_dm/facebook_dm>",
       "updatedAt": "<ISO timestamp from updated_at column>",
       # Brief 261 additions (camelCase to match the existing convention):
       "reason": "<spam/abusive/wrong_contact/other or empty>",
       "blockedBy": "<operator label or empty>",
   }
   ```
   Any existing dashboard caller that reads `conversationId` / `channel` / `updatedAt` continues to work. New callers can additionally read `reason` / `blockedBy`.

4. **Filter `wa_list_conversations` SQL** at `state_registry.py:1532` — change the LEFT JOIN WHERE clause from `WHERE cs.deleted IS NULL OR cs.deleted = 0` to `WHERE (cs.deleted IS NULL OR cs.deleted = 0) AND (cs.blocked IS NULL OR cs.blocked = 0)`. Blocked WhatsApp conversations now disappear from the active Inbox list (their history is preserved; the unblock path makes them reappear).

5. **Filter `email_list_conversations`** at `state_registry.py:1115`. The function iterates over email_thread_state.json threads. Add a per-thread check:
   - Extract the customer email from the thread_key (`thread_key.split(":", 2)[1]` gives `alice@x.com` for `subj:alice@x.com:invoice`).
   - If `get_blocked(customer_email)` returns True, skip the thread (continue to next).
   - Place the check immediately after the existing `if flags.get("deleted"): continue` line at 1157-1158.

6. **Extend `POST /messages/conversations/{conversation_id:path}/block`** at `dashboard/api.py:2639` to accept an optional JSON body:
   ```python
   class BlockRequest(BaseModel):
       reason: str = ""
       blocked_by: str = ""

   @router.post(...)
   async def block_conversation(conversation_id: str,
                                  req: BlockRequest = BlockRequest()):
       ...
       state_registry.set_blocked(conversation_id, True,
                                   reason=req.reason,
                                   blocked_by=req.blocked_by)
       bm_logger.log("conversation_blocked",
                     conversation_id=conversation_id[:50],
                     reason=req.reason[:50],
                     blocked_by=req.blocked_by[:50])
       return {"ok": True, "conversationId": conversation_id,
               "blocked": True,
               "reason": req.reason,
               "blocked_by": req.blocked_by}
   ```
   Body fields are optional — calling the endpoint without a body still works (Pydantic default). Backward compatible with any existing frontend wiring.

7. **Add `GET /blocked-senders` alias** at `dashboard/api.py` immediately after the existing `/settings/blocked-conversations` handler at line 2663. The new handler MUST return the SAME envelope shape as the existing endpoint (`{"conversations": [...]}` per `api.py:2668`) so the two are true aliases:
   ```python
   @router.get("/blocked-senders", dependencies=[Depends(_check_auth)])
   async def list_blocked_senders():
       """Brief 261: alias of /settings/blocked-conversations matching the
       endpoint shape from issue #30. Returns identical JSON to the
       existing /settings/blocked-conversations handler - same envelope
       (`{"conversations": [...]}`), same row shape (camelCase keys
       conversationId/channel/updatedAt, now extended with reason and
       blockedBy from Brief 261's set_blocked extension)."""
       return {"conversations": state_registry.list_blocked_conversations()}
   ```
   Keep `/settings/blocked-conversations` working unchanged (same handler, same shape, no breaking change). The two endpoints return byte-identical responses; the alias exists purely so SR's Replit frontend can adopt Calvin's preferred `/blocked-senders` path without a backend rename.

8. **Frontend contract** (documented in OUTPUT, not code): response shape, request shape for the POST body, the `/blocked-senders` GET endpoint, and the dashboard UX expectation Calvin already drafted (Block button next to archive/delete, confirmation dialog text, optional reason dropdown, Settings list view).

## Tests

Append 5 tests to `wtyj/tests/dashboard/test_220_block_conversation.py` (canonical per-module file for block-conversation tests; Brief 220 named it). If that file doesn't exist, create it as a NEW per-module file since this is the first block-related test addition under Brief 261. Verify with `ls wtyj/tests/dashboard/test_220*` at execution time.

1. **test_brief_261_set_blocked_persists_reason_and_blocked_by** — call `set_blocked("alice@x.com", True, channel="email", reason="spam", blocked_by="op1")`. Read back via `list_blocked_conversations()`. Assert the returned dict has `reason="spam"` AND `blocked_by="op1"`. Cleanup via `set_blocked(..., False)`.

2. **test_brief_261_unblock_clears_reason_and_blocked_by** — set_blocked with reason+blocked_by, then set_blocked(False), then check via `list_blocked_conversations()` — assert the conversation is no longer in the list (existing Brief 220 behavior preserved).

3. **test_brief_261_wa_list_conversations_filters_blocked** — seed a WA conversation via direct INSERT into `whatsapp_threads`, call `set_blocked(phone, True, channel="whatsapp")`, call `wa_list_conversations()`. Assert the phone is NOT in the returned list. Then unblock and assert it reappears.

4. **test_brief_261_email_list_conversations_filters_blocked** — monkeypatch `_get_email_state_path()` to a tmp file with a seeded thread keyed `subj:spam@spam.com:annoying`. Call `set_blocked("spam@spam.com", True, channel="email")`. Call `email_list_conversations()`. Assert the spam thread is NOT in the returned list. Unblock and assert it reappears.

5. **test_brief_261_block_endpoint_accepts_reason_and_blocked_by_body** — TestClient POST to `/dashboard/api/messages/conversations/{id}/block` with JSON body `{"reason": "abusive", "blocked_by": "calvin"}`. Assert 200 response with the body fields echoed. Then GET `/dashboard/api/blocked-senders` and assert the response is `{"conversations": [...]}` AND the row carries `reason="abusive"` AND `blockedBy="calvin"` (camelCase per Brief 261's preserved key naming).

## Success Condition

After Brief 261 deploys:
- `POST /messages/conversations/{id}/block` with `{"reason": "spam", "blocked_by": "op"}` body returns the new fields in the response.
- `GET /blocked-senders` returns rows wrapped as `{"conversations": [...]}` with each row carrying camelCase keys (`conversationId`, `channel`, `updatedAt`) plus the Brief 261 additions (`reason`, `blockedBy`). Returns byte-identical JSON to `GET /settings/blocked-conversations` (both endpoints active for backward compat).
- Blocked WhatsApp conversation: subsequent inbound is dropped (Brief 220, unchanged) AND the conversation no longer appears in the active Inbox list (Brief 261's filter).
- Blocked email sender: subsequent inbound is dropped (Brief 220, unchanged) AND threads for that sender no longer appear in the active Email Inbox list (Brief 261's filter).
- Unblocking restores the conversation to the active list AND clears the `reason` + `blocked_by` fields.
- All 4 production containers healthy post-deploy.
- Frontend contract documented in OUTPUT so SR can wire the Block button next to archive/delete.

## Rollback

```
ssh root@108.61.192.52 "bash /root/wtyj/scripts/rollback.sh all"
```

Canonical rollback per `wtyj/briefs/infra.md:188`. Restores `wtyj-agent:previous` image. Schema migration is idempotent + additive (ALTER TABLE ADD COLUMN), so the new columns survive a rollback on disk but are unused by the rolled-back code — harmless. If the rollback target image is itself bad: `git revert <Brief 261 source SHA> && git push origin main` — CI re-deploys without the gap-closing changes; Brief 220's existing behavior remains intact.
