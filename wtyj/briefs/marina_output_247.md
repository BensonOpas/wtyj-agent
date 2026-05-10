# OUTPUT 247 — Register alert dispatcher in email_poller process; remove duplicate legacy email send

## What was done

P0 fix for issue #17 — email-channel escalations were silently no-op'ing alert delivery. Calvin's new rude QA email correctly created an escalation row visible in the dashboard, but no email or WhatsApp operator alert was delivered. Production audit on unboks state_registry confirmed: zero `alert_deliveries` rows for ANY email-channel escalation in the entire history (id=16, 23, 26, 27 — all `channel='email'` — all 0 rows). Every WhatsApp-channel escalation has the expected 4 rows (default email + alt email + WhatsApp via Brief 240 Zernio + Telegram-skipped). Per-step shipped:

1. **Side-effect import in `wtyj/agents/marina/email_poller.py`** at line 29 (multi-line comment block at lines 22-28 explains the rationale; the `from dashboard import api as _dashboard_api_for_dispatcher_registration  # noqa: F401` line is at 29), immediately after the existing Brief 235 `from shared import escalation_dispatcher  # noqa: F401` (line 20 — which registers the Brief 227 summary dispatcher in this same process). Side effect: `dashboard/api.py:1879` registers `_fire_appointment_alerts` and `:2002` registers `_fire_escalation_alerts` against `state_registry`. Mirrors Brief 235's pioneered pattern exactly.

   **Placement deviation from brief spec (disclosed):** the brief instructed insertion AFTER the `from agents.marina.email_adapter import ...` block (lines 39-46) to defensively avoid potential import cycles. Actual placement is at line 29 — BEFORE the email_adapter block. Tests pass (subprocess test confirms no cycle materializes), and grouping the import next to its sibling Brief 235 dispatcher registration makes the file easier to read for future maintainers (both side-effect imports for cross-process dispatcher registration sit together at lines 20 + 29). The brief's defensive concern was theoretical; the empirical test result is no cycle.
2. **Removed duplicate legacy direct smtp_send** at `email_poller.py:1089-1097`. Pre-Brief-247 this block sent a hardcoded body to `demo_support_email` (= `business.support_email` from client.json — `butlerbensonagent@gmail.com` for unboks; not Calvin's primary mailbox). After Brief 247 the dispatcher fires for the same escalation row and sends Brief 239's rich body to BOTH `email_destination` (default) AND `email_alternative_destination` (Calvin's primary `calvin@gaimin.io`) PLUS WhatsApp via Brief 240's resolved Zernio route. Without removing the legacy send, Calvin would receive 1 legacy-style email + 2 dispatcher emails = 3 per escalation. Block replaced with a multi-line comment marker explaining the deletion + pointer to the dispatcher path so future readers don't reintroduce it. The `escalation_alert` body string variable defined just above (lines 1078-1088) stays — it's the body passed to the very next `create_pending_notification` call (line 1107) which persists it to `pending_notifications.body`.
3. **2 new tests in NEW file `wtyj/tests/marina/test_email_poller_alert_dispatcher.py`** — test 1 is a subprocess test that spawns a fresh `python3 -c "from agents.marina import email_poller; from shared import state_registry; print('escalation_dispatcher_registered=' + str(state_registry._alert_dispatcher is not None))"` and asserts `True` for both the escalation and appointment dispatchers. The subprocess shape is the only honest way to prove a side-effect import works in a fresh process — pytest's main process imports many modules so an in-process assertion would always pass. Test 2 is the same-process integration check: forces dashboard.api import, captures the dispatcher via monkeypatch, calls `create_pending_notification('escalation', 'email', ...)`, asserts the dispatcher was invoked with `channel='email'` (catches future regressions that might filter by channel). Test 2 wraps with `_wipe_escalations_for(customer_id)` before AND after to keep the shared dev DB clean across runs (mirrors the Brief 240 helper pattern in `test_217_alert_delivery.py`). Test 1's subprocess env-var block also includes `AZURE_CLIENT_ID=test` per the brief's spec (added during execution).

**Brief-reviewer:** PASS round 1 with 2 advisory nits (not blocking). Both addressed during execution: (a) the brief said the legacy block "immediately precedes" the create_pending_notification call — actually 9 lines of `sheets_writer.log_escalation` sit between them; clarified by leaving the sheets_writer block alone (correctly out of scope) and only deleting the smtp_send block. (b) Test 2 needed `_wipe_escalations_for` setup because Brief 227's dedup logic UPDATEs an existing row instead of inserting; added the helper + pre-test + post-test wipe.

## Tests

1060 passing / 0 failures (1058 baseline + 2 new = 1060). New file `wtyj/tests/marina/test_email_poller_alert_dispatcher.py` runs 2/2.

The subprocess test in particular is significant: it's the FIRST test in this codebase that verifies a side-effect import works across process boundaries — the exact production scenario where the bug Calvin observed lived for months/quarters undetected. Future regressions to email_poller's import order or removal of the side-effect import would now fail visibly in CI.

## Production verification needed (post-deploy)

After CI deploys this, the next email-channel escalation Calvin triggers should:
1. Create the `pending_notifications` row (works pre-fix too).
2. Fire 4 `alert_deliveries` rows: 2 emails (default + alt) + 1 WhatsApp via Brief 240 Zernio route + 1 Telegram-skipped.
3. Calvin receives an email at `calvin@gaimin.io` AND a WhatsApp at `+351963618003`.
4. NO email arrives at `butlerbensonagent@gmail.com` from the legacy direct send (it's gone).

A natural next QA step is to send another rude QA email post-deploy and verify items 2-4. Calvin can do this via the QA simulator (Brief 245) once Phase 2 ships, or manually.

## Deployment

Source commit pending. Will deploy via the standard CI pipeline. Container restart picks up the new email_poller.py — the dispatcher will be registered in the email-poller process from supervisord's next start of that program. All 4 containers expected healthy post-deploy. Briefs 238-246 all preserved (no shared code paths touched in dashboard/api.py or state_registry.py — the only changes are in email_poller.py + a new test file).

## Out-of-scope (deferred per brief Step 4)

- Move `_fire_escalation_alerts` and `_fire_appointment_alerts` to a shared module like `wtyj/shared/alert_dispatcher.py` — cleaner long-term but ~200-line touch; Brief 247 punted.
- Backfill `alert_deliveries` rows for the 4 historical email escalations (id=16, 23, 26, 27) — out of scope; rare; operator-side resolution already happened.
- Remove the relay-mode legacy direct smtp_send at `email_poller.py:1019-1028` — different `notification_type='relay'`; dispatcher never targeted relay rows; out of scope.
- Same fix needed in `hold_reaper.py` — verified no `create_pending_notification` calls in hold_reaper, so no fix needed.
