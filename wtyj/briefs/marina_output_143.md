# OUTPUT 143 — Zernio WhatsApp

## What was done

WhatsApp messages can now come through Zernio instead of Meta Cloud API. Same pipeline as IG/FB DMs — Zernio webhook → debounce → orchestrator (or DM agent) → reply via Zernio.

Changes:
1. `zernio_dm_client.py` — WhatsApp gets `channel="whatsapp"` (not `"whatsapp_dm"`)
2. `webhook_server.py` — Zernio WhatsApp messages route through the existing debounce buffer. `_flush_buffer` checks for `_zernio_*` metadata and routes replies through Zernio API instead of Meta API. booking_flow toggle respected.

Meta WhatsApp code stays — just becomes inactive once the Meta webhook is disabled in Meta's dashboard.

## Files changed

- `agents/social/zernio_dm_client.py` — channel naming fix
- `agents/social/webhook_server.py` — WhatsApp debounce + Zernio reply routing in `_flush_buffer`
- `tests/social/test_143_zernio_whatsapp.py` — 6 new tests

## Test results

```
6 new tests: all pass
639 total: all pass
6 pre-existing failures: test_047 + test_048 (unchanged)
```

## Next step (manual)

Disable the Meta WhatsApp webhook in Meta's developer dashboard to prevent duplicate message processing. Do this AFTER verifying Zernio WhatsApp works live.
