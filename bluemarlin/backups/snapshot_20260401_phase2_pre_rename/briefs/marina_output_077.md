# OUTPUT 077 — WhatsApp Operator Notification + Relay Bridge

**Brief:** `briefs/marina_brief_077_whatsapp_relay_bridge.md`
**Status:** Complete
**Date:** 2026-03-12

## What Was Done

All 8 steps executed as specified:

### Step 1 — pending_notifications table + CRUD (state_registry.py)
- Added `pending_notifications` table creation in `_get_conn()` after `whatsapp_booking_state`
- Added 4 CRUD functions: `create_pending_notification()`, `get_pending_notifications()`, `update_notification_status()`, `get_relay_by_token()`
- Header updated to `Last modified: Brief 077`

### Step 2 — Semi-escalation reverted to proper relay (social_agent.py)
- Added `import uuid`
- Replaced semi-escalation block (Step 7.5): now sets `awaiting_relay`, `relay_token` (12-char hex), `relay_question` instead of promoting to `fully_escalated`
- Builds `[RELAY-{token}]` subject line and operator alert body
- Inserts into `pending_notifications` via `create_pending_notification()`
- Sheets intent changed from `"semi_to_full_escalation"` to `"semi_escalation"`
- Internal note changed from `"Relay question (no relay bridge): ..."` to `"Relay question: ..."`

### Step 3 — Full escalation notification (social_agent.py)
- After existing Sheets logging + bm_logger call, builds escalation alert
- Subject: `[ESCALATION] {ref} - {name} (WhatsApp: {phone}) - {intents}`
- Body includes: `=== CUSTOMER ===`, `=== CHAT LOG ===`, `=== BOOKING FIELDS ===`, `=== MARINA'S INTERNAL NOTE ===`
- Inserts into `pending_notifications` with `notification_type='escalation'`

### Step 4 — Pending notification processing (email_poller.py)
- Added import: `from agents.social.whatsapp_client import send_text_message as wa_send_text_message`
- After `im.logout()`, iterates `get_pending_notifications()`, sends each via `smtp_send()`, marks as `"sent"`

### Step 5 — WhatsApp relay detection (email_poller.py)
- Extended relay detection: when email thread not found for relay token, checks `get_relay_by_token()`
- If channel=='whatsapp': gets WhatsApp state, reformulates via marina_agent, sends via `wa_send_text_message()`, stores in WhatsApp history, clears relay flags, marks notification as `"replied"`

### Step 6 — Headers updated
- `email_poller.py` and `social_agent.py` headers set to `Last modified: Brief 077`

### Step 7 — test_074 semi-escalation tests updated
- Test 1: Renamed to `test_semi_creates_relay`, asserts `awaiting_relay` instead of `fully_escalated`
- Test 2: Renamed to `test_semi_with_hold_cancels_and_creates_relay`, asserts `awaiting_relay`
- Test 3: Intent assertion changed to `"semi_escalation"`, internal_note to `"Relay question: ..."`
- Test 4: Docstring updated (no logic change needed)

### Step 8 — test_077_relay_bridge.py created (8 tests)
1. `test_create_pending_notification_round_trip` — CRUD round-trip
2. `test_get_relay_by_token` — lookup by token + None for non-existent
3. `test_update_notification_status` — pending → sent status transition
4. `test_semi_creates_relay_not_full` — relay flags set, not fully_escalated
5. `test_semi_inserts_pending_notification` — relay notification queued
6. `test_full_escalation_inserts_notification` — escalation notification queued
7. `test_semi_cancels_soft_hold` — soft hold cancelled + relay flags set
8. `test_escalation_alert_contains_chat_log` — body sections verified

### Additional fix — test_071 semi-escalation assertions
- 3 tests in test_071 also asserted `fully_escalated is True` for semi-escalation scenarios
- Updated: Test 3 (`test_semi_escalation_sets_relay_state`), Test 4 (`test_semi_escalation_cancels_soft_hold`), Test 5 (`test_semi_escalation_overrides_post_validate`)
- All now assert `awaiting_relay is True` and `"fully_escalated" not in state["flags"]`

## Test Results

```
$ python3 -m pytest tests/social/ -q
100 passed in 0.58s
```

- 8/8 new tests (test_077) pass
- 92/92 existing social tests pass (including updated test_071 and test_074)
- 2 pre-existing marina test collection errors (test_035, test_036) — unrelated to this brief

## Files Modified

| File | Change |
|------|--------|
| `shared/state_registry.py` | +pending_notifications table, +4 CRUD functions |
| `agents/social/social_agent.py` | Semi-escalation → proper relay, full escalation → notification |
| `agents/marina/email_poller.py` | +pending notification processing, +WhatsApp relay detection |
| `tests/social/test_077_relay_bridge.py` | **New** — 8 tests |
| `tests/social/test_074_semi_ratelimit.py` | Semi-escalation assertions updated |
| `tests/social/test_071_whatsapp_escalation.py` | Semi-escalation assertions updated |

## Anything Unexpected

- test_071 had 3 tests that also asserted `fully_escalated` for semi-escalation, not listed in the brief's Step 7. Required manual fix to pass regression.
- No other issues encountered.
