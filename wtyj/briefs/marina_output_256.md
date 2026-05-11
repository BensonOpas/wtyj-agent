# OUTPUT 256 — Compact WhatsApp escalation alert body

## What was done

P1 fix for issue #25 — Calvin's live verification reported that the WhatsApp operator alert for an email-channel escalation was *"not an alert, [it's] a book"*. Root cause was at `wtyj/dashboard/api.py:1969-1970`: `_fire_escalation_alerts` built ONE rich body via `_build_alert_body` (the Brief 239 format with Reason / latestCustomerMessage-in-quotes / Suggested options bullets / etc.) and dispatched it unchanged to BOTH email (smtp_send) AND WhatsApp (send_dm_reply). The same body that's right for an operator's inbox looked like a wall of text on WhatsApp. Added two helpers — `_strip_email_artifacts` (drops quoted reply intros, `>` lines, RFC-3676 sig delimiters, common sign-off lead-ins, confidentiality disclaimer keywords, em dashes; hard-caps at 180 chars) and `_build_alert_body_whatsapp` (Calvin's 5-line target format: Customer / Channel / Need / Latest / Action, ~539-char worst-case ceiling). `_fire_escalation_alerts` now builds both bodies; email keeps the rich Brief 239 output, WhatsApp gets the compact one. Appointment alerts at `_fire_appointment_alerts` are untouched (already compact per Brief 241 — no customer-text fields).

## Tests

1095 passing / 0 failures (1090 baseline + 5 new = 1095). Targeted file `wtyj/tests/social/test_217_alert_delivery.py` runs 39/39. Test 4 is the load-bearing 600-char ceiling assertion: pathological inputs (200-char customer name, 300-char decide, 800-char latestCustomerMessage with signature + disclaimer + quoted history) produce a body under 600 chars only because the three caps (customer 60, need 180, latest 180) hold.

## Unexpected findings

The pre-existing test `test_wa_alert_resolved_route_calls_zernio_records_sent` at line 542 asserted `"Reason:" in captured_send["text"]` — i.e., it codified the OLD behavior (rich body sent to WhatsApp) as a passing invariant. Updated the assertion to reflect the post-Brief-256 contract (compact body, no `Reason:` / `Suggested options:` / `recommendedOptions` bullets) in the same commit. The docstring was rewritten to match. This is a behavioral test, not a structural one — the test still verifies that the dispatcher calls Zernio with the route's conv_id + account_id and records `sent`, just against the new compact body shape.

Brief-reviewer round 1 FAIL caught two real issues: (a) the original brief named a non-existent test file path `wtyj/tests/dashboard/test_217_alert_dispatcher.py` — actual canonical is `wtyj/tests/social/test_217_alert_delivery.py`; (b) the original 600-char ceiling math didn't bound `customer_name`, so a pathological display name could blow the cap silently. Tightened all three caps and added the 200-char customer_name input to test 4 to actually prove the bound. Round 2 PASS.

## Deployment

Source commit `e5e1804` ([HOTFIX] subject so the CI pipeline bypasses off-hours queue). Post-exec commit pending step (i). All 4 containers expected healthy post-deploy via the shared `wtyj-agent` image.
