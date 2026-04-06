# OUTPUT 068 — WhatsApp Message Pipeline: Parse, Dedup, Reply

## What Was Done

### Local (Mac)
1. Modified `shared/state_registry.py` — added `whatsapp_processed` table, `wa_has_been_processed()`, `wa_mark_as_processed()`
2. Created `agents/social/whatsapp_client.py` — parse Meta payloads into normalized messages + send text replies via WhatsApp Cloud API (urllib.request)
3. Created `agents/social/social_agent.py` — stub handler returning hardcoded test reply
4. Modified `agents/social/webhook_server.py` — POST handler now uses BackgroundTasks, calls parse → dedup → agent → send pipeline
5. Created `tests/social/test_068_pipeline.py` — 10 tests covering parse, dedup, agent, send, integration

### VPS
1. Deployed via git pull + service restart
2. Live curl test: simulated WhatsApp text message → full pipeline executed → reply sent and delivered

## Test Results

### Local (10/10 pass)
```
tests/social/test_068_pipeline.py::test_parse_text_message PASSED
tests/social/test_068_pipeline.py::test_parse_status_update_returns_empty PASSED
tests/social/test_068_pipeline.py::test_parse_image_message PASSED
tests/social/test_068_pipeline.py::test_parse_empty_payload PASSED
tests/social/test_068_pipeline.py::test_dedup_prevents_reprocessing PASSED
tests/social/test_068_pipeline.py::test_agent_stub_returns_reply PASSED
tests/social/test_068_pipeline.py::test_send_text_message_success PASSED
tests/social/test_068_pipeline.py::test_send_text_message_failure PASSED
tests/social/test_068_pipeline.py::test_webhook_post_triggers_pipeline PASSED
tests/social/test_068_pipeline.py::test_health_endpoint PASSED
```

### Regression (7/7 pass)
```
tests/social/test_067_webhook.py — 7 passed
```

### Live Verification
Full pipeline confirmed in VPS logs:
- `webhook_received` — payload arrived
- `whatsapp_message_normalized` — parsed (from: 59996881585, text: "Live test from curl", from_name: "Curl Test")
- `agent_stub_called` — stub handler invoked
- `whatsapp_send_ok` — reply sent via WhatsApp Cloud API (message ID: wamid.HBgLNTk5OTY4ODE1ODUVAgARGBJFRDIzNjM5NzEzNTdENUE1MEQA)
- `webhook_status_update` — Meta confirmed "sent" then "delivered"
- Pricing: billable=false, category=service (free customer service window)

### Token Verification
Permanent System User token confirmed working — outbound API call returned 200 with valid message ID.

## Anything Unexpected

1. **Status update webhooks arrive automatically** — after sending our reply, Meta immediately sent two status webhooks (sent + delivered). These were correctly filtered by `parse_webhook_payload` (logged as `webhook_status_update`, not processed as messages). This confirms the status filtering logic works in production.
2. **Free tier pricing** — Meta's status webhook shows `"billable": false, "pricing_model": "PMP", "category": "service"`. Customer-initiated conversations within the 24h service window are free. Good for testing.
3. **No issues with imports** — Brief 067 regression tests passed without modification despite webhook_server.py gaining new imports (state_registry, whatsapp_client, social_agent).

## SR Deliverables (per his checklist)

1. Token swapped successfully: **yes** (permanent System User token, deployed earlier this session)
2. Service restarted: **yes**
3. Inbound webhook still works: **yes** (curl test received and processed)
4. Outbound reply using permanent token works: **yes** (reply delivered, confirmed by Meta status webhook)
5. Any Meta API error message: **none — clean 200 response**
