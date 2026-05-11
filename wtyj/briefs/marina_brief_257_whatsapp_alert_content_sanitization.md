# BRIEF 257 — WhatsApp alert content sanitization (strip internal prefixes, CRM/ticket hallucinations, subject-as-Latest leak)
**Status:** Draft | **Files:** `wtyj/dashboard/api.py`, `wtyj/tests/social/test_217_alert_delivery.py` | **Depends on:** Brief 256 | **Blocks:** issue #25 verification (round 2)

## Context

Calvin's round-2 live retest of #25 (2026-05-11T18:25:13Z) reported PARTIAL/FAIL. Two distinct symptoms:

1. **First WA alert: verbose format** — included `Mode: Agent needs help`, long `Reason:` / `Decision needed:` / `Suggested options:` blocks. These labels only exist in `_build_alert_body` (the rich Brief 239 body); they cannot be produced by `_build_alert_body_whatsapp`. Deploy-window race is the load-bearing explanation: Brief 256 source `e5e1804` pushed 2026-05-11T17:30Z, CI completed ~17:38Z, `wtyj-unboks` container restarted 17:39:14Z. Any escalation processed between push and restart hit the OLD `email_poller` process running pre-Brief-256 code. **Audit confirms**: `_fire_escalation_alerts` is the only dispatcher registered (one `set_alert_dispatcher` call at `dashboard/api.py:2179`, no other Python module sends operator WhatsApp alerts directly — verified by grepping every `send_dm_reply` / `send_whatsapp_message` call site in `wtyj/`). The single dispatcher in the live container post-17:39:14Z does call `_build_alert_body_whatsapp` for the WA branch. **No code fix needed for the verbose-format symptom**; it cannot reproduce on the current live code path.

2. **Second WA alert: compact shape, leaked content** — Calvin's exact text:
   - `Need: Reach out to Calvin directly to establish context, or review any external records...`
   - `Latest: [ESCALATION] NO-REF - Calvin Adamus...`
   - Mentions of "CRM/ticket history" and "no conversation history available" that Marina's Nr 2 operator flow should not invent.

   Root cause traced to two places:

   - **Subject-as-Latest leak**: `state_registry.create_pending_notification` (`state_registry.py:1766`) passes `subject` as the 4th positional arg to `_alert_dispatcher(...)`, which becomes the `summary` (fallback_summary) param in `_fire_escalation_alerts`. For email-poller escalations, the subject is `f"[ESCALATION] {_ref} - {_cname} ({from_email}) - {_esc_note[:200]}"` (`email_poller.py:771, 1128`). When Claude's escalation_summary call fails or returns empty `latestCustomerMessage`, my Brief 256 `_build_alert_body_whatsapp` falls back to `_strip_email_artifacts(fallback_summary)` — which leaves `[ESCALATION] NO-REF - Calvin Adamus (calvin@gaimin.io) -` mostly intact since none of those tokens match the email-artifact strip patterns. The compact body's Latest line ends up showing an internal subject prefix instead of the actual customer message.

   - **CRM/ticket hallucination in Need**: Claude's `operatorNeedsToDecide` field comes from `escalation_summary.py` which uses Brief 252's entity-extraction prompt. When the source escalation lacks a concrete entity (booking ref, time, etc.), Claude drifts to generic operator-advice prose ("Reach out to Calvin directly to establish context, or review any external records..."). Brief 252's prompt rules try to gate this but don't catch every case. Calvin specifically called out: "do not mention CRM/ticket history unless that real feature exists", "do not say no conversation history available if the source email exists".

## Why This Approach

Three options considered:

1. **Python-side sanitizers on Need + Latest before they hit the compact body (chosen)** — add two more strip patterns to the boundary defense layer (`_strip_internal_prefixes`, `_strip_hallucinated_external_systems`). Belt-and-suspenders the same way `_strip_email_artifacts` defends against signatures/disclaimers post-Brief-256: when Claude or upstream subject construction produces unwanted text, the sanitizer drops or replaces it. Smallest behavioral surface; reuses the established defense pattern.

2. **Server-side prompt change in `escalation_summary.py` to ban "external records / CRM / ticket history" language** — push the constraint up to Claude. Already tried for entity extraction in Brief 252; Calvin still got "book" output in #25 round-1 because prompt rules alone are insufficient. Same failure mode would apply here. Keep the Python sanitizer as the load-bearing fix; a Claude-side rule could be added later as a supplementary measure.

3. **Source customer message directly from `customer_interactions` table when `summary_dict.latestCustomerMessage` is empty** — adds a DB read on the alert path, more code, dependency on Brief 188's customer_interactions schema. Solves the root issue (we have the message; we just don't pipe it correctly) but is a bigger surgical change than this hotfix should attempt. Deferred to a future brief if option 1 doesn't close Calvin's verification.

Trade-off accepted: option 1 is defensive sanitization, not source correction. If Claude consistently produces empty `latestCustomerMessage`, the compact alert will OMIT the Latest line (per the Brief 256 design — empty Latest is dropped, not stubbed). Operators get a 4-line alert (Customer / Channel / Need / Action) which Calvin's spec explicitly accepts ("Latest" is listed as compact-body content but not load-bearing for the alert's "operator decision in seconds" goal).

## Instructions

1. **New helper `_strip_internal_prefixes(text: str) -> str`** in `wtyj/dashboard/api.py`, placed immediately above `_build_alert_body_whatsapp` (~line 1735). Removes the email-poller / social-agent subject-prefix artifacts that are NOT customer text. Approach: drop the known internal tokens in a deterministic order, then trim residue. This is simpler and more predictable than a single structured regex.

   Subject formats this targets (from `email_poller.py:771, 1128, 758` and `social_agent.py:278, 670`):
   - `[ESCALATION] {ref} - {customer_name} ({email_or_phone}) - {note}`
   - `[ESCALATION] {ref} - {customer_name}` (some social paths)
   - `[BOOKING REQUEST] {customer_name} (Email: {email}) - {note}`
   - `[RELAY-{token}] {ref} - {customer_name}`

   Strip steps (apply in order):
   1. Drop full bracketed tokens with regex: `\[ESCALATION\]`, `\[BOOKING REQUEST\]`, `\[RELAY-[A-Za-z0-9]+\]`.
   2. Drop the bare ref token `NO-REF` (case-sensitive).
   3. Drop parenthesized email blobs: regex `\([^)]*@[^)]*\)` (captures `(calvin@gaimin.io)`, `(Email: calvin@gaimin.io)`, etc.).
   4. Drop parenthesized phone-looking blobs: regex `\(\+?[\d\s\-]{6,}\)` (captures `(+351963618003)`, `(351 963 618 003)`).
   5. Strip leading/trailing runs of whitespace + `-`, `:`, `,`, `.` punctuation (collapse all of `[\s\-:,]+` at boundaries).
   6. Collapse runs of internal whitespace to single spaces.
   - **Sentinel check**: if the result is empty (the input was ONLY internal prefix tokens with no real text after), return empty string. The caller then omits the field entirely instead of showing an empty value.
   - Returns the cleaned string (possibly empty).

2. **New helper `_strip_hallucinated_external_systems(text: str) -> str`** in `wtyj/dashboard/api.py`, placed immediately below `_strip_internal_prefixes`. Replaces Claude-emitted phrases that invent external systems Marina doesn't have:
   - Pattern (case-insensitive substring): drop entire sentences containing `external records`, `CRM`, `ticket history`, `helpdesk`, `Salesforce`, `Zendesk` — cut from the start of the containing sentence to the next `.`, `!`, `?`, or end of string.
   - Pattern (case-insensitive substring): drop sentences containing `no conversation history available`, `no prior context available`, `cannot find any conversation history` — same sentence-level cut.
   - Pattern (case-insensitive substring): drop generic operator-advice prefaces `Reach out to the customer directly to establish context`, `Review any external records` — same sentence-level cut.
   - After cuts: strip leading/trailing whitespace + collapse double-spaces to single.
   - **Sentinel check**: if the result is empty after cuts, return a generic fallback string `"Review and reply."` (operator-facing, doesn't invent context, fits the "direct operator decision" rule Calvin set in #25 rule 6).
   - Returns the cleaned string.

3. **Modify `_build_alert_body_whatsapp` (api.py:1735)** to pipe Need + Latest through the new sanitizers:
   - `need_line` (after the existing `operatorNeedsToDecide` / `reason` / fallback chain): pipe through `_strip_internal_prefixes` → `_strip_hallucinated_external_systems` → existing 180-char cap. If end result is empty AND no Claude content was available, the helper's "Review and reply." fallback from step 2 kicks in.
   - `latest_line`: pipe `summary_dict.get("latestCustomerMessage")` through `_strip_internal_prefixes` BEFORE `_strip_email_artifacts`. If after both strippers the value is empty, OR if the ORIGINAL `latestCustomerMessage` starts with `[ESCALATION]`, `[BOOKING REQUEST]`, or `[RELAY-` (sentinel: it was never customer text, it was an internal subject), OMIT the Latest line entirely (existing Brief 256 logic for empty `latest_line` already does this).
   - The fallback chain from `latestCustomerMessage` empty → `fallback_summary` is REMOVED: never use the subject as Latest. If `latestCustomerMessage` is empty, the Latest line is omitted.

4. **Modify the no-`summary_dict` legacy branch** in `_build_alert_body_whatsapp`: also pipe `fallback_summary` through `_strip_internal_prefixes` → `_strip_hallucinated_external_systems`. The legacy Brief 217 path produces "Need: <fallback_summary>" with no Latest; sanitize the fallback the same way as the structured path so a subject-only fallback doesn't leak.

5. **No changes** to `_build_alert_body` (rich email body keeps full content — operator reading the email wants the context, even if it's noisy). No changes to `_fire_escalation_alerts` dispatch logic. No changes to `_fire_appointment_alerts`.

## Tests

Append 5 tests to `wtyj/tests/social/test_217_alert_delivery.py` (canonical per-module file, already extended by Brief 256). All tests call `_build_alert_body_whatsapp` directly with synthesized `summary_dict` / `fallback_summary` inputs that mirror Calvin's round-2 failure exactly.

1. **test_brief_257_wa_alert_strips_escalation_subject_prefix_from_latest** — `summary_dict = {"operatorNeedsToDecide": "Confirm time", "latestCustomerMessage": "[ESCALATION] NO-REF - Calvin Adamus (calvin@gaimin.io) - wants to book"}`. Assert: body does NOT contain `[ESCALATION]`, `NO-REF`, `calvin@gaimin.io`. Assert: Latest line either is OMITTED entirely OR contains only `wants to book` (the trailing customer-relevant fragment). Use `assert "[ESCALATION]" not in body` AND `assert "NO-REF" not in body` AND `assert "calvin@gaimin.io" not in body`.

2. **test_brief_257_wa_alert_strips_crm_hallucination_from_need** — `summary_dict = {"operatorNeedsToDecide": "Reach out to Calvin directly to establish context, or review any external records and CRM/ticket history for prior interactions.", "latestCustomerMessage": "Hi, I need help with my booking"}`. Assert: body Need line does NOT contain `external records`, `CRM`, `ticket history`. Assert: Need either contains "Review and reply." (sanitizer fallback) OR the cleaned sentence without external-system claims.

3. **test_brief_257_wa_alert_strips_no_conversation_history_phrase** — `summary_dict = {"operatorNeedsToDecide": "There is no conversation history available. Please contact the customer.", "latestCustomerMessage": ""}`. Assert: body Need line does NOT contain `no conversation history available`. Assert: Latest line is OMITTED (was empty). Assert: Need contains "Please contact the customer." OR sanitizer fallback `Review and reply.`.

4. **test_brief_257_wa_alert_omits_latest_when_no_real_customer_message** — `summary_dict = {"operatorNeedsToDecide": "Confirm appointment", "latestCustomerMessage": ""}, fallback_summary = "[ESCALATION] NO-REF - Calvin Adamus (calvin@gaimin.io) - wants booking"`. Assert: body does NOT contain `Latest:` line at all (the subject is NOT used as Latest fallback per the Brief 257 rule). Assert: body still contains `Customer:`, `Channel:`, `Need: Confirm appointment`, `Action:`.

5. **test_brief_257_wa_alert_legacy_fallback_path_sanitized** — call `_build_alert_body_whatsapp("Calvin", "email", summary_dict=None, fallback_summary="[ESCALATION] NO-REF - Calvin Adamus (calvin@gaimin.io) - urgent help needed")`. This is the no-`summary_dict` Brief 217 fallback path. Assert: body Need does NOT contain `[ESCALATION]`, `NO-REF`, `calvin@gaimin.io`. Assert: Need contains `urgent help needed` (the trailing customer-relevant fragment) OR the sanitizer fallback `Review and reply.`.

6. **test_brief_257_wa_alert_omits_latest_when_latestCustomerMessage_starts_with_internal_prefix** — load-bearing assertion for the step-3 rule "if the ORIGINAL `latestCustomerMessage` starts with `[ESCALATION]`, `[BOOKING REQUEST]`, or `[RELAY-`, OMIT the Latest line entirely". Call with `summary_dict = {"operatorNeedsToDecide": "Decide", "latestCustomerMessage": "[ESCALATION] NO-REF - garbage payload"}`. Assert: `"Latest:" not in body`. Then call again with `latestCustomerMessage = "[BOOKING REQUEST] Calvin wants help"` — assert `"Latest:" not in body`. Then with `latestCustomerMessage = "[RELAY-abc123] more garbage"` — assert `"Latest:" not in body`. This test exclusively proves the omission branch; without it, an executor could implement "strip-then-show" and test 1 would still pass.

## Success Condition

After Brief 257 source commit + push + canary + production deploy + (if necessary) container restart:
- Calvin sends a fresh test email that triggers an escalation through the email-poller path (no Claude entity match, so Claude's `latestCustomerMessage` may be empty or generic).
- WhatsApp alert delivered to `+351963618003` contains:
  - NO `[ESCALATION]`, `NO-REF`, `calvin@gaimin.io` text leakage in any field.
  - NO `external records`, `CRM`, `ticket history`, `no conversation history available` phrases.
  - Either a real customer-text Latest line OR no Latest line at all (never an internal-subject-as-Latest line).
  - Need contains either Claude's cleaned operator-decision text OR the sanitizer fallback `Review and reply.`.
- Email alert remains the rich Brief 239 body — unchanged.
- All 4 production containers healthy post-deploy.

## Rollback

```
ssh root@108.61.192.52 "bash /root/wtyj/scripts/rollback.sh all"
```

Canonical rollback per `wtyj/briefs/infra.md:188`. Retags `wtyj-agent:previous` → `wtyj-agent:latest` and restarts all four production containers. Pure additive sanitizer functions + caller modifications; no schema migration, no data destruction. Revert restores Brief 256 behavior in <30s. If image-target itself is bad: `git revert <Brief 257 source SHA> && git push origin main`.
