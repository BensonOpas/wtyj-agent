# BRIEF 186 — Channel adapter refactor (parsing layer, Zernio channels)
**Status:** Draft | **Files:** `wtyj/agents/social/webhook_server.py`, new `wtyj/agents/social/channels/*` | **Depends on:** — | **Blocks:** s32 (sender registry dispatch), s34 (email poller split)

## Context

`webhook_server.py:_process_zernio_event` builds platform-specific message dicts inline at two locations and passes them to `handle_incoming_whatsapp_message`:

- **WhatsApp via Zernio path** (`webhook_server.py:302-311`): builds an 8-key dict including 4 `_zernio_*` metadata fields, then routes through `_buffer_message`.
- **IG/FB/X DM path** (`webhook_server.py:334-338`): builds a 3-key dict (`from`, `text`, `from_name`) and calls `handle_incoming_whatsapp_message` directly.

The two dict shapes are different. Adding a new channel means adding another inline branch with another inline dict. Channel-specific construction logic is tangled into the routing function.

The blueprint (`wtyj/docs/the_blueprint.md`, Pattern 1: "Channel as a Pluggable Adapter") calls for each channel to be its own self-contained adapter that produces a normalized message. Brief 185's three reviewer rounds were direct evidence of the cost of this tangle: a single conceptual change ("store the real platform") required touching 15+ hardcoded `"whatsapp"` strings spread across `social_agent.py` because the channel info was scattered instead of owned by an adapter.

This brief introduces the adapter layer for the **parsing side only**, scoped to the 4 Zernio-routed channels (WhatsApp via Zernio, Instagram DM, Facebook DM, X/Twitter DM). Sender refactor, email poller split, conversation state machine — all out of scope.

## Why This Approach

**Two adapter classes, not four.** IG, FB, and X all build the same minimal dict today (`{from, text, from_name, channel, message_id}`). One generic `ZernioDMChannel` class serves all three. Only WhatsApp via Zernio is special — it needs `_zernio_*` metadata for the buffer round-trip (`_buffer_message` → `_flush_buffer` re-emits the dict in a separate function scope, so metadata must travel with the message). Two adapters cover all current behavior.

**Layered parsing, not single-step.** `parse_zernio_webhook` (in `zernio_dm_client.py`) stays as the first step (raw Zernio JSON → normalized Zernio dict). Adapters do the second step (Zernio dict → orchestrator dict). Two layers instead of one is intentional — `parse_zernio_webhook` is shared across all Zernio channels; adapters are channel-specific. Flattening would duplicate Zernio JSON parsing across every adapter. YAGNI on flattening.

**Dict shape is a compatible superset.** The dicts produced by the adapters add a top-level `channel` key that the inline dicts did not have, and `ZernioDMChannel` additionally adds `message_id` (the inline IG/FB/X dict had only `from`/`text`/`from_name`). These additions are safe: `handle_incoming_whatsapp_message` at `social_agent.py:171-173` reads only `from`/`text`/`from_name` from the message dict and ignores other keys. `_flush_buffer` at `webhook_server.py:194-220` reads `_zernio_*` metadata keys plus `message_id` for the `booking_flow=false` branch — both preserved in `WhatsAppZernioChannel`. No consumer downstream reads top-level `channel` or `message_id` from a message dict passed to the orchestrator (verified by grep). Future briefs can introduce a `TypedDict` or dataclass for the message shape, but that requires touching every consumer and is out of scope here.

**Default fallback for unknown channels.** Today `parse_zernio_webhook` produces `channel="unknown_dm"` for any platform Zernio sends that we don't recognize. Current code processes those messages with the same inline IG/FB/X branch. New code falls back to `ZernioDMChannel` via a `DEFAULT_ZERNIO_CHANNEL` reference — preserves current behavior (don't crash on unknown platforms).

### Rejected alternatives

1. **Bundle s30 (parsing) + s32 (sender registry) into one brief.** Rejected: bigger diff on the load-bearing webhook code, longer reviewer cycle, harder rollback. Better to ship parsing first as an incremental migration. Sender registry is a small follow-up brief once the adapter pattern is proven.

2. **One adapter class per platform (`InstagramChannel`, `FacebookChannel`, `TwitterChannel` separately).** Rejected: they all do the same thing today. YAGNI. Future brief can split if a real per-platform need emerges (e.g. different attachment handling).

3. **Replace dict with `TypedDict` / dataclass.** Rejected: requires touching every consumer of the message dict. Out of scope. Current consumers expect dicts; keep dicts.

4. **Touch `_buffer_message` / `_flush_buffer` / Meta WhatsApp path.** Rejected: Meta WhatsApp is `/webhooks/meta/whatsapp` → `_process_whatsapp_event` → `parse_webhook_payload`, a separate parsing pipeline that's archived (`infra.md` confirms Meta WhatsApp is in archived rollback state). Migrate it in a separate brief if/when we re-enable it.

5. **Touch the `handle_incoming_dm` path** (when `booking_flow: false`). Rejected: that path passes the raw `parse_zernio_webhook` output dict directly (`webhook_server.py:358`), which has a different shape than the orchestrator dict. Normalizing it would force `handle_incoming_dm` to either change its signature or get a separate adapter. Out of scope; only the orchestrator-bound path is normalized in this brief.

**Tradeoff carried:** the IG/FB/X DM path now goes through one extra function call (`adapter_cls.from_zernio(msg)`) for each inbound DM. Negligible cost — pure dict construction, no I/O — but technically slightly more allocation than the inline version.

## Instructions

### Step 1 — Create the channels directory and base class

Create `wtyj/agents/social/channels/base.py`:

```python
# wtyj/agents/social/channels/base.py
# Brief 186 — Channel adapter base class.
from abc import ABC, abstractmethod


class Channel(ABC):
    """Base class for channel adapters.

    A channel adapter knows how to convert a parsed Zernio webhook message
    (output of parse_zernio_webhook in zernio_dm_client.py) into the dict
    shape that handle_incoming_whatsapp_message consumes.
    """

    @classmethod
    @abstractmethod
    def from_zernio(cls, zernio_msg: dict) -> dict:
        """Convert a parse_zernio_webhook output dict into a message dict
        suitable for handle_incoming_whatsapp_message.

        Args:
            zernio_msg: dict with keys conversation_id, platform, channel,
                        sender_name, sender_id, text, message_id, account_id

        Returns:
            dict with keys: from, text, from_name, channel, message_id.
            WhatsApp via Zernio also includes: _zernio_conversation_id,
            _zernio_account_id, _zernio_channel, _zernio_sender_name (needed
            for the debounce buffer round-trip in _flush_buffer).
        """
```

### Step 2 — Create the WhatsApp via Zernio adapter

Create `wtyj/agents/social/channels/whatsapp_zernio.py`:

```python
# wtyj/agents/social/channels/whatsapp_zernio.py
# Brief 186 — Adapter for WhatsApp messages routed through Zernio.
# Includes _zernio_* metadata required for the debounce buffer round-trip.
from .base import Channel


class WhatsAppZernioChannel(Channel):
    """WhatsApp messages received via Zernio webhook.

    The output dict includes _zernio_* metadata because the message goes
    through the debounce buffer (_buffer_message → _flush_buffer) and the
    metadata is needed when the buffered message is later passed back to
    handle_incoming_whatsapp_message inside _flush_buffer's separate scope.
    """

    @classmethod
    def from_zernio(cls, zernio_msg: dict) -> dict:
        sender_name = zernio_msg.get("sender_name", "")
        conversation_id = zernio_msg["conversation_id"]
        return {
            "from": conversation_id,
            "text": zernio_msg.get("text", ""),
            "from_name": sender_name,
            "message_id": zernio_msg["message_id"],
            "channel": zernio_msg["channel"],
            "_zernio_conversation_id": conversation_id,
            "_zernio_account_id": zernio_msg["account_id"],
            "_zernio_channel": zernio_msg["channel"],
            "_zernio_sender_name": sender_name,
        }
```

### Step 3 — Create the generic Zernio DM adapter

Create `wtyj/agents/social/channels/zernio_dm.py`:

```python
# wtyj/agents/social/channels/zernio_dm.py
# Brief 186 — Generic adapter for Zernio DM channels (Instagram, Facebook,
# X/Twitter, and any future Zernio-routed DM platforms). DM channels do NOT
# include _zernio_* metadata because they are not buffered/debounced — the
# message is dispatched directly to handle_incoming_whatsapp_message inside
# the original _process_zernio_event function scope.
from .base import Channel


class ZernioDMChannel(Channel):
    """Generic adapter for Zernio DM channels (IG, FB, X/Twitter, etc.)."""

    @classmethod
    def from_zernio(cls, zernio_msg: dict) -> dict:
        return {
            "from": zernio_msg["conversation_id"],
            "text": zernio_msg.get("text", ""),
            "from_name": zernio_msg.get("sender_name", ""),
            "channel": zernio_msg["channel"],
            "message_id": zernio_msg["message_id"],
        }
```

### Step 4 — Create the registry

Create `wtyj/agents/social/channels/__init__.py`:

```python
# wtyj/agents/social/channels/__init__.py
# Brief 186 — Channel adapter registry.
from .base import Channel
from .whatsapp_zernio import WhatsAppZernioChannel
from .zernio_dm import ZernioDMChannel

# Maps the "channel" field from parse_zernio_webhook output to an adapter
# class. Channel names match what zernio_dm_client.py:85 produces:
#   - "whatsapp" for platform="whatsapp"
#   - "{platform}_dm" for any other platform (e.g. "instagram_dm")
ZERNIO_CHANNELS = {
    "whatsapp": WhatsAppZernioChannel,
    "instagram_dm": ZernioDMChannel,
    "facebook_dm": ZernioDMChannel,
    "twitter_dm": ZernioDMChannel,
}

# Default adapter for unknown channels (e.g. a new Zernio platform we haven't
# explicitly registered). Falls back to the generic DM adapter so the system
# does not crash on unfamiliar inbound messages.
DEFAULT_ZERNIO_CHANNEL = ZernioDMChannel

__all__ = [
    "Channel",
    "WhatsAppZernioChannel",
    "ZernioDMChannel",
    "ZERNIO_CHANNELS",
    "DEFAULT_ZERNIO_CHANNEL",
]
```

### Step 5 — Wire the registry into `webhook_server.py:_process_zernio_event`

Add the import alongside the existing `from agents.social.zernio_dm_client import ...` line near `webhook_server.py:18`:

```python
from agents.social.channels import ZERNIO_CHANNELS, DEFAULT_ZERNIO_CHANNEL
```

**Replace the inline WhatsApp dict construction at `webhook_server.py:302-311`** (the `_wa_msg = {...}` literal inside the `if msg["platform"] == "whatsapp":` block at line 301). Current code builds `_wa_msg` with 8 hardcoded keys. New code:

```python
if msg["platform"] == "whatsapp":
    adapter_cls = ZERNIO_CHANNELS.get(channel, DEFAULT_ZERNIO_CHANNEL)
    _wa_msg = adapter_cls.from_zernio(msg)
    send_typing_indicator(conversation_id, account_id)
    _buffer_message(_wa_msg)
    return
```

The adapter call replaces lines 302-311 (the inline `_wa_msg = {...}` literal). The `send_typing_indicator` and `_buffer_message` calls (currently lines 312-313) are unchanged.

**Replace the inline IG/FB/X dict construction at `webhook_server.py:334-338`** (the `orchestrator_msg = {...}` literal inside the `if _booking_flow_on:` branch — line 339 is the `handle_incoming_whatsapp_message(...)` call which is also replaced with the new pattern below). New code:

```python
if _booking_flow_on:
    adapter_cls = ZERNIO_CHANNELS.get(channel, DEFAULT_ZERNIO_CHANNEL)
    orchestrator_msg = adapter_cls.from_zernio(msg)
    reply_text = handle_incoming_whatsapp_message(orchestrator_msg, channel=channel)
    state_registry.dm_store_message(
        conversation_id=conversation_id,
        channel=channel,
        role="user",
        text=text,
        sender_name=msg["sender_name"],
    )
```

Lines 340-347 (`state_registry.dm_store_message(...)`) are unchanged.

### Step 6 — Verify nothing else changed

Do NOT touch:
- `_buffer_message`, `_flush_buffer`, `_get_phone_lock`, `_maybe_run_cleanup` — buffer/lock infrastructure
- The `else: # Q&A only — use DM agent` branch at `webhook_server.py:348-358` — DM agent path uses raw Zernio dict, out of scope
- `parse_zernio_webhook` in `zernio_dm_client.py` — first parsing layer stays put
- `handle_incoming_whatsapp_message`, `handle_incoming_dm`, anything in `social_agent.py`
- Anything in `whatsapp_client.py` or the Meta WhatsApp `/webhooks/meta/whatsapp` path
- `email_poller.py`

## Tests

Create `wtyj/tests/social/test_186_channel_adapters.py` with 5 tests:

### Test 1 — `WhatsAppZernioChannel.from_zernio` produces full metadata

Given a Zernio dict with `platform="whatsapp"`, `conversation_id="conv_abc"`, `text="hello"`, `sender_name="Test User"`, `message_id="msg_123"`, `account_id="acct_456"`, `channel="whatsapp"`, call `WhatsAppZernioChannel.from_zernio(zernio_msg)` and assert the result has:
- `from == "conv_abc"`
- `text == "hello"`
- `from_name == "Test User"`
- `message_id == "msg_123"`
- `channel == "whatsapp"`
- `_zernio_conversation_id == "conv_abc"`
- `_zernio_account_id == "acct_456"`
- `_zernio_channel == "whatsapp"`
- `_zernio_sender_name == "Test User"`

### Test 2 — `ZernioDMChannel.from_zernio` produces minimal dict (no `_zernio_*` keys)

Given a Zernio dict with `platform="instagram"`, `channel="instagram_dm"`, `conversation_id="conv_ig"`, `text="hi there"`, `sender_name="IG User"`, `message_id="msg_ig_1"`, `account_id="acct_ig"`, call `ZernioDMChannel.from_zernio(zernio_msg)` and assert:
- `from == "conv_ig"`
- `text == "hi there"`
- `from_name == "IG User"`
- `channel == "instagram_dm"`
- `message_id == "msg_ig_1"`
- No keys starting with `_zernio_` are present in the result (use `assert not any(k.startswith("_zernio_") for k in result)`)

### Test 3 — Registry maps the four channels correctly

Import `ZERNIO_CHANNELS` and `WhatsAppZernioChannel`, `ZernioDMChannel`. Assert:
- `ZERNIO_CHANNELS["whatsapp"] is WhatsAppZernioChannel`
- `ZERNIO_CHANNELS["instagram_dm"] is ZernioDMChannel`
- `ZERNIO_CHANNELS["facebook_dm"] is ZernioDMChannel`
- `ZERNIO_CHANNELS["twitter_dm"] is ZernioDMChannel`

This is a registry behavior test, not a structural string-grep — it verifies the registry is wired up correctly so the dispatch works at runtime.

### Test 4 — Unknown channel falls back to `DEFAULT_ZERNIO_CHANNEL`

Import `ZERNIO_CHANNELS`, `DEFAULT_ZERNIO_CHANNEL`, `ZernioDMChannel`. Assert:
- `ZERNIO_CHANNELS.get("totally_new_dm", DEFAULT_ZERNIO_CHANNEL) is ZernioDMChannel`
- Calling `DEFAULT_ZERNIO_CHANNEL.from_zernio({...})` with a fake unknown-platform Zernio dict (`channel="newplatform_dm"`) returns a dict with the standard 5 keys and no crash.

### Test 5 — Integration: `_process_zernio_event` dispatches via the registry

Mock `handle_incoming_whatsapp_message` (in `agents.social.webhook_server`), `send_dm_reply`, `send_typing_indicator`, and `state_registry.dm_store_message`. Follow the cache-restore + `_cleanup(conv_id)` pattern from `test_138_dm_booking.py:69-92` (use a unique conversation_id like `conv_186_ig` and a unique `message_id` to avoid the dedup table colliding with prior runs; restore `config_loader._cache["features"]["booking_flow"]` to its original value in a `finally:` block). Build a real Zernio webhook payload for an Instagram DM (using the same payload-building helper pattern as `test_138_dm_booking.py:_make_zernio_payload`):

```python
payload = {
    "event": "message.received",
    "account": {"id": "acct_ig"},
    "data": {
        "conversationId": "conv_186_ig",
        "id": "msg_186_1",
        "text": "Hello from Instagram",
        "sender": {"name": "Instagram User"},
        "platform": "instagram",
    },
}
```

Set `booking_flow=True` in config_loader cache. Call `_process_zernio_event(payload)`. Assert that `handle_incoming_whatsapp_message` was called exactly once with:
- First positional arg has `from == "conv_186_ig"`, `text == "Hello from Instagram"`, `from_name == "Instagram User"`, `channel == "instagram_dm"`
- `channel="instagram_dm"` was passed as the kwarg

This verifies the adapter was actually invoked and produced the expected dict shape, not just that the registry has the right entries (test 3 covers that separately).

All 5 tests should pass with the new code and fail without it (negative control: Tests 3 and 5 would fail if the registry isn't imported; Tests 1, 2, 4 would fail if the adapter classes don't exist or produce wrong shapes).

## Success Condition

`python3 -m pytest wtyj/tests/ -q` reports **876 passed / 0 failed** (871 baseline + 5 new), and `_process_zernio_event` produces byte-identical message dicts to the pre-refactor inline version when given the same Zernio payloads (verified by Test 5's assertion that `handle_incoming_whatsapp_message` is called with the expected dict).

## Rollback

`git revert <commit>`. The new `wtyj/agents/social/channels/` directory is purely additive — reverting removes it. The `webhook_server.py` changes are localized to two ~6-line blocks plus one import line. Reverting restores the inline dict construction. No data migration, no state changes, no third-party API impact. Container restart picks up the reverted code in the next deploy cycle.
