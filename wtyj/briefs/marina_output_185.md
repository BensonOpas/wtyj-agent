# OUTPUT 185 — Store actual platform in conversation data

## What was done

Added `channel` parameter to `handle_incoming_whatsapp_message()` in `social_agent.py` (default `"whatsapp"` for backward compatibility). All 8 `create_pending_notification()` calls, 2 `marina_agent.process_message()` calls, 10 notification body/subject strings, 4 `sheets_writer.log_escalation()` calls, and 1 `customer_record_interaction()` call now use the actual channel instead of hardcoded `"whatsapp"`. Added `_channel_label` helper dict for human-readable names (WhatsApp, Instagram, Facebook, X/Twitter). Updated both call sites in `webhook_server.py` to pass the real channel from the Zernio webhook. Fixed one pre-existing test (`test_138_dm_booking`) that broke because its mock side_effect didn't accept the new `channel` kwarg.

## Tests

871 passing / 0 failures (867 baseline + 4 new).

## Unexpected findings

Test `test_138_dm_booking::test_dm_user_message_stored_after_orchestrator` broke because its side_effect function `_orchestrator_side_effect(msg)` didn't accept the new `channel` keyword argument. The mock was silently swallowing the TypeError. Fixed by adding `**kwargs` to the side_effect signature. This is a pattern to watch for: any test that mocks `handle_incoming_whatsapp_message` with a side_effect function needs to accept the new `channel` kwarg.
