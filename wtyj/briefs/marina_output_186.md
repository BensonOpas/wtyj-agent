# OUTPUT 186 — Channel adapter refactor (parsing layer, Zernio channels)

## What was done

Created `wtyj/agents/social/channels/` package with 4 new files: `base.py` (the `Channel` ABC), `whatsapp_zernio.py` (`WhatsAppZernioChannel` — WhatsApp via Zernio adapter that emits `_zernio_*` metadata for the debounce buffer round-trip), `zernio_dm.py` (`ZernioDMChannel` — generic adapter for Instagram, Facebook, X/Twitter, and any future Zernio DM platform), and `__init__.py` (the `ZERNIO_CHANNELS` registry mapping channel name → adapter class plus `DEFAULT_ZERNIO_CHANNEL` fallback). Updated `wtyj/agents/social/webhook_server.py:_process_zernio_event` to dispatch via the registry: removed the inline `_wa_msg = {...}` literal at the WhatsApp branch (was lines 302-311) and the inline `orchestrator_msg = {...}` literal at the IG/FB/X branch (was lines 334-338), replacing both with `adapter_cls = ZERNIO_CHANNELS.get(channel, DEFAULT_ZERNIO_CHANNEL); ... = adapter_cls.from_zernio(msg)`. Added one import line. The dict shape produced by the adapters is a compatible superset of the previous inline dicts (adds `channel` and `message_id` to the IG/FB/X output) — no consumer reads the new keys, verified by grep across `social_agent.py`, `webhook_server.py`, and `dm_agent.py`. Brain (`handle_incoming_whatsapp_message`), buffer (`_buffer_message`/`_flush_buffer`), DM agent path, Meta WhatsApp legacy path, and email poller all untouched.

## Tests

876 passing / 0 failures (871 baseline + 5 new).

## Deployment

Pending — deploy after commit + push.
