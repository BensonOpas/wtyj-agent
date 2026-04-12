# BRIEF 187 — Sender registry: dispatch replies via Zernio adapter (Pattern 3)
**Status:** Draft | **Files:** `wtyj/agents/social/webhook_server.py`, new `wtyj/agents/social/senders/*`, `wtyj/tests/social/test_138_dm_booking.py`, `wtyj/tests/social/test_143_zernio_whatsapp.py`, `wtyj/tests/social/test_186_channel_adapters.py` (mock target updates) | **Depends on:** Brief 186 (channel adapter pattern) | **Blocks:** s34 (email poller split — will use the same sender registry)

## Context

Brief 186 introduced channel adapters for the **parsing** side (`wtyj/agents/social/channels/`) — webhook payloads now flow through a `ZERNIO_CHANNELS` registry to produce normalized message dicts. The **sending** side is still inline. Two call sites in `webhook_server.py` directly call `send_dm_reply(conversation_id, account_id, text)` from `zernio_dm_client.py`:

- `webhook_server.py:233` — inside `_flush_buffer`'s `if reply_text:` block, the WhatsApp via Zernio path. Both the booking-flow-on and booking-flow-off branches funnel here.
- `webhook_server.py:352` — inside `_process_zernio_event`'s `if reply_text:` block, the IG/FB/X DM path. Same `if reply_text:` pattern.

Both call sites have **byte-for-byte identical signatures**: `send_dm_reply(conversation_id, account_id, reply_text)`. The variable names differ (`_zernio_conv`/`_zernio_acct` vs. `conversation_id`/`account_id`) but the function args are the same.

The blueprint Pattern 3 ("Registry-Based Dispatch", `wtyj/docs/the_blueprint.md`) calls for a `SENDERS = {"whatsapp": WhatsAppSender, ...}` registry plus one `send_reply(...)` function the brain calls without knowing how each channel sends. This brief implements that pattern for the sender side, scoped tightly to Zernio-routed channels — symmetric to Brief 186's parser-side scope.

## Why This Approach

**One adapter class, not four.** All four Zernio-routed channels (WhatsApp via Zernio, Instagram DM, Facebook DM, X/Twitter DM) send through the SAME function — `send_dm_reply` in `zernio_dm_client.py`, which calls Zernio's unified `client.inbox.send_inbox_message(...)` API. There is no per-channel sending behavior to differentiate. So a single `ZernioSender` class wrapping `send_dm_reply` covers all four registry entries. This mirrors how `ZernioDMChannel` handles IG/FB/X identically on the parser side.

**The dispatcher signature is `send_reply(channel, conversation_id, account_id, text)`.** Channel-first because it's the dispatch key. `account_id` is a required parameter because Zernio's API requires it (the conversation_id alone is not enough — the account_id identifies WHICH connected social account the conversation belongs to). Future briefs that add a non-Zernio sender (e.g. Telegram, or a vendor that doesn't use account_id) can either ignore the parameter or refactor the signature when there's a real second sender to compare against. YAGNI on premature genericization.

**Wrap, don't replace.** `ZernioSender.send` calls the existing `send_dm_reply` function rather than reimplementing the Zernio API call. The existing function has battle-tested error handling, logging, and the `_get_client()` initialization. Wrapping preserves all of that.

**Two call sites updated, none added.** Each call site swaps `send_dm_reply(conv, acct, text)` for `send_reply(channel, conv, acct, text)`. Net diff: ~6 lines changed in webhook_server.py + 1 added import. The new `senders/` package adds ~50 lines of new code across 3 files plus a registry init.

### Rejected alternatives

1. **Bundle s31 (state machine) into this brief.** Rejected: state machine is independent of dispatch and a much bigger change (touches `fully_escalated`, `awaiting_relay`, `pending_notifications`, multiple consumers). Would balloon the brief and the diff. Keep s32 small and ship it; s31 is its own brief.
2. **Refactor `send_text_message` (Meta WhatsApp legacy) into the registry.** Rejected: Meta WhatsApp direct API is the archived rollback path per `infra.md`. The call site at `webhook_server.py:245` is inside the legacy `else: # Meta WhatsApp (legacy)` branch and reaches a different sender (`send_text_message(to=phone, text=...)` vs. `send_dm_reply(conv_id, account_id, text)`). Including it would force the dispatcher signature to either be polymorphic on `to` vs. `(conv_id, account_id)` OR require a second adapter class — both add complexity for a code path that may be deleted entirely if Meta direct is never re-enabled. Leave it inline; if Meta direct is ever restored, it can be migrated in its own brief.
3. **Refactor email sender (`email_poller.py`) into the registry.** Rejected: email sending lives inside the 1400-line `email_poller.py` monolith. Extracting it requires understanding the orchestrator/integrations split that subtask **s34** is going to do. Trying to do it now creates a coordination problem with s34. Better: leave email sending alone in this brief, then s34 wires `email_poller`'s sender into the registry as part of its split.
4. **Function-based registry (no classes).** Rejected: a dict mapping channel name → function works for the immediate need (`SENDERS = {"whatsapp": send_dm_reply, ...}`), but it doesn't extend cleanly when a future sender needs initialization state, multiple methods, or differs in shape (e.g. an `EmailSender` that holds an SMTP client connection across calls). Class-based registry mirrors the channel adapter pattern from Brief 186, keeps the symmetry, and gives a natural home for future polymorphism. The cost is ~10 extra lines (one class wrapping a function) — acceptable.
5. **Skip `Sender` ABC, just have `ZernioSender` with no base class.** Rejected: the ABC documents the contract for any future sender (`send(conversation_id, account_id, text) -> bool`) and matches the `Channel` ABC pattern from Brief 186. Same trivial cost (~15 lines for `base.py`), same symmetry benefit.

**Tradeoff carried:** the dispatcher adds one function-call indirection (`send_reply` → `ZernioSender.send` → `send_dm_reply`) per outgoing reply. Cost is negligible (no I/O, no allocation beyond a class lookup), but technically more frames in a stack trace if anything throws.

## Instructions

### Step 1 — Create the senders directory and base class

Create `wtyj/agents/social/senders/base.py`:

```python
# wtyj/agents/social/senders/base.py
# Brief 187 — Sender adapter base class.
from abc import ABC, abstractmethod


class Sender(ABC):
    """Base class for outbound message sender adapters.

    A sender knows how to deliver a reply text to a customer conversation
    on a specific channel. The dispatcher (send_reply in __init__.py) picks
    a sender by channel name and delegates to its send() classmethod.
    """

    @classmethod
    @abstractmethod
    def send(cls, conversation_id: str, account_id: str, text: str) -> bool:
        """Send a reply to the given conversation.

        Args:
            conversation_id: the platform's conversation identifier
                (Zernio conversation hex string for IG/FB/X DMs and Zernio
                WhatsApp; phone number for Meta WhatsApp direct).
            account_id: the connected social account identifier (required
                for Zernio so it knows which account is sending; may be
                ignored by senders that don't need it).
            text: the reply text to deliver.

        Returns:
            True on successful send, False otherwise. Errors are logged by
            the underlying transport, not raised.
        """
```

### Step 2 — Create the Zernio sender adapter

Create `wtyj/agents/social/senders/zernio.py`:

```python
# wtyj/agents/social/senders/zernio.py
# Brief 187 — Sender adapter wrapping zernio_dm_client.send_dm_reply.
# All Zernio-routed channels (WhatsApp via Zernio, Instagram DM, Facebook DM,
# X/Twitter DM) use the same Zernio Inbox API endpoint, so a single class
# covers all four registry entries.
from .base import Sender
from agents.social.zernio_dm_client import send_dm_reply


class ZernioSender(Sender):
    """Sends replies via Zernio's Inbox API (covers all Zernio-routed channels)."""

    @classmethod
    def send(cls, conversation_id: str, account_id: str, text: str) -> bool:
        return send_dm_reply(conversation_id, account_id, text)
```

### Step 3 — Create the registry and dispatcher

Create `wtyj/agents/social/senders/__init__.py`:

```python
# wtyj/agents/social/senders/__init__.py
# Brief 187 — Sender registry + dispatcher.
from .base import Sender
from .zernio import ZernioSender

# Maps channel name (matches parse_zernio_webhook output's "channel" field
# and the ZERNIO_CHANNELS registry from Brief 186) to a Sender class.
# All four Zernio-routed channels share ZernioSender because they all use
# the same Zernio Inbox API to deliver replies.
SENDERS: dict[str, type[Sender]] = {
    "whatsapp": ZernioSender,
    "instagram_dm": ZernioSender,
    "facebook_dm": ZernioSender,
    "twitter_dm": ZernioSender,
}

# Default sender for unknown channels (mirrors DEFAULT_ZERNIO_CHANNEL from
# the parser registry — preserves "process anything Zernio gives us" behavior).
DEFAULT_SENDER: type[Sender] = ZernioSender


def send_reply(channel: str, conversation_id: str, account_id: str, text: str) -> bool:
    """Dispatch a reply to the right sender based on channel name.

    This is the single public entry point for sending outbound replies. Call
    sites should use this instead of calling channel-specific sender functions
    (like send_dm_reply) directly, so the registry stays the source of truth
    for which transport handles which channel.
    """
    sender_cls = SENDERS.get(channel, DEFAULT_SENDER)
    return sender_cls.send(conversation_id, account_id, text)


__all__ = ["Sender", "ZernioSender", "SENDERS", "DEFAULT_SENDER", "send_reply"]
```

### Step 4 — Wire `send_reply` into `webhook_server.py`

Add the import alongside the existing `from agents.social.channels import ...` line near `webhook_server.py:20`:

```python
from agents.social.senders import send_reply
```

**Replace the inline `send_dm_reply` call at `webhook_server.py:233`** (inside `_flush_buffer`'s `if reply_text:` block, the Zernio WhatsApp path). Current code:

```python
if reply_text:
    send_dm_reply(_zernio_conv, _zernio_acct, reply_text)
    state_registry.dm_store_message(
        ...
    )
```

New code:

```python
if reply_text:
    send_reply(_zernio_channel, _zernio_conv, _zernio_acct, reply_text)
    state_registry.dm_store_message(
        ...
    )
```

The `state_registry.dm_store_message(...)` call (lines 234-239) is unchanged. Only the function name and the added `_zernio_channel` first argument change.

**Replace the inline `send_dm_reply` call at `webhook_server.py:352`** (inside `_process_zernio_event`'s `if reply_text:` block, the IG/FB/X DM path). Current code:

```python
if reply_text:
    # Send reply via Zernio
    send_dm_reply(conversation_id, account_id, reply_text)
    # Store assistant reply
    state_registry.dm_store_message(
        ...
    )
```

New code:

```python
if reply_text:
    # Send reply via the sender registry (Brief 187 — dispatched by channel)
    send_reply(channel, conversation_id, account_id, reply_text)
    # Store assistant reply
    state_registry.dm_store_message(
        ...
    )
```

The `state_registry.dm_store_message(...)` call (lines 354-359) is unchanged. The comment at line 351 is updated to reflect the new dispatch pattern.

### Step 5 — Update existing test mocks from `send_dm_reply` → `send_reply`

After Steps 1-4, webhook_server.py no longer calls `send_dm_reply` directly — it calls `send_reply`. Existing tests that mock `agents.social.webhook_server.send_dm_reply` will silently stop intercepting the send path. The mock would patch a name that's never called, letting the real `send_dm_reply` (via `ZernioSender.send`) fire unpatched during tests.

**In these 3 test files (11 tests total):**
- `wtyj/tests/social/test_138_dm_booking.py` — 7 tests (every test that has `@patch("agents.social.webhook_server.send_dm_reply")`)
- `wtyj/tests/social/test_143_zernio_whatsapp.py` — 3 tests
- `wtyj/tests/social/test_186_channel_adapters.py` — 1 test (test_process_zernio_event_dispatches_via_registry)

**Make two mechanical changes:**

**A. Replace the mock decorator** in every affected test:
```python
# OLD:
@patch("agents.social.webhook_server.send_dm_reply")
# NEW:
@patch("agents.social.webhook_server.send_reply")
```

**B. Shift positional arg assertions by +1** in any test that asserts on `mock_send.call_args[0]`. `send_reply` has `channel` as its first positional argument, so:
- `args[0]` was `conversation_id` → now `args[1]`
- `args[1]` was `account_id` → now `args[2]`
- `args[2]` was `reply_text` → now `args[3]`

For tests that only call `mock_send.assert_called_once()` or `mock_send.assert_not_called()` (no positional assertions), only change A is needed.

For `test_138_dm_booking.py::test_dm_reply_sent_via_zernio` specifically — this test asserts on all 3 positional args. After the shift, it should assert: `args[0]` is the channel string (e.g. `"instagram_dm"` or `"whatsapp"` depending on the test's payload platform), `args[1]` is `conv_id`, `args[2]` is `"acc_123"`, `args[3]` is `"Booking reply"`.

### Step 6 — Do NOT touch

- The `send_dm_reply` function in `zernio_dm_client.py` — `ZernioSender` wraps it; both keep working in parallel during the migration. Future briefs can deprecate the direct callable if no other code uses it (but `send_typing_indicator` and other Zernio helpers still live in `zernio_dm_client.py`, so the file stays).
- The existing `from agents.social.zernio_dm_client import ... send_dm_reply ...` import in `webhook_server.py:18` — leave it alone. After this brief, `send_dm_reply` is no longer used inside `webhook_server.py`, but removing it from the import line is a separate cleanup. Keep this brief surgical.
- `send_text_message(to=phone, text=reply_text)` at `webhook_server.py:245` (Meta WhatsApp legacy path inside the `else:` branch) — out of scope, archived path.
- Anything in `email_poller.py` — out of scope, owned by s34.
- Anything in `social_agent.py`, `marina_agent.py`, `dm_agent.py`, `state_registry.py` — out of scope, untouched.
- `_buffer_message`, `_flush_buffer`'s structure, `_get_phone_lock`, the per-phone lock infrastructure, `send_typing_indicator` calls — all unchanged.

## Tests

Create `wtyj/tests/social/test_187_sender_registry.py` with 5 tests:

### Test 1 — `ZernioSender.send` delegates to `send_dm_reply`

Patch `agents.social.senders.zernio.send_dm_reply` with a `MagicMock` set to return `True`. Call `ZernioSender.send("conv_abc", "acct_456", "hello")`. Assert:

- `send_dm_reply` was called exactly once with positional args `("conv_abc", "acct_456", "hello")`
- The return value is `True`

This verifies the wrapper is a thin pass-through with no parameter munging.

### Test 2 — Registry maps the four channels to `ZernioSender`

Import `SENDERS`, `ZernioSender`. Assert:

- `SENDERS["whatsapp"] is ZernioSender`
- `SENDERS["instagram_dm"] is ZernioSender`
- `SENDERS["facebook_dm"] is ZernioSender`
- `SENDERS["twitter_dm"] is ZernioSender`

Identity check (`is`) not equality. Verifies the dispatch table is wired up so future imports get the right class.

### Test 3 — `send_reply` dispatches via the registry

Patch `agents.social.senders.zernio.send_dm_reply` with a `MagicMock` returning `True`. Call `send_reply("instagram_dm", "conv_ig", "acct_ig", "hi there")`. Assert:

- `send_dm_reply` was called once with `("conv_ig", "acct_ig", "hi there")`
- `send_reply` returned `True`

This verifies the channel→class lookup → `.send()` chain works end-to-end at the unit level.

### Test 4 — Unknown channel falls back to `DEFAULT_SENDER`

Patch `agents.social.senders.zernio.send_dm_reply` returning `True`. Call `send_reply("totally_new_channel_xyz", "conv_x", "acct_x", "fallback test")`. Assert:

- `send_dm_reply` was still called (the default fell back to ZernioSender)
- `send_reply` returned `True`

Also assert the lookup directly: `SENDERS.get("totally_new_channel_xyz", DEFAULT_SENDER) is ZernioSender`.

### Test 5 — Integration: `_process_zernio_event` calls `send_reply` for IG DMs

Mirrors the test_186 integration test pattern. Patch `agents.social.webhook_server.send_reply` (NOT the leaf `send_dm_reply` — we want to verify `webhook_server` actually goes through the dispatcher rather than bypassing it). Patch `handle_incoming_whatsapp_message` to return `"Reply from orchestrator"`, and patch `send_typing_indicator` and `state_registry.dm_store_message` so the test doesn't hit real I/O.

Build a real Zernio Instagram DM payload using the same `_make_zernio_payload` helper pattern as `test_138_dm_booking.py:28-44` (and `test_186_channel_adapters.py`). Use a unique `conv_id` like `"conv_187_ig"` and a unique `message_id` like `"test_187_ig_msg_1"` to avoid the dedup table colliding with prior runs. Set `config_loader._cache["features"]["booking_flow"] = True` inside a try/finally that restores the original value.

Call `_process_zernio_event(payload)`. Assert:

- `send_reply` was called exactly once
- First positional arg is `"instagram_dm"` (channel)
- Second positional arg is `"conv_187_ig"` (conversation_id)
- Fourth positional arg is `"Reply from orchestrator"` (text)
- The third positional arg (account_id) is whatever the payload's account.id maps to (use `"acct_ig"` in the payload and assert it round-trips)

Use the cleanup pattern from `test_138_dm_booking.py:17-25` to wipe `whatsapp_threads`, `whatsapp_booking_state`, `pending_notifications`, and `whatsapp_processed` rows for the test conversation_id before and after the test.

This catches the case where someone refactors `webhook_server.py` and accidentally bypasses `send_reply`, which a leaf-level mock of `send_dm_reply` would silently allow.

## Success Condition

`python3 -m pytest wtyj/tests/ -q` reports **881 passed / 0 failed** (876 baseline + 5 new). The two `send_dm_reply` call sites in `webhook_server.py` (lines 233 and 352) are replaced with `send_reply(...)` calls. After deploy, sending a real DM through any of the 4 Zernio-routed channels still delivers the reply (verified by the integration test plus container health check post-deploy).

## Rollback

`git revert <commit>`. The new `wtyj/agents/social/senders/` directory is purely additive — reverting removes it. The `webhook_server.py` changes are localized to two ~3-line blocks plus one import line. Reverting restores direct `send_dm_reply` calls. No data migration, no state changes, no third-party API impact, no DB schema changes. Container restart picks up the reverted code in the next deploy cycle.
