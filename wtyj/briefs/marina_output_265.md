# OUTPUT 265 — Email alert multi-button + WhatsApp Zernio investigation

## What was done

P1 for issue #33. Two parts:

**Part A — Email**: Brief 243 already added one CTA button to escalation + appointment alert emails. Brief 265 extends to a two-button row: `Open escalation` (or `Open appointment`) plus `Open dashboard`. `_build_alert_html_body` now accepts a `buttons=[(url, label), ...]` kwarg; backward-compat preserved for any caller still using the Brief 243 positional `link_url` + `link_label` signature (those keep rendering a single button). `_resolve_dashboard_link` gained a new `item_kind="dashboard"` branch returning the bare `{base}/{slug}` tenant root URL. Each plain-text fallback section now lists every button's URL on its own line so text-only mail clients still get every link.

**Part B — WhatsApp**: Calvin asked Brief 265 to **investigate** Zernio interactive-button capability, not guess. Audit verified the Zernio SDK signature (`client.inbox.send_inbox_message(message=text)` at `wtyj/agents/social/zernio_dm_client.py:99`) is plain-text-only with no `interactive=` / `buttons=` / `template_components=` parameter. Meta Cloud API direct path is blocked by the archived Meta app (per Brief 143 / 240 infra context). No WA changes ship in Brief 265. The brief explicitly does NOT add a numbered "Reply 1/2/3" fallback because no inbound reply-parser exists; adding it would set false operator expectations (operator types `1`, nothing happens — worse than no buttons at all).

## Email alert files changed

- `wtyj/dashboard/api.py`:
  - `_resolve_dashboard_link` at line 2544 gained a `dashboard` branch (`{base}/{slug}` return)
  - `_build_alert_html_body` at line 2571 refactored to accept `buttons` kwarg; renders inline-flex horizontal row of buttons + per-URL plain-link fallback section
  - `_fire_appointment_alerts` email branch (around line 2604) builds 2-button list `[(appointment_link, "Open appointment"), (dashboard_link, "Open dashboard")]`
  - `_fire_escalation_alerts` email branch (around line 2788) builds 2-button list `[(escalation_link, "Open escalation"), (dashboard_link, "Open dashboard")]`

## WhatsApp / Zernio capability finding

**Verified finding**: Zernio's `send_inbox_message` SDK method accepts only a plain text `message` string. No interactive-button payload supported.

Two paths investigated:
1. **Zernio Inbox API native interactive buttons** — not exposed by the SDK at `agents/social/zernio_dm_client.py:99-115`. The single SDK call `client.inbox.send_inbox_message(conversation_id=..., account_id=..., message=text)` takes a plain string. No alternative SDK method visible in the codebase for sending structured/templated messages. Would require Zernio to add interactive-button support to their Inbox API + SDK release.
2. **Bypassing Zernio for direct Meta Cloud API interactive messages** — blocked by the archived Meta app (Brief 143 era: `whatsapp_legacy` Meta app is archived as a fallback rollback path, not actively maintained per `infra.md:409`). Would require a fresh Meta Business app registration + WhatsApp Business approval — out of scope for this hotfix.

**Decision: ship the email side of #33; document the WhatsApp finding; defer the WA button work until either Zernio adds native button support or a Meta app re-registration is in scope.**

The reply-parser fallback (numbered options the operator types back) is deferred: shipping the text without the parser would tell operators "Reply with 1, 2, or 3" and have nothing happen when they did. Better to leave WhatsApp at the Brief 256/257 compact informational format than introduce non-functional commands.

## Exact buttons implemented

| Alert type | Button 1 | Button 2 | URL pattern |
|---|---|---|---|
| Escalation email | `Open escalation` | `Open dashboard` | `{base}/{slug}/escalations/{id}` + `{base}/{slug}` |
| Appointment email | `Open appointment` | `Open dashboard` | `{base}/{slug}/appointments/{id}` + `{base}/{slug}` |

Where `{base}` = tenant's `client.json::business.dashboard_url` (e.g., `https://dashboard.unboks.org`) and `{slug}` = `client.json::business.slug` (e.g., `unboks`).

## Link / deep-link format

- No tokens or secrets in any URL — verified by inspection: `_resolve_dashboard_link` only reads `business.slug` + `business.dashboard_url` from the per-tenant `client.json`. Both fields are non-secret config.
- URLs are tenant-aware (the slug segment scopes the link). An operator clicking from the unboks alert email lands on unboks's dashboard.
- The dashboard frontend handles authentication on its end — if the operator's session has expired, they get the login page first then are redirected to the deep-link target.

## Tests / build result

- **1130 passing / 0 failures** (1127 Brief-264 baseline + 3 new Brief 265 = 1130).
- All 3 new tests in `wtyj/tests/social/test_217_alert_delivery.py` (canonical per-module file Brief 217 named):
  1. `test_brief_265_email_alert_renders_two_buttons` — exact 4-anchor count (2 buttons + 2 fallback links) + both labels + both URLs present
  2. `test_brief_265_email_alert_backward_compat_single_button` — Brief 243 (link_url, link_label) positional signature still works, single button + single fallback
  3. `test_brief_265_resolve_dashboard_link_supports_dashboard_root` — `dashboard` branch returns bare `{base}/{slug}`; regression guards for escalation/appointment/unknown branches

## Production health

Source commit `edcecdb` ([HOTFIX]) deployed via CI. All 4 production containers expected healthy on the new image. No schema change, no behavioral change for any caller still using the Brief 243 single-button signature.

## Calvin retest steps

1. **Trigger a real escalation** on the unboks tenant (any customer message that hits Marina's escalation criteria — e.g., a refund request via email or WhatsApp). The escalation alert email lands at the operator destination.

2. **Check the email rendering**:
   - **Expected**: an alert body section (escalation Reason / Decision needed / Suggested options text per Brief 239/254), then a row with two blue buttons: `Open escalation` (left) and `Open dashboard` (right). Below the buttons, a "Plain link:" section with both URLs each on its own line as clickable text links.
   - **URL shape**: `https://dashboard.unboks.org/unboks/escalations/<id>` for the escalation deep-link; `https://dashboard.unboks.org/unboks` for the dashboard root.
   - **Mobile test**: open the same email on a phone (Gmail / Apple Mail / Outlook mobile). The buttons should remain tappable; the fallback links should remain text-renderable.

3. **Trigger an appointment confirmation** (e.g., a booking flow with a confirmed time). Appointment alert email lands with the same 2-button shape: `Open appointment` + `Open dashboard`. Verify both URLs are tenant-scoped.

4. **WhatsApp alerts unchanged**: same escalation triggers a Zernio WhatsApp alert to `+351963618003`. The WA body is the Brief 256/257 compact format (Customer / Channel / Need / Latest / Action), no buttons. **This is intentional and documented above** — Zernio SDK doesn't expose interactive buttons today.

5. **Click each button on a different device** (desktop browser where you're already signed into the dashboard, then a clean incognito window where you're not). Verify:
   - Signed-in: button lands directly on the escalation/appointment detail or dashboard root.
   - Signed-out: dashboard login page first, then redirect to the deep-link target.
   - No tokens in the URL (visible in the browser address bar — confirms no leakage).

If anything misbehaves, paste the rendered email source + the URL the button pointed at and I'll iterate.

## Replit contract

**No frontend changes required for Brief 265 to deliver value.** The Brief 243 deep-link routes (`/{slug}/escalations/{id}` + `/{slug}/appointments/{id}`) already exist in the dashboard. The new `Open dashboard` button targets the bare `/{slug}` URL which already maps to the tenant's Inbox landing page.

**Optional future Replit work** (not blocking #33 verification):
- A dedicated `/<tenant>/dashboard` landing page distinct from Inbox could replace the bare `/<tenant>` target for the Open dashboard button. The backend `_resolve_dashboard_link("dashboard", 0)` would need to add `/dashboard` to its return. One-line change once SR confirms the desired landing route.
- A `View conversation` button (mentioned in Calvin's #33 spec but deferred from Brief 265) requires a deep-link route like `/<tenant>/inbox/<customer_id>` or `/<tenant>?conv=<id>`. If SR adds such a route, Brief 265 can be extended with a 3rd button via the same multi-button infrastructure.

## Out of scope (deferred)

- **WhatsApp interactive buttons**: Zernio SDK constraint, documented above. Re-evaluate when Zernio ships native button support OR Meta app is re-registered for direct Cloud API access.
- **Numbered reply fallback for WhatsApp**: requires a Zernio inbound webhook handler that disambiguates "operator command (1/2/3)" from "customer message" — separate brief.
- **Mark resolved button on email**: requires a signed magic-link auth flow (one-time token in URL) since email-side mark-resolved would mutate state. We don't have magic-link infrastructure today. Calvin's #33 spec explicitly conditioned Mark resolved on "if a safe authenticated/deep-link flow exists" — it doesn't, so we skip it.
- **View conversation button**: see Replit contract — needs SR-side route confirmation before backend can wire the link.
