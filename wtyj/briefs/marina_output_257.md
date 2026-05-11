# OUTPUT 257 — WhatsApp alert content sanitization

## What was done

Round-2 fix for issue #25 after Calvin's live retest (2026-05-11T18:25Z) showed Brief 256 closed the body-shape gap but left two content leaks: (a) Latest line contained `[ESCALATION] NO-REF - Calvin Adamus (calvin@gaimin.io) - ...` because `summary_dict.latestCustomerMessage` was empty and Brief 256 fell back to `fallback_summary` (the email-poller subject); (b) Need line contained Claude-hallucinated `external records / CRM / ticket history` and `no conversation history available` phrases. Added two sanitizers in `wtyj/dashboard/api.py` — `_strip_internal_prefixes` (drops bracketed subject tokens, NO-REF, parenthesized email/phone blobs) and `_strip_hallucinated_external_systems` (sentence-level cuts for CRM/Zendesk/Salesforce/no-history phrases, with generic `Review and reply.` fallback). Rewrote `_build_alert_body_whatsapp` to pipe Need through both sanitizers + 180-char cap, pipe Latest through internal-prefix strip BEFORE email-artifact strip, omit Latest entirely when `latestCustomerMessage` starts with an internal prefix, and remove the prior Brief 256 fallback chain that used `fallback_summary` as a Latest substitute. Audit confirmed only one operator-alert dispatcher hook (`_fire_escalation_alerts` at `dashboard/api.py:2179`) — the verbose-format symptom Calvin saw on his first alert must have been the 17:30→17:39 deploy window before wtyj-unboks restarted on the Brief 256 image.

## Tests

1101 passing / 0 failures (1095 baseline + 6 new = 1101). Targeted file `wtyj/tests/social/test_217_alert_delivery.py` runs 45/45. Test 6 (`test_brief_257_wa_alert_omits_latest_when_latestCustomerMessage_starts_with_internal_prefix`) exclusively probes the omission rule with three distinct internal prefixes — a strip-and-show implementation would pass test 1 but fail test 6.

## Unexpected findings

Two regressions surfaced during the full-suite run that the focused test pass missed. First commit of `_strip_internal_prefixes` collapsed all whitespace (including newlines) and stripped trailing periods. Both broke Brief 256 tests: the period strip turned "Confirm appointment time change." into "Confirm appointment time change" (test asserted the period), and the newline collapse turned multi-line signed emails into a single line, bypassing `_strip_email_artifacts`'s newline-anchored patterns for `\n-- \n` sig delimiter and `\n(?:Best regards|...)` sign-off detection. Fixed by: (a) removing `\.` from the trailing-strip pattern; (b) collapsing only horizontal whitespace `[ \t]+` instead of all `\s+`. Both fixes have explanatory comments inline so a future refactor doesn't accidentally regress them. The full regression suite then passed 1101/0.

## Deployment

Source commit `22467d9` ([HOTFIX] — bypasses off-hours queue). Post-exec commit pending step (i). Audit-confirmed deploy will route all WhatsApp escalation alerts (soft / hard / NO-REF / email-origin / social-origin) through `_build_alert_body_whatsapp` because that's the single dispatcher path; Brief 257 didn't change routing, only the body content of the WA branch.
