# OUTPUT 243 — Email alert dashboard deep-link buttons

## What was done

Replaced the plain "Open dashboard to reply." line at the bottom of escalation + appointment alert emails with HTML CTA buttons (blue `#1a73e8` Gmail-safe inline-CSS) plus a plain-text fallback URL line, deep-linking to the specific item in the operator dashboard. Per-step shipped:

1. **`business.slug` + `business.dashboard_url` in client.json (4 tenants):** added to `clients/bluemarlin/config/client.json`, `clients/adamus/config/client.json`, `clients/unboks/config/client.json` (committed) and `/root/clients/consultadespertares/config/client.json` (VPS-only patch via SSH+Python with `.bak.brief243` backup, mirroring Brief 238's pattern). All 4 tenants share `dashboard_url: https://dashboard.unboks.org`; slug is the per-tenant URL segment.
2. **`smtp_send` extended** in `wtyj/agents/marina/email_adapter.py` with optional `html_body: str = None` kwarg. When None → current behavior (plain `MIMEText("plain")` only — backward compatible). When set → `MIMEMultipart('alternative')` with both plain and HTML parts so HTML-capable clients render the button while text-stripping clients still see the plain body + URL.
3. **Two new helpers in `wtyj/dashboard/api.py`** between `_build_appointment_body` and `_fire_appointment_alerts`:
   - `_resolve_dashboard_link(item_kind, item_id)` — reads `business.slug` + `business.dashboard_url` from `config_loader.get_business()`, returns `f"{base}/{slug}/escalations/{id}"` or `f"{base}/{slug}/appointments/{id}"`. Empty string when either field missing → dispatchers fall back to plain-only email (no broken/half-link rendered).
   - `_build_alert_html_body(text_body, link_url, link_label)` — wraps the plain text in `<pre>` (preserves operator at-a-glance scan layout), adds an inline-CSS-styled blue button (#1a73e8 background, white text, 12px padding, 4px radius, no underline), and a "Plain link:" fallback line below so text-rendering clients still get a clickable URL. HTML-escapes everything via `html.escape()` to prevent injection.
4. **Wired into both dispatchers' email loops:** `_fire_escalation_alerts` builds link via `_resolve_dashboard_link("escalation", escalation_id)` once outside the per-recipient loop, conditionally builds `html_body` (None when no link), passes via `smtp_send(..., html_body=_html_body)`. `_fire_appointment_alerts` does the same with `("appointment", appointment_id)` and `"Open appointment"` label. Empty link → `html_body=None` → plain-only email (backward-compatible fallback).
5. **5 new tests** appended to `wtyj/tests/social/test_217_alert_delivery.py` (per Brief 236 rule — same per-source-module file as the Brief 217/241/242 dispatcher tests). Tests cover: link build with slug+url, link empty when missing fields, HTML body shape (button + fallback URL + escaped text + double URL count), escalation dispatcher passes html_body when link resolves, appointment dispatcher passes html_body with appointment label.

**Brief-reviewer:** FAIL round 1 (line-number drift — `_fire_escalation_alerts` was at 1813 not 1654, `_fire_appointment_alerts` at 1698 not 1758, email loops at 1864-1870 + 1739-1751 not where the brief had pointed). Round-2 patch: corrected all line numbers + the email-loop anchor blocks via Python script doing exact replacements. **PASS round 2 zero issues.**

**Existing test compatibility:** 7 pre-existing tests in `test_217_alert_delivery.py` mocked `smtp_send` with `(to, subj, body)` signatures (no `**kw`). Brief 243's dispatcher now passes `html_body=` kwarg unconditionally when a link resolves — the test's mocked config_loader returned a non-empty business block, so the kwarg DID get passed and the old mocks would `TypeError`. Updated all 7 mock sites to add `**kw` (6 `def fake_smtp(...)` definitions at lines 335/358/378/398/484/759 + 1 lambda variant at line 801; the 3 `@patch("dashboard.api.smtp_send")` decorator usages at lines 120/163/270 auto-`MagicMock` and accept any kwargs without modification). No behavioral change to existing tests; they now tolerate the new kwarg.

**Implementation-detail deviation from brief:** `_build_alert_html_body` uses `import html as _html` + `_html.escape(...)` instead of the brief's `import html` + `html.escape(...)`. Functionally identical; chosen to avoid shadowing risk with local variables named `html`. Disclosed here for paper-trail honesty.

## Tests

1047 passing / 0 failures (1042 baseline + 5 new = 1047). Targeted file `wtyj/tests/social/test_217_alert_delivery.py` runs 34/34 (was 29; added 5).

## Frontend contract for SR (issue #7 documented)

Backend produces links of shape:
- `https://dashboard.unboks.org/<tenant>/escalations/<id>`
- `https://dashboard.unboks.org/<tenant>/appointments/<id>`

SR's React app at `unboks-org/unboks-dashboard-api` needs route handlers for these paths. If SR's current routing is `/<tenant>` only (no nested item routing), the operator lands on the tenant root and has to click into Escalations/Appointments and find the item manually. Optional fallback: query-string variant `?view=escalations&escalationId=<id>` if path-based routing isn't supported — backend can produce either shape; path-based was chosen as the cleaner default.

## Deployment

Source commit pending. Will deploy via CI pipeline (Brief 235's push-to-main → test → canary → off-hours-decide → production). All 4 containers expected healthy post-deploy. Brief 238 tenant guard / Brief 239 rich body / Brief 240 Zernio route / Brief 241 dispatcher / Brief 242 confirm endpoint all preserved. End-to-end: operator confirms in dashboard → status flips → dispatcher fires → email arrives with **clickable Open escalation / Open appointment button** + fallback URL + WhatsApp via Zernio → Calvin clicks the button → lands on the deep-linked item in the dashboard (pending SR's route handler).
