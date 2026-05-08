# OUTPUT 220 — Block conversation (per-conversation runtime drop)

## What was done

Added `conversation_status.blocked INTEGER NOT NULL DEFAULT 0` via idempotent ALTER (placed adjacent to Brief 213's `ai_muted` + `human_takeover_at` ALTERs, not BEFORE the table CREATE — Brief 213's ALTERs already handled that ordering for the same table). Three new state_registry helpers (`set_blocked`, `get_blocked`, `list_blocked_conversations`) using the same UPSERT pattern as `set_ai_muted`. Three new dashboard endpoints in api.py (`POST /messages/conversations/:id/block`, `POST /.../unblock`, `GET /settings/blocked-conversations`) placed adjacent to the takeover/handback endpoints from Brief 213. Drop checks added at all 4 customer-message ingestion paths: Zernio DM ingestion (`_process_zernio_event` after the existing ignored_phones loop), Zernio-WhatsApp `_flush_buffer` branch (BEFORE the ai_muted check so blocked beats muted), Meta-legacy WhatsApp branch (same ordering rule), and email_poller's per-uid loop (BEFORE the inline `th["messages"].append(...)` so blocked emails never enter thread state). All 4 sites use the SAME helper call: `state_registry.get_blocked(conversation_id)`. Different from `ai_muted` semantically: ai_muted stores then skips Marina (operator still sees the message); blocked drops entirely (operator NEVER sees it unless they explicitly unblock).

## Tests

1022 passing / 0 failures (1016 baseline + 6 new).

## Unexpected findings

Pre-existing test_208's `test_non_ignored_phone_proceeds` regressed because the new block check sits AFTER the ignored_phones check — the test patches `state_registry` with `MagicMock`, so `state_registry.get_blocked(...)` returned a truthy MagicMock object instead of the expected False, and the new check dropped the otherwise-allowed message. Fix: added `mock_state.get_blocked.return_value = False` stub to `test_208_phone_block_and_session.py:test_non_ignored_phone_proceeds`. Disclosed in the test's inline comment naming Brief 220 as the reason. test_208 file isn't in this brief's Files header — minor scope creep, but the fix is a one-line stub addition that documents the regression-guard relationship between the two briefs.

## Deployment

Pending — commit/push/deploy in step 16.
