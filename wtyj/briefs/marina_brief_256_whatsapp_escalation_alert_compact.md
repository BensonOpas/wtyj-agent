# BRIEF 256 — Compact WhatsApp escalation alerts (strip email artifacts, hard length cap)
**Status:** Draft | **Files:** `wtyj/dashboard/api.py`, `wtyj/tests/social/test_217_alert_delivery.py` | **Depends on:** Brief 252 (escalation summary entity extraction) | **Blocks:** issue #25 verification

## Context

Calvin's live verification on issue #25 (2026-05-11): the WhatsApp operator alert for an email-channel escalation was unusable as an alert — too long, included quoted email history, customer signature block, and confidentiality disclaimer. Calvin's exact words: *"This is not an alert, this is a book. A WhatsApp alert should be an alert, short Vulcan summary and call to action."*

Current code at `wtyj/dashboard/api.py:1969-1970` builds **one** alert body via `_build_alert_body(...)` and sends it to BOTH email (line 2003, smtp_send) AND WhatsApp (line 2034, send_dm_reply). The body at lines 1709-1720 contains: Reason block, previousProposedTimes block, latestCustomerMessage block (in quotes), Decision needed, Suggested options (up to 5 bullets), Action. For a rich escalation this easily exceeds 1500 chars and includes whatever quoted-history / signature / disclaimer text leaked through Claude's escalation summary extraction.

Calvin's target compact format (from issue body):
```
Escalation alert

Customer: Calvin Adamus
Channel: Email
Need: Confirm appointment time change.

Latest: Customer asks to move Tuesday 11:00 to Tuesday 12:00 due to flight delay.

Action: Open dashboard to confirm or suggest another time.
```

Constraint summary from issue #25 Rules section: under ~600 chars, no quoted email chain, no signatures, no confidentiality disclaimer, no long bullet lists, no em dashes (matching Brief 251's global brand rule), 1-2 suggested actions max, email alerts stay rich.

Out of scope (confirmed): appointment alerts at `_fire_appointment_alerts` (api.py:1817). `_build_appointment_body` (api.py:1737) is already compact (topic/time/location/CTA, no customer-text fields) and not flagged by Calvin in issue #25.

## Why This Approach

Three options considered:

1. **Add `_build_alert_body_whatsapp` + sanitizer; per-channel body in dispatcher (chosen)** — keep `_build_alert_body` untouched for email (rich), introduce a compact builder for WhatsApp, route per-channel. Defensive `_strip_email_artifacts` helper runs over the `latestCustomerMessage` field to belt-and-suspender Brief 252's prompt-side entity extraction. Smallest behavioral surface; email path is byte-identical post-deploy.

2. **One body, channel-conditional truncation inside `_build_alert_body`** — single function with a `compact: bool` flag. Mixes two intents in one helper, makes future changes to email-side messaging riskier, and the truncation logic still needs the same sanitizer. Rejected as a coupling smell.

3. **Server-side prompt change only (force Claude to emit a separate compact field)** — extend `escalation_summary.py` to emit `whatsappAlertText` alongside `latestCustomerMessage` etc. Pushes the cleanup into Claude, costs one prompt-rule expansion. Rejected because it leaves no defensive layer if Claude ignores the rule — the bug Calvin saw IS a case where prompt rules alone were insufficient (Brief 252 already told Claude to extract concrete entities; Calvin still got a "book"). Python-side sanitizer is the load-bearing fix; we keep Claude doing best-effort entity extraction.

Trade-off accepted: when Claude's `latestCustomerMessage` is well-formed (post-Brief-252), the sanitizer is a near no-op. When Claude regresses or the input email contains aggressive quoted history that Claude included verbatim, the sanitizer truncates hard. The compact builder ALWAYS caps the latest-message field at 200 chars regardless of what Claude returned.

## Instructions

1. **New helper `_strip_email_artifacts(text: str) -> str`** in `wtyj/dashboard/api.py`, placed immediately above `_build_alert_body` (~line 1679). Drops:
   - Quoted reply markers: any line starting with `>` (after lstrip of whitespace). Cut from the first such line.
   - "On <date> ... wrote:" pattern (case-insensitive, with optional newline before). Common Gmail/Outlook/Apple Mail quote intro. Cut from the match.
   - Forwarded headers `-----Original Message-----` / `-----Forwarded message-----`. Cut from the match.
   - Signature delimiter `\n-- \n` (RFC-3676 sig delimiter, with trailing space). Cut from the match. Plain `\n--\n` (no trailing space) is also covered defensively.
   - Common signature lead-ins (case-insensitive, start of line): `Best regards`, `Best,`, `Kind regards`, `Thanks,`, `Thank you,`, `Cheers,`, `Sincerely,`, `Sent from my iPhone`, `Sent from my Android`. Cut from the match.
   - Confidentiality disclaimers — keyword line containing any of (case-insensitive): `This email and any attachments`, `confidentiality notice`, `CONFIDENTIAL:`, `intended recipient`, `privileged and confidential`, `IMPORTANT NOTICE`. Cut from the match.
   - After cuts: strip leading/trailing whitespace, collapse runs of newlines (`\n\n\n+`) to single `\n\n`, replace em dashes (U+2014 + U+2013) with `-` per Brief 251's brand rule.
   - Hard length cap: truncate to 180 chars; if truncated, append `…`.

2. **New helper `_build_alert_body_whatsapp(customer_name: str, channel: str, summary_dict: dict, fallback_summary: str) -> str`** in `wtyj/dashboard/api.py`, placed immediately below `_build_alert_body`. Output shape matches Calvin's target verbatim:
   ```
   Escalation alert

   Customer: {customer_name or '(unknown)'}
   Channel: {_channel_label(channel)}
   Need: {need_line}

   Latest: {latest_line}

   Action: Open dashboard to reply.
   ```
   - `need_line` = `summary_dict.get("operatorNeedsToDecide")` if non-empty (already entity-extracted per Brief 252), else first 180 chars of `summary_dict.get("reason")`, else `(no decision specified)`. Truncate to 180 chars.
   - `latest_line` = `_strip_email_artifacts(summary_dict.get("latestCustomerMessage") or "")`. If empty after stripping, fall back to first 180 chars of `_strip_email_artifacts(fallback_summary or "")`. If still empty, the whole `Latest: …` line is omitted (don't show an empty Latest).
   - `customer_name_safe` = `(customer_name or "(unknown)")[:60]` — cap to 60 chars (no truncation suffix; long display names from Zernio / exotic email From headers would otherwise blow through the 600-char ceiling). Interpolated as the `Customer:` line value.
   - When `summary_dict` is None/empty (legacy Brief 217 fallback path), use only `fallback_summary` stripped + capped, omit Need/Latest distinction (use single "Need: {fallback}" line + Action).
   - No mode line. No reason block. No previousProposedTimes block. No suggested options bullets. No "Plain link:" footer.
   - Length: structurally bounded by 5 short fixed-label lines (~50 chars total) + Customer name (≤60) + Need (≤180) + Latest (≤180) + Action (~32 chars) + label/newline overhead (~37 chars) = ≤539 chars worst case. Comfortably under the ≤600 target. Test 4 exercises with all caps maxed out (customer_name 60+, Need 300, Latest 800) to prove the bound holds.

3. **Modify `_fire_escalation_alerts` (api.py:1941)** to build BOTH bodies. Replace:
   ```python
   alert_text = _build_alert_body(customer_name, channel, mode, summary_dict, summary, client_name)
   ```
   with:
   ```python
   alert_text = _build_alert_body(customer_name, channel, mode, summary_dict, summary, client_name)
   alert_text_whatsapp = _build_alert_body_whatsapp(customer_name, channel, summary_dict, summary)
   ```
   - Email branch at line 2003 keeps using `alert_text` (rich, unchanged).
   - WhatsApp branch at line 2034 (`send_dm_reply(route["conversation_id"], route["account_id"], alert_text)`) MUST switch to `alert_text_whatsapp`.
   - Email `record_alert_delivery` calls unchanged. WhatsApp `record_alert_delivery` calls unchanged.

4. **No changes** to `_build_alert_body`, `_build_alert_subject`, `_build_alert_html_body`, `_resolve_dashboard_link`, `_build_appointment_body`, `_fire_appointment_alerts`. Appointment alerts are out of scope per issue #25.

## Tests

Append 5 tests to `wtyj/tests/social/test_217_alert_delivery.py` (canonical per-module file for the alert dispatcher; Brief 217 named it, Briefs 239/240/241/243/247 already extended it). All tests exercise the new helpers directly (no IMAP / Zernio / SMTP integration — that surface is tested elsewhere and the issue is the body shape, not the dispatch).

1. **test_brief_256_whatsapp_alert_compact_shape** — minimal summary_dict with `operatorNeedsToDecide` + `latestCustomerMessage` both short and well-formed. Assert: body starts with `Escalation alert`, contains `Customer: <name>`, `Channel: Email`, `Need: <decide>`, `Latest: <latest>`, `Action: Open dashboard to reply.`. Assert body does NOT contain `Reason:`, `Suggested options:`, `Mode:`, `Previously proposed`, bullets, em dashes.

2. **test_brief_256_whatsapp_alert_strips_quoted_history** — summary_dict where `latestCustomerMessage` contains `"Hi, can we move to 12:00?\n\nOn 2026-05-10, support@unboks.org wrote:\n> Original message\n> with quoted lines"`. Assert: `body` contains `Hi, can we move to 12:00?`, does NOT contain `On 2026-05-10`, does NOT contain `> Original message`, does NOT contain `> with quoted lines`.

3. **test_brief_256_whatsapp_alert_strips_signature_and_disclaimer** — summary_dict where `latestCustomerMessage` contains the customer message + `"\n\nBest regards,\nCalvin Adamus\n+351 963 618 003\n\nThis email and any attachments are confidential and intended solely for the addressee."`. Assert: body contains the customer message, does NOT contain `Best regards`, does NOT contain `+351 963 618 003`, does NOT contain `This email and any attachments`, does NOT contain `confidential`.

4. **test_brief_256_whatsapp_alert_under_600_chars** — summary_dict with worst-case content: `customer_name` = 200-char pathological display name, `operatorNeedsToDecide` = 300 chars of decision prose, `latestCustomerMessage` = 800 chars including signature + disclaimer + quoted history. Assert: `len(body) <= 600`. The three caps (customer_name 60, need 180, latest 180) keep the body within bounds; without them, the same input produces a body > 1000 chars.

5. **test_brief_256_whatsapp_alert_falls_back_when_no_summary_dict** — `_build_alert_body_whatsapp(name, channel, summary_dict=None, fallback_summary="Customer urgently needs help")`. Assert: body contains `Need: Customer urgently needs help`, contains `Customer:`, contains `Channel:`, contains `Action: Open dashboard to reply.`, does NOT raise, does NOT include `(no decision specified)` (the fallback is provided).

## Success Condition

After Brief 256 source commit + push + canary + production deploy:
- Calvin sends a fresh email that triggers an escalation containing a quoted prior message + signature + standard confidentiality disclaimer.
- WhatsApp alert delivered to `+351963618003` is the 5-line compact format, under ~600 chars.
- WhatsApp alert contains no quoted lines starting with `>`, no `Best regards` / `Sent from my iPhone`, no `confidentiality notice` / `intended recipient`.
- Email alert remains the rich Brief 239/243 format (Reason, latestCustomerMessage in quotes, Suggested options bullets, HTML CTA button). Verifiable by checking the operator's email vs. their WhatsApp side-by-side.
- All 4 production containers healthy post-deploy.

## Rollback

```
ssh root@108.61.192.52 "bash /root/wtyj/scripts/rollback.sh all"
```

Canonical rollback per `wtyj/briefs/infra.md:188`. Retags `wtyj-agent:previous` → `wtyj-agent:latest` and restarts all four production containers. Pure additive code change (no schema, no data destruction). Revert restores prior behavior in <30s; WhatsApp alert returns to the full Brief 239 body until next code-side fix.

If the rollback target image (`:previous`) is itself problematic: `git revert <Brief 256 source SHA> && git push origin main` — CI picks up the revert, runs canary, deploys to production.
