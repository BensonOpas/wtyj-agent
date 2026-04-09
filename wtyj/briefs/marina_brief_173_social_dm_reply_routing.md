# BRIEF 173 — Fix social DM reply routing (any platform, not just WhatsApp)
**Status:** Draft | **Files:** whatsapp_client.py, test_173 (new) | **Depends on:** 159, 172 | **Blocks:** —

## Context

SR tested the dashboard "Send Reply via Marina" button on a semi-escalation from **Anne-Sophie Hammar** (a Facebook DM customer on Zernio) and got `500 Failed to send WhatsApp reply (Zernio account missing or send failed)`.

Real error from VPS logs (`bluemarlin.log`):

```
{"event": "zernio_dm_send_failed",
 "conversation_id": "69d7bf948890ddcf0a96...",
 "error": "[404] Conversation not found. Use the conversation id from the list conversations endpoint."}
```

The 404 is the key. The conversation_id is valid — Zernio sent it to us via webhook minutes earlier. The problem is the **account_id** being paired with it.

Root cause: `whatsapp_client.send_whatsapp_message` (Brief 159) calls `social_publisher.get_account_id("whatsapp")` unconditionally. Zernio's Inbox API scopes conversations to accounts. A conversation_id from the Facebook account does NOT exist in the WhatsApp account's inbox, so Zernio rejects the send with 404.

Probed `social_publisher.get_account_id` on the VPS — all four platforms are connected and active:

| platform | account_id | username |
|---|---|---|
| whatsapp | `69d41a7b7dea335c2bbdf250` | +1 515-500-5577 |
| facebook | `69bb24a66cb7b8cf4c8074aa` | BlueMarlin Tours Curacao |
| instagram | `69b8689d6cb7b8cf4c7846ff` | bluemarlincharters |
| twitter | `69d1a75f3343e77992317df7` | Bluemarlin2026 |

So we have the Facebook account_id already — we just never pair it with Facebook conversations on the send path.

## Why This Approach

**Rejected — propagate channel through `handle_incoming_whatsapp_message`.** Correct long-term but requires touching `webhook_server.py`, all 6 `create_pending_notification` sites in `social_agent.py`, the dashboard reply handler, and a data migration for existing escalations (which are all stored as `channel='whatsapp'`). Too much surface for a single fix.

**Rejected — have the dashboard reply handler look up the platform from the escalation row.** Same problem: the row says `whatsapp` for a Facebook customer. A data fix on top of a code fix.

**Chosen — fan out in `send_whatsapp_message`.** When the customer_id is a Zernio conversation_id, try the WhatsApp account first (unchanged behavior for WhatsApp customers), and if that fails with a not-found-type error, iterate through the other three social accounts (facebook, instagram, twitter) and try each. The first one that succeeds wins. Cache the winning account for this conversation so repeat replies use the known-good account on the fast path.

Benefits:
- Zero changes to escalation storage, webhook routing, or existing data
- Anne-Sophie's stuck escalation works on the next click without manual DB surgery
- Adds no channel-tracking complexity to social_agent
- ≤4 Zernio API calls per reply on a cold case, 1 on a warm case (cache hit)

Drawbacks:
- Channel field in escalations stays "wrong" for IG/FB/X customers. Acceptable — it's only used by the reply handler, which now fans out anyway. If we need correct channel data later (for analytics, filtering), that's a separate brief.
- No guarantee about which account a new conversation lives in until the first send attempt.

## Instructions

### Step 1: Refactor `send_whatsapp_message` in `whatsapp_client.py`

**File:** `wtyj/agents/social/whatsapp_client.py`

Add a module-level cache dict near the top of the file (after the existing helpers):

```python
# Brief 173: cache conversation_id → account_id for Zernio social DMs.
# Populated on first successful send. Cleared only on process restart.
_zernio_account_cache: dict = {}
```

Then replace the existing `send_whatsapp_message` function (currently lines ~106-123) with a version that tries each social account until one succeeds:

```python
def send_whatsapp_message(customer_id: str, text: str) -> bool:
    """Send a DM via Zernio Inbox API if customer_id is a Zernio conversation_id,
    otherwise fall back to the legacy Meta WhatsApp Cloud API. Returns True on success.

    Brief 173: Zernio conversation_ids are scoped to accounts (whatsapp / facebook /
    instagram / twitter), so we can't assume a conversation belongs to the WhatsApp
    account. Try the cached account for this conversation first (if known), then
    iterate through all active social accounts until one accepts the send.
    """
    if not _is_zernio_conversation_id(customer_id):
        return send_text_message(to=customer_id, text=text)

    # Deferred imports to avoid circular dependency with social_publisher
    from agents.social.zernio_dm_client import send_dm_reply
    from agents.social import social_publisher

    # Fast path: cache hit
    cached = _zernio_account_cache.get(customer_id)
    if cached:
        if send_dm_reply(customer_id, cached, text):
            return True
        # Cache miss (account may have been reconnected with a new id) — fall through
        _zernio_account_cache.pop(customer_id, None)

    # Cold path: try each social platform account in order. WhatsApp first because
    # it's the most common path in production, then the other Meta channels, then X.
    for platform in ("whatsapp", "facebook", "instagram", "twitter"):
        account_id = social_publisher.get_account_id(platform)
        if not account_id:
            continue
        if send_dm_reply(customer_id, account_id, text):
            _zernio_account_cache[customer_id] = account_id
            log("zernio_send_platform_resolved",
                conversation_id=customer_id[:20], platform=platform)
            return True

    log("zernio_send_all_platforms_failed", conversation_id=customer_id[:20])
    return False
```

The `send_dm_reply` function in `zernio_dm_client.py` already returns `False` on 404 (it catches the exception and logs `zernio_dm_send_failed`). No changes needed there — the fan-out loop will move on to the next platform automatically.

### Step 2: Tests

**File:** `wtyj/tests/social/test_173_dm_reply_routing.py`

```python
"""Tests for Brief 173 — social DM reply routing fans out across platforms."""
import os
from unittest.mock import patch

os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")

from agents.social import whatsapp_client


def _clear_cache():
    whatsapp_client._zernio_account_cache.clear()


@patch("agents.social.zernio_dm_client.send_dm_reply")
@patch("agents.social.social_publisher.get_account_id")
def test_send_succeeds_on_first_whatsapp_account(mock_get_account, mock_send):
    """Brief 173: WhatsApp-first path — if the WhatsApp account accepts, no fan-out."""
    _clear_cache()
    mock_get_account.side_effect = lambda p: {"whatsapp": "wa_acc"}.get(p, "")
    mock_send.return_value = True

    ok = whatsapp_client.send_whatsapp_message("a" * 24, "hello")
    assert ok is True
    # Should have stopped after the first successful send
    assert mock_send.call_count == 1
    assert mock_send.call_args[0][1] == "wa_acc"


@patch("agents.social.zernio_dm_client.send_dm_reply")
@patch("agents.social.social_publisher.get_account_id")
def test_send_fans_out_to_facebook_when_whatsapp_fails(mock_get_account, mock_send):
    """Brief 173: the Anne-Sophie case — Facebook conversation rejected by WhatsApp
    account, accepted by Facebook account."""
    _clear_cache()
    mock_get_account.side_effect = lambda p: {
        "whatsapp": "wa_acc",
        "facebook": "fb_acc",
        "instagram": "ig_acc",
        "twitter": "tw_acc",
    }.get(p, "")
    # First call (whatsapp) fails, second call (facebook) succeeds
    mock_send.side_effect = [False, True]

    ok = whatsapp_client.send_whatsapp_message("b" * 24, "hi from dashboard")
    assert ok is True
    assert mock_send.call_count == 2
    assert mock_send.call_args_list[0][0][1] == "wa_acc"
    assert mock_send.call_args_list[1][0][1] == "fb_acc"


@patch("agents.social.zernio_dm_client.send_dm_reply")
@patch("agents.social.social_publisher.get_account_id")
def test_send_returns_false_when_all_platforms_fail(mock_get_account, mock_send):
    _clear_cache()
    mock_get_account.side_effect = lambda p: f"{p}_acc"
    mock_send.return_value = False

    ok = whatsapp_client.send_whatsapp_message("c" * 24, "nope")
    assert ok is False
    assert mock_send.call_count == 4  # whatsapp, facebook, instagram, twitter


@patch("agents.social.zernio_dm_client.send_dm_reply")
@patch("agents.social.social_publisher.get_account_id")
def test_cache_hit_skips_fanout(mock_get_account, mock_send):
    """Brief 173: warm path — cached account is used directly, no fan-out."""
    _clear_cache()
    whatsapp_client._zernio_account_cache["d" * 24] = "fb_acc"
    mock_send.return_value = True

    ok = whatsapp_client.send_whatsapp_message("d" * 24, "warm")
    assert ok is True
    assert mock_send.call_count == 1
    assert mock_send.call_args[0][1] == "fb_acc"
    # get_account_id should not have been called at all
    assert mock_get_account.call_count == 0


@patch("agents.social.zernio_dm_client.send_dm_reply")
@patch("agents.social.social_publisher.get_account_id")
def test_cache_populated_after_fanout_success(mock_get_account, mock_send):
    _clear_cache()
    mock_get_account.side_effect = lambda p: f"{p}_acc"
    mock_send.side_effect = [False, False, True]  # fb is the winner

    conv_id = "e" * 24
    whatsapp_client.send_whatsapp_message(conv_id, "first send")
    assert whatsapp_client._zernio_account_cache[conv_id] == "instagram_acc"
```

### Step 3: Run tests + commit + deploy

```bash
python3 -m pytest wtyj/tests/social/test_173_dm_reply_routing.py -v
python3 -m pytest wtyj/tests/ -q --tb=line
```

Expected: 817 passing (812 baseline + 5 new).

```bash
git add wtyj/agents/social/whatsapp_client.py wtyj/tests/social/test_173_dm_reply_routing.py wtyj/briefs/marina_brief_173_social_dm_reply_routing.md
git commit -m "Brief 173: fan out Zernio send across platforms (fix FB/IG/X relay)"
git push origin main
ssh root@108.61.192.52 "cd /root && git pull && cd /root/clients/bluemarlin && docker compose down && docker compose build && docker compose up -d && cd /root/clients/adamus && docker compose down && docker compose up -d"
```

### Step 4: Have Benson retry the dashboard reply

Tell SR to click "Send Reply via Marina" on the Anne-Sophie Hammar Facebook escalation. It should succeed now. If it doesn't, pull the VPS logs for `zernio_send_platform_resolved` or `zernio_send_all_platforms_failed` to diagnose.

## Success Condition

1. `send_whatsapp_message` tries each of the 4 social Zernio platforms until one accepts
2. A successful send caches the winning account_id in `_zernio_account_cache`
3. Repeat sends for the same conversation hit the cache, no fan-out
4. 5 new tests pass, 817 total
5. Both containers healthy post-deploy

## Rollback

Revert the single commit. The cache is in-memory only, nothing to clean up.
