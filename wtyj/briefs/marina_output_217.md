# OUTPUT 217 — Escalation alert delivery

## What was done

New per-tenant alert pipeline: when a customer triggers an escalation, the backend now pings the operator on configured channels. Two new SQLite tables (`alert_settings` singleton row using INSERT-OR-REPLACE on fixed `id=1` so the upsert is atomic; `alert_deliveries` append-only audit log of every dispatch attempt). Three state_registry helpers (`get_alert_settings` with sentinel `"default"` resolution to `support_email` from `client.json`, `save_alert_settings`, `record_alert_delivery`) plus a pluggable callback mechanism (`set_alert_dispatcher` setter; `_alert_dispatcher` module-global) so state_registry can fire alerts without importing dashboard.api (which would create a circular import). Two new endpoints in `wtyj/dashboard/api.py`: `GET /settings/escalation-alerts` returns the resolved config; `PUT /settings/escalation-alerts` upserts. The dispatcher (`_fire_escalation_alerts`) registers itself with state_registry at module-import time, immediately after its definition, so the function name resolves at registration time. Hooked into `state_registry.create_pending_notification` AFTER `set_conversation_status`, gated on `notification_type == "escalation"` (relay rows do NOT fire alerts). Telegram + Messenger record `status="skipped"` with `"provider not configured"` since we don't have those providers wired today. Best-effort dispatch — every channel attempt is wrapped in try/except so a delivery failure NEVER blocks the escalation row from being saved. Auto-clear fixture in `wtyj/tests/social/conftest.py` resets alert_settings to all-disabled before each test so pre-existing tests that seed escalations don't see surprise smtp_send calls; test_217 enables what it needs per-test.

## Tests

998 passing / 0 failures (baseline 989 + 9 new).

## Unexpected findings

Two pre-existing tests (test_210, test_214) that mocked `smtp_send` for their own /reply or /guidance email path failed once Brief 217 went live — the alert dispatcher fired on `create_pending_notification` and consumed the mock's first call, so `mock_smtp.assert_called_once()` saw 2 calls. Root cause: production default behavior is "email alerts enabled with support_email destination" (per SR's contract: "Email is always enabled by default"), so legacy tests that don't explicitly disable alerts inherit that behavior. Fix: added an autouse `_disable_alert_dispatch_default` fixture in `wtyj/tests/social/conftest.py` that resets alert_settings to all-disabled before each test. test_217 saves its own settings per-test; test_215's `_seed_escalation` helper continues to pass through unchanged. No production behavior change — the fixture is test-only.

## Deployment

Pending — commit/push/deploy in step 16.
