# BRIEF 185 — Store actual platform in conversation data and escalation notifications
**Status:** Draft | **Files:** `webhook_server.py`, `social_agent.py` | **Depends on:** — | **Blocks:** —

## Context

SR's bug report: IG/FB/X DMs all show as "whatsapp" in escalation notifications and conversation context, because `social_agent.py:handle_incoming_whatsapp_message()` hardcodes `'whatsapp'` in every `create_pending_notification()` call (`social_agent.py:258`, `274`, `490`, `588`, `677`, `711`, `759`, `890`) and in the `marina_agent.process_message()` channel parameter (`social_agent.py:230`, `355`).

The Zernio webhook already parses the correct platform — `zernio_dm_client.py:85` sets `channel` to `"instagram_dm"`, `"facebook_dm"`, `"twitter_dm"`, or `"whatsapp"`. And `webhook_server.py:297` reads `msg["channel"]` correctly for `dm_store_message()` storage. But `social_agent.py` never receives this value — `handle_incoming_whatsapp_message()` doesn't accept a channel/platform parameter, so it defaults to `"whatsapp"` everywhere.

The DM message storage path (`dm_store_message` calls in `webhook_server.py:341-368`) is already correct — it passes `channel` from the parsed message. The bug is specifically in `social_agent.py`'s notification creation and Marina's channel context.

## Why This Approach

**Considered:** Adding a `platform` column to `pending_notifications` table. Rejected — the table already has a `channel` column that serves this purpose; we just need to pass the right value through.

**Considered:** Renaming `handle_incoming_whatsapp_message` to a generic name. Rejected for this brief — the function is called from 3 places (`webhook_server.py:202`, `241`, `339`) and renaming is a larger refactor that belongs in the channel adapter brief. The name is misleading but changing it here would bloat the diff.

**Chosen approach:** Add an optional `channel` parameter to `handle_incoming_whatsapp_message()` with default `"whatsapp"` (backward compatible). Pass it through to every `create_pending_notification()` call and the `marina_agent.process_message()` call. Update the two call sites in `webhook_server.py` that handle non-WhatsApp Zernio DMs to pass the actual channel.

## Instructions

### Step 1: Update `social_agent.py:handle_incoming_whatsapp_message` signature

At `social_agent.py`, add `channel="whatsapp"` parameter to the function signature. The function currently takes `msg` dict as its only parameter (at the function definition).

### Step 2: Replace hardcoded `'whatsapp'` in social_agent.py

**A. Notification channel parameter** — every `create_pending_notification(...)` call that passes `'whatsapp'` as the channel argument should pass the `channel` parameter instead. 8 call sites:
- `social_agent.py:258`, `274`, `490`, `588`, `677`, `711`, `759`, `890`

**B. Marina channel parameter** — update the two `marina_agent.process_message()` calls:
- `social_agent.py:230` — escalated path: `channel="whatsapp"` → `channel=channel`
- `social_agent.py:355` — main path: `channel="whatsapp"` → `channel=channel`

**C. Notification body/subject strings** — replace all hardcoded `"WhatsApp"` text in notification subject and body strings with a human-readable label derived from the channel. Add a helper at the top of the function:
```python
_channel_label = {"whatsapp": "WhatsApp", "instagram_dm": "Instagram", "facebook_dm": "Facebook", "twitter_dm": "X/Twitter"}.get(channel, channel)
```
Then replace every `"WhatsApp: {phone}"` and `"(WhatsApp: {phone})"` in notification strings with `f"{_channel_label}: {phone}"`. 10 occurrences at lines: `247`, `275`, `491`, `577`, `663`, `667`, `698`, `702`, `760`, `891`.

**D. Sheets logging** — replace hardcoded `"subject": "WhatsApp"` in `sheets_writer.log_escalation()` calls with `"subject": _channel_label`. 4 occurrences at lines: `592`, `637`, `770`, `840`.

**E. Customer interaction logging** — at `social_agent.py:364`, `customer_record_interaction` passes hardcoded `"whatsapp"` as channel and `"WhatsApp/DM:"` in the summary. Replace with `channel` and `f"{_channel_label}/DM:"`.

### Step 3: Pass channel from webhook_server.py

In `webhook_server.py:_process_zernio_event`, at the two places `handle_incoming_whatsapp_message` is called for non-WhatsApp platforms:

**Booking flow path** (`webhook_server.py:339`): Change from:
```python
reply_text = handle_incoming_whatsapp_message(orchestrator_msg)
```
To:
```python
reply_text = handle_incoming_whatsapp_message(orchestrator_msg, channel=channel)
```

**WhatsApp debounce path** in `_flush_buffer` (`webhook_server.py:202`): This path already checks `if _zernio_conv:` and has `_zernio_channel`. Change from:
```python
reply_text = handle_incoming_whatsapp_message(final_msg)
```
To:
```python
reply_text = handle_incoming_whatsapp_message(final_msg, channel=_zernio_channel)
```

The legacy Meta WhatsApp path (`webhook_server.py:241`) doesn't need changes — it correctly defaults to `"whatsapp"`.

### Step 4: No schema changes

The `channel` column already exists in both `whatsapp_threads` and `pending_notifications`. No migration needed. The stored values change from always `"whatsapp"` to the actual platform (`"whatsapp"`, `"instagram_dm"`, `"facebook_dm"`, `"twitter_dm"`).

## Tests

1. **Instagram DM escalation uses instagram_dm channel and label** — Mock `marina_agent.process_message` to return an escalation result. Call `handle_incoming_whatsapp_message(msg, channel="instagram_dm")`. Assert `create_pending_notification` was called with `channel="instagram_dm"` AND the notification body/subject contains `"Instagram"` not `"WhatsApp"`.

2. **Facebook DM relay notification uses facebook_dm** — Mock process_message to return a semi-escalation (relay). Call with `channel="facebook_dm"`. Assert notification channel is `"facebook_dm"` and body contains `"Facebook"`.

3. **Default channel is whatsapp when not specified** — Call `handle_incoming_whatsapp_message(msg)` without channel parameter. Assert notification uses `"whatsapp"` and body contains `"WhatsApp"`. Backward compatibility.

4. **Marina receives correct channel** — Mock `marina_agent.process_message`. Call `handle_incoming_whatsapp_message(msg, channel="twitter_dm")`. Assert `process_message` was called with `channel="twitter_dm"`.

## Success Condition

After deploying, an Instagram DM that triggers an escalation creates a `pending_notification` row with `channel='instagram_dm'` instead of `channel='whatsapp'`. Dashboard escalation cards show the correct channel.

## Rollback

`git revert <commit>`. All notification channels revert to hardcoded `"whatsapp"`. No data migration needed — old rows with wrong channel values remain (cosmetic, not breaking).
