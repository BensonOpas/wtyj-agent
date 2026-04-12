# OUTPUT 187 — Sender registry: dispatch replies via Zernio adapter

## What was done

Created `wtyj/agents/social/senders/` package with 3 files: `base.py` (`Sender` ABC), `zernio.py` (`ZernioSender` wrapping the existing `send_dm_reply` from `zernio_dm_client.py`), and `__init__.py` (`SENDERS` registry mapping channel name → sender class + `send_reply()` dispatcher function). Updated `webhook_server.py` to import `send_reply` and call it instead of `send_dm_reply` directly at both Zernio send sites: `_flush_buffer:234` (WhatsApp via Zernio) and `_process_zernio_event:354` (IG/FB/X DMs). Updated 11 existing tests across 3 files (`test_138_dm_booking.py`, `test_143_zernio_whatsapp.py`, `test_186_channel_adapters.py`) to mock `send_reply` instead of `send_dm_reply` and shift positional arg assertions by +1 for the new `channel` first argument. Brief-reviewer FAIL round 1 (caught the 11-test mock regression — patching the mock target from `send_dm_reply` to `send_reply` was not in the original brief), PASS round 2 after patching.

## Tests

881 passing / 0 failures (876 baseline + 5 new).

## Deployment

Pending — deploy after commit + push.
