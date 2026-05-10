# BRIEF 243 — Email alert dashboard deep-link buttons (TASK-077)

**Status:** Draft | **Files:** `clients/{bluemarlin,adamus,unboks}/config/client.json` (each gets `business.slug` + `business.dashboard_url` — local repo edits), `/root/clients/consultadespertares/config/client.json` (VPS-only — Consulta Despertares is not version-controlled in this repo, patched via SSH+Python in Step 1b — same pattern as Brief 238), `wtyj/agents/marina/email_adapter.py` (`smtp_send` gains optional `html_body=None` kwarg; when set, emits multipart/alternative with both text and HTML parts; when None, current plain-text behavior unchanged), `wtyj/dashboard/api.py` (new `_resolve_dashboard_link(item_kind, item_id)` + `_build_alert_html_body(text_body, link_url, link_label)` helpers above `_fire_escalation_alerts`; wire link build + html_body pass-through in both `_fire_escalation_alerts` and `_fire_appointment_alerts`), `wtyj/tests/social/test_217_alert_delivery.py` (EXTEND with 5 new behavioral tests covering link build, link absence fallback, html body shape, escalation+appointment dispatcher integration) | **Depends on:** Brief 217 (alert dispatcher + smtp_send call sites in `_fire_escalation_alerts`), Brief 226 (alternative email destination), Brief 239 (rich escalation body — the text body this brief wraps in HTML), Brief 240 (ON CONFLICT DO UPDATE pattern in `save_alert_settings` — reused for safety; `business` block in client.json doesn't change schema), Brief 241 (`_fire_appointment_alerts` + `_build_appointment_body`), Brief 242 (operator confirm path — neither alert dispatcher nor email body shape touched by this brief, both preserved). | **Blocks:** SR's frontend route work to handle the deep-link path shape. Backend produces the link; frontend needs route handlers for `/{tenant}/escalations/{id}` and `/{tenant}/appointments/{id}` — documented in OUTPUT and posted to issue #7 as the contract.

## Context

Issue #7 (TASK-077) flags that current alert emails end with a useless plain-text line:

```
Action:
Open dashboard to reply.
```

…with no link. Operators have to manually navigate to the dashboard, find the right tab, and search for the matching escalation/appointment. Calvin asks for a real CTA button + plain-text fallback URL that deep-links to the specific item.

### Audit findings (verified read-only)

**1. `smtp_send` is plain-text only.** `wtyj/agents/marina/email_adapter.py:123-137` does:
```python
msg = MIMEMultipart()
msg["From"] = ...
...
msg.attach(MIMEText(body, "plain", "utf-8"))
```
Single MIMEText part, type "plain". To support an HTML CTA button while preserving the text fallback, we need multipart/alternative with both `text/plain` and `text/html` parts. Most modern email clients (Gmail, Outlook, Apple Mail, mobile clients) render the HTML part; readers without HTML support (text-only mail clients, screen readers, accessibility tools) get the plain text. Both parts are sent; client picks.

**2. Both alert builders end with a "go to dashboard" line, no link.**
- `_build_alert_body` (`dashboard/api.py:1620`): `"Action:\nOpen dashboard to reply."` (Brief 239 rich body) or `"Action: Open dashboard to review."` (legacy fallback).
- `_build_appointment_body` (`dashboard/api.py:1678`): `"Open the dashboard to review or update this appointment."` (Brief 241).

**3. No `business.dashboard_url` or `business.slug` in any client.json today.** Verified across `clients/unboks/config/client.json`, `clients/bluemarlin/config/client.json`, `clients/adamus/config/client.json`. Brief 177's lessons noted the gap. The container today identifies its tenant only via `CLIENT_CONFIG_PATH` env var (`wtyj/shared/config_loader.py:16`), which gives the file path — slug is implicit in the directory name (`/root/clients/unboks/...` → "unboks") but never read by code.

**4. Frontend route shape is not visible from this repo.** SR's frontend lives at the separate `unboks-org/unboks-dashboard-api` repo (perma-clone at `~/Projects/unboks-dashboard-api/` per `infra.md` Frontend section). Issue #7 acknowledges this: *"If frontend support is missing, choose the safest backend-produced link shape and report the frontend contract needed."* This brief picks **path-based** as the cleaner default and documents the contract in the OUTPUT.

**5. Dashboard URL.** Per `infra.md:330` and `system_state.md` references throughout briefs 200/201/211: production frontend is at `https://dashboard.unboks.org`. All four tenants currently share that one Replit project; per-tenant routing happens via the `/{tenant}/` URL segment.

### Why the new fields belong on `business`

`business.name` already lives in `client.json` (Brief 142 era). `business.email`, `business.support_email`, `business.phone`, `business.whatsapp`, `business.location`, `business.languages`, etc. — `business` is the canonical block for per-tenant identity. Adding `business.slug` + `business.dashboard_url` keeps the same convention. No new top-level block needed. SR's frontend already reads `/dashboard/api/config` to render branding; surfacing slug/URL alongside is a natural extension if SR ever needs them.

### Out of scope (per issue #7)

- **Broad frontend routing changes.** Backend produces the link shape; SR wires the route handlers in `unboks-org/unboks-dashboard-api`. If the path-based route doesn't exist yet, the link will land on the dashboard root (operator still has to navigate manually) — but the link is still valid, no 404. Frontend follow-up captured as the contract on issue #7.
- **WhatsApp alerts.** Issue #7 explicitly says "WhatsApp alerts remain unchanged." The Brief 240 Zernio path stays text-only; WhatsApp doesn't render HTML buttons anyway. The alert text Calvin gets on WhatsApp continues to end with the plain "Open the dashboard..." line. (If we ever want to inject a deep link into WA alerts too, that's a separate brief — Zernio's API may or may not preserve links across the WhatsApp transport.)
- **Auth-token-in-URL / magic-link login.** Issue #7's security section explicitly forbids this. Operator must already be logged in. If they're not, the dashboard's existing login flow runs and (frontend territory) optionally redirects back to the requested route — that's SR's call.
- **BlueMarlin tenant alert behavior.** BlueMarlin is deprecated per Brief 238. We add `business.slug` + `business.dashboard_url` to its client.json for schema consistency, but BlueMarlin doesn't fire alerts (no live channels post-Brief-238).

## Why This Approach

Three options were considered for HTML email support:

**A — Add optional `html_body` kwarg to existing `smtp_send` (chosen).** Single function still owns email sending. Multipart/alternative is the standard MIME pattern for "render HTML if you can, otherwise fall back to text" — every email client knows what to do. Backward-compat: existing 6+ callers of `smtp_send` (Marina email reply, escalation email, appointment email, the new alert dispatchers) pass plain only and get unchanged behavior. Single-line additive.

**B — New `smtp_send_html(to, subj, text_body, html_body)` function.** Rejected. Two functions to keep in sync (auth flow, headers, error handling). Future drift risk. The kwarg approach scales better as we add more rich-email flows.

**C — Switch entirely to HTML, drop plain text.** Rejected. Some email clients/readers (notably accessibility tools, text-only mail clients on the VPS itself when an operator SSH-checks email) need text. Multipart/alternative gives both at the cost of one extra MIME part — negligible.

Three options for the deep-link path shape:

**1 — Path-based: `https://dashboard.unboks.org/{tenant}/escalations/{id}` (chosen).** Cleanest URL — readable, RESTful, matches the API routing (`api.unboks.org/api/{tenant}/...`) Calvin's already familiar with. Path segments make the tenant + item type + item id structurally clear.

**2 — Query-string: `https://dashboard.unboks.org/{tenant}?view=escalations&escalationId={id}`.** Workable fallback if SR's React Router doesn't have nested routes set up yet. Same backend produces either shape. We ship path-based; SR can ask for query-string in a follow-up if the path shape isn't supported.

**3 — Single combined param: `https://dashboard.unboks.org/?goto=unboks/escalations/123`.** Rejected. Implicit tenant routing is brittle and mixes concerns.

For the link-missing-fallback behavior:

**A — Always include the link block, even if generated badly.** Risky — broken/half-link could lead to 404s, dead URLs in the operator's inbox.

**B — Skip the link block entirely if `business.slug` or `business.dashboard_url` is missing (chosen).** When `_resolve_dashboard_link` returns empty, `_fire_*_alerts` passes plain-only to `smtp_send` (no `html_body`). Operator gets the existing pre-Brief-243 email shape — slightly less convenient, but no broken UI. Defensive default for misconfigured tenants.

## Instructions

### Step 1a — Add `business.slug` + `business.dashboard_url` to local repo client.json files

For each of `clients/bluemarlin/config/client.json`, `clients/adamus/config/client.json`, `clients/unboks/config/client.json`: add two new keys to the `business` block. Use the Edit tool or a Python script (Edit may be unreliable; the codebase has used Python `json.load`/`json.dump` for similar additions in Brief 238).

```json
"business": {
  ...existing fields...
  "slug": "unboks",
  "dashboard_url": "https://dashboard.unboks.org"
}
```

Slug values:
- `unboks` for `clients/unboks/config/client.json`
- `bluemarlin` for `clients/bluemarlin/config/client.json`
- `adamus` for `clients/adamus/config/client.json`

`dashboard_url` is the same `https://dashboard.unboks.org` for all three (one shared dashboard project; per-tenant routing via slug). Per-tenant override is supported by the helper if a future tenant gets its own dashboard origin.

### Step 1b — Add same fields to Consulta Despertares on the VPS via SSH

`/root/clients/consultadespertares/config/client.json` is VPS-only (not version-controlled). Patch in place via SSH+Python with timestamped backup. Same pattern Brief 238 used:

```bash
ssh root@108.61.192.52 "python3 - <<'PY'
import json, os, shutil
p = '/root/clients/consultadespertares/config/client.json'
shutil.copy(p, p + '.bak.brief243')
with open(p) as f:
    cfg = json.load(f)
biz = cfg.setdefault('business', {})
biz['slug'] = 'consultadespertares'
biz['dashboard_url'] = 'https://dashboard.unboks.org'
tmp = p + '.tmp'
with open(tmp, 'w') as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
os.replace(tmp, p)
print('Consulta config patched. Backup at', p + '.bak.brief243')
print('slug:', cfg['business'].get('slug'))
print('dashboard_url:', cfg['business'].get('dashboard_url'))
PY"
```

### Step 2 — Extend `smtp_send` in `wtyj/agents/marina/email_adapter.py`

Modify the function signature + body. The MIMEMultipart structure changes from "mixed" (default) to "alternative" when html_body is provided. When None, current behavior preserved exactly:

```python
def smtp_send(to_addr: str, subject: str, body: str,
              in_reply_to=None, references=None, reply_to=None,
              html_body: str = None):
    """Brief 204: Gmail app password mode when EMAIL_PASSWORD is set; else
    Microsoft OAuth XOAUTH2 (existing path).

    Brief 243: when html_body is provided, send multipart/alternative
    with both text/plain and text/html parts. Email clients render the
    HTML version; clients that strip HTML (or text-only readers) get the
    plain `body`. When html_body is None (default), current single-part
    plain-text behavior is unchanged."""
    # Brief 243: switch to multipart/alternative when an HTML body is
    # supplied, so the text part is the explicit fallback. Default
    # MIMEMultipart() subtype is 'mixed' which is wrong for this
    # purpose - clients may show both parts as separate attachments.
    if html_body is not None:
        msg = MIMEMultipart('alternative')
    else:
        msg = MIMEMultipart()
    msg["From"] = "Marina <{}>".format(EMAIL_ADDR)
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=EMAIL_ADDR.split("@")[1])
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    if reply_to:
        msg["Reply-To"] = reply_to
    # Brief 243: text part FIRST so HTML-stripping clients pick it as
    # the body. RFC 2046 says clients should prefer the LAST acceptable
    # part in multipart/alternative — but text-only clients ignore the
    # HTML and pick text. The order matters for plain-text clients that
    # render the first text part they understand.
    msg.attach(MIMEText(body, "plain", "utf-8"))
    if html_body is not None:
        msg.attach(MIMEText(html_body, "html", "utf-8"))

    # ...rest of function unchanged (Gmail app password / Microsoft
    # OAuth XOAUTH2 paths use msg.as_string() which serializes the
    # multipart structure automatically)...
```

The Gmail and Microsoft auth paths (lines 139-160) use `msg.as_string()` for the actual SMTP send — both work transparently with multipart/alternative. No changes needed below the `attach` calls.

### Step 3 — New helpers in `wtyj/dashboard/api.py`

Place above `_fire_appointment_alerts` (around line 1698) — between `_build_appointment_body` (line 1678) and `_fire_appointment_alerts` (line 1698) so both dispatchers reach the helpers — just below the existing `_build_alert_body` and `_build_appointment_body` helpers from Briefs 239 + 241.

```python
def _resolve_dashboard_link(item_kind: str, item_id: int) -> str:
    """Brief 243: build a deep-link URL into the operator dashboard for
    a specific escalation or appointment. Reads business.slug and
    business.dashboard_url from the tenant's client.json. Returns empty
    string when either is missing - dispatchers fall back to plain-text
    email body in that case (no broken link rendered).

    item_kind: 'escalation' or 'appointment'.
    item_id: integer row id (escalation_id or appointment_id).
    """
    try:
        biz = config_loader.get_business() or {}
        slug = (biz.get("slug") or "").strip()
        base = (biz.get("dashboard_url") or "").rstrip("/").strip()
    except Exception:
        return ""
    if not slug or not base:
        return ""
    if item_kind == "escalation":
        path = "escalations"
    elif item_kind == "appointment":
        path = "appointments"
    else:
        return ""  # unknown item kind - defensive
    return f"{base}/{slug}/{path}/{item_id}"


def _build_alert_html_body(text_body: str, link_url: str,
                            link_label: str) -> str:
    """Brief 243: render the plain-text alert body as HTML with a CTA
    button + fallback URL. Inline CSS only (Gmail-safe). The text body
    is wrapped in <pre> to preserve operator at-a-glance scan layout.

    Button styling: blue #1a73e8 background, white text, 12px padding,
    4px border-radius, no underline, sans-serif font. Works in Gmail,
    Outlook, Apple Mail, mobile clients."""
    import html
    safe_text = html.escape(text_body or "")
    safe_url = html.escape(link_url or "", quote=True)
    safe_label = html.escape(link_label or "Open dashboard")
    return (
        "<!DOCTYPE html>"
        "<html><body style=\"font-family: -apple-system, BlinkMacSystemFont, "
        "'Segoe UI', Roboto, sans-serif; color: #202124;\">"
        f"<pre style=\"font-family: inherit; white-space: pre-wrap; "
        f"font-size: 14px; margin: 0 0 16px 0;\">{safe_text}</pre>"
        f"<p style=\"margin: 16px 0;\">"
        f"<a href=\"{safe_url}\" "
        f"style=\"display: inline-block; background-color: #1a73e8; "
        f"color: #ffffff; text-decoration: none; padding: 12px 24px; "
        f"border-radius: 4px; font-weight: 500;\">{safe_label}</a>"
        f"</p>"
        f"<p style=\"font-size: 12px; color: #5f6368; margin: 16px 0 0 0;\">"
        f"Plain link:<br>"
        f"<a href=\"{safe_url}\" style=\"color: #1a73e8;\">{safe_url}</a>"
        f"</p>"
        "</body></html>"
    )
```

`html.escape` import inside the helper to keep the module top unchanged (one-line cost, scoped to where it's needed).

### Step 4 — Wire into `_fire_escalation_alerts`

In the email-send loop inside `_fire_escalation_alerts` (`dashboard/api.py:~1864-1870`; the dispatcher itself is defined at line 1813), wrap the `smtp_send(...)` call with link resolution + optional html_body. Currently:

```python
for dest in recipients:
    try:
        smtp_send(dest, email_subject, alert_text)
        state_registry.record_alert_delivery(escalation_id, "email", dest, "sent")
    except Exception as exc:
        state_registry.record_alert_delivery(
            escalation_id, "email", dest, "failed", str(exc)[:200])
```

After this brief:

```python
# Brief 243: build deep-link to this escalation. Empty string when
# tenant config lacks business.slug or business.dashboard_url -
# smtp_send falls back to plain text only.
_link_url = _resolve_dashboard_link("escalation", escalation_id)
_html_body = (
    _build_alert_html_body(alert_text, _link_url, "Open escalation")
    if _link_url else None
)
for dest in recipients:
    try:
        smtp_send(dest, email_subject, alert_text, html_body=_html_body)
        state_registry.record_alert_delivery(escalation_id, "email", dest, "sent")
    except Exception as exc:
        state_registry.record_alert_delivery(
            escalation_id, "email", dest, "failed", str(exc)[:200])
```

Link resolution happens ONCE per dispatcher fire, OUTSIDE the per-recipient loop (the link is identical for every recipient — same escalation, same dashboard route).

### Step 5 — Wire into `_fire_appointment_alerts`

Same pattern in `_fire_appointment_alerts` (`dashboard/api.py:~1698`; email-send loop at 1739-1751). Find the email-send loop, build the link + html_body once, pass through.

```python
_link_url = _resolve_dashboard_link("appointment", appointment_id)
_html_body = (
    _build_alert_html_body(alert_text, _link_url, "Open appointment")
    if _link_url else None
)
for dest in recipients:
    if state_registry.appointment_alert_already_sent(
            appointment_id, "email", dest):
        continue
    try:
        smtp_send(dest, email_subject, alert_text, html_body=_html_body)
        state_registry.record_alert_delivery(
            None, "email", dest, "sent",
            alert_type="appointment", appointment_id=appointment_id)
    except Exception as exc:
        state_registry.record_alert_delivery(
            None, "email", dest, "failed", str(exc)[:200],
            alert_type="appointment", appointment_id=appointment_id)
```

WhatsApp / Telegram / Messenger branches in both dispatchers stay UNCHANGED — only the email branch gets the html_body.

### Step 6 — Tests in `wtyj/tests/social/test_217_alert_delivery.py` (EXTEND)

Add 5 new tests at the bottom. Reuse `_wipe_appointments_for` and `_wipe_escalations_for` helpers from Briefs 240/241.

```python
# ── Brief 243: HTML deep-link buttons in alert emails ──────────────────

def test_resolve_dashboard_link_builds_path_when_slug_and_url_present(monkeypatch):
    """Brief 243: helper builds 'dashboard_url/slug/escalations/id' when
    both business.slug and business.dashboard_url are configured."""
    from dashboard import api as dapi
    monkeypatch.setattr(dapi.config_loader, "get_business",
                         lambda: {"slug": "unboks",
                                   "dashboard_url": "https://dashboard.unboks.org"})
    url = dapi._resolve_dashboard_link("escalation", 42)
    assert url == "https://dashboard.unboks.org/unboks/escalations/42"
    url2 = dapi._resolve_dashboard_link("appointment", 7)
    assert url2 == "https://dashboard.unboks.org/unboks/appointments/7"


def test_resolve_dashboard_link_returns_empty_when_slug_missing(monkeypatch):
    """Brief 243: helper returns empty string when business.slug is
    absent. Dispatchers use this to fall back to plain-text email."""
    from dashboard import api as dapi
    monkeypatch.setattr(dapi.config_loader, "get_business",
                         lambda: {"dashboard_url": "https://dashboard.unboks.org"})
    assert dapi._resolve_dashboard_link("escalation", 42) == ""


def test_build_alert_html_body_includes_button_and_fallback_url():
    """Brief 243: HTML body renders the plain text inside <pre>, the CTA
    button as a styled anchor, and a 'Plain link' fallback URL block."""
    from dashboard import api as dapi
    text = "Escalation alert\n\nCustomer: Calvin\nReason:\nNeeds scheduling decision."
    url = "https://dashboard.unboks.org/unboks/escalations/42"
    html = dapi._build_alert_html_body(text, url, "Open escalation")
    assert "<pre" in html
    assert "Customer: Calvin" in html
    assert f'href="{url}"' in html
    assert ">Open escalation<" in html
    assert "background-color: #1a73e8" in html
    assert "Plain link:" in html


def test_escalation_dispatcher_passes_html_body_when_link_resolves(monkeypatch):
    """Brief 243: when business.slug+dashboard_url are set, the
    escalation dispatcher passes html_body to smtp_send. The text body
    is unchanged; the HTML body wraps it with the CTA button."""
    from dashboard import api as dapi
    from shared import state_registry
    monkeypatch.setattr(dapi.config_loader, "get_business",
                         lambda: {"name": "Unboks", "slug": "unboks",
                                   "dashboard_url": "https://dashboard.unboks.org",
                                   "support_email": "ops@example.com"})
    captured = {}
    def fake_smtp(to, subj, body, html_body=None, **kw):
        captured.update(to=to, subj=subj, body=body, html_body=html_body)
    monkeypatch.setattr(dapi, "smtp_send", fake_smtp)
    monkeypatch.setattr(state_registry, "get_alert_settings",
                         lambda **k: {"alertTypes": {"escalations": True, "appointments": True},
                                       "channels": {"email": {"enabled": True,
                                                                "destination": "ops@example.com",
                                                                "alternativeDestination": ""}}})
    monkeypatch.setattr(state_registry, "record_alert_delivery",
                         lambda *a, **k: None)
    dapi._fire_escalation_alerts(
        escalation_id=42, customer_name="Calvin", channel="whatsapp",
        summary="ignored", mode="soft",
        summary_dict={"reason": "needs scheduling",
                       "operatorNeedsToDecide": "pick a time",
                       "recommendedOptions": ["Confirm Friday 12:00"],
                       "extractedDetails": {"intent": "scheduling",
                                              "proposedTimes": ["Friday 12:00"]},
                       "latestCustomerMessage": "i wanna do friday 12:00"},
        is_update=False)
    assert captured["html_body"] is not None
    assert "https://dashboard.unboks.org/unboks/escalations/42" in captured["html_body"]
    assert ">Open escalation<" in captured["html_body"]
    # Plain text body still includes the original "Action:" line
    # unchanged - the link is in the HTML body, not the text.
    assert "Open the dashboard" in captured["body"] or "Open dashboard" in captured["body"]


def test_appointment_dispatcher_passes_html_body_with_appointment_link(monkeypatch):
    """Brief 243: appointment dispatcher passes html_body with the
    appointment-specific deep link + 'Open appointment' button label."""
    from dashboard import api as dapi
    from shared import state_registry
    monkeypatch.setattr(dapi.config_loader, "get_business",
                         lambda: {"name": "Unboks", "slug": "unboks",
                                   "dashboard_url": "https://dashboard.unboks.org",
                                   "support_email": "ops@example.com"})
    captured = {}
    def fake_smtp(to, subj, body, html_body=None, **kw):
        captured.update(html_body=html_body)
    monkeypatch.setattr(dapi, "smtp_send", fake_smtp)
    monkeypatch.setattr(state_registry, "get_alert_settings",
                         lambda **k: {"alertTypes": {"escalations": True, "appointments": True},
                                       "channels": {"email": {"enabled": True,
                                                                "destination": "ops@example.com",
                                                                "alternativeDestination": ""}}})
    monkeypatch.setattr(state_registry, "appointment_alert_already_sent",
                         lambda *a, **k: False)
    monkeypatch.setattr(state_registry, "record_alert_delivery",
                         lambda *a, **k: None)
    appt = {"id": 99, "conversation_id": "conv-x", "channel": "whatsapp",
            "customer_name": "Calvin", "title": "Intake call",
            "date_time_label": "Friday 12:00",
            "proposed_times": ["Friday 12:00"],
            "location": "Café Paris", "status": "confirmed"}
    dapi._fire_appointment_alerts(99, "Calvin", "whatsapp", appt)
    assert captured["html_body"] is not None
    assert "https://dashboard.unboks.org/unboks/appointments/99" in captured["html_body"]
    assert ">Open appointment<" in captured["html_body"]
```

Five tests. Each asserts specific behavioral output (URL string, HTML markup, button label). No source-string greppers; no mock-the-thing-you-test (smtp_send is a boundary mock — external service).

**Regression baseline:** 1042 passing / 0 failures (per Brief 242 system_state). After this brief: **1047 passing / 0 failures** (1042 + 5 new).

## Success Condition

After execution:

1. `python3 -m pytest wtyj/tests/social/test_217_alert_delivery.py -q` passes (existing 29 + 5 new = 34).
2. `python3 -m pytest wtyj/tests/ -q` reports 1047 passing / 0 failures.
3. `python3 -c "import json; print(json.load(open('clients/unboks/config/client.json'))['business']['slug'], json.load(open('clients/unboks/config/client.json'))['business']['dashboard_url'])"` prints `unboks https://dashboard.unboks.org`. Same for bluemarlin/adamus with their respective slugs.
4. After deploy, `ssh root@VPS "docker exec wtyj-unboks python3 -c 'from shared import config_loader; b=config_loader.get_business(); print(b.get(\"slug\"), b.get(\"dashboard_url\"))'"` returns `unboks https://dashboard.unboks.org`. Same query against `wtyj-consultadespertares` returns `consultadespertares https://dashboard.unboks.org`.
5. Trigger a test escalation alert (via `state_registry.create_pending_notification(...)` from a docker exec or wait for a real one): inspect the resulting email — body has the HTML CTA button labeled "Open escalation" linking to `https://dashboard.unboks.org/unboks/escalations/<id>` AND a "Plain link:" fallback line. WhatsApp alert text unchanged.
6. CI green; all 4 containers healthy. Brief 238 tenant guard / Brief 239 rich body / Brief 240 Zernio route / Brief 241 dispatcher / Brief 242 confirm endpoint all preserved.

## Rollback

Code-only rollback: `git revert <this brief's source commit>` and push. Pipeline auto-deploys (~90s). The 2 new client.json fields in repo (`business.slug`, `business.dashboard_url`) revert with the commit; tenant containers continue working without them (helper returns empty link → dispatcher falls back to plain-text email — pre-Brief-243 behavior). The Consulta VPS-only config additions stay (no harm: extra unused fields).

To roll back the Consulta VPS config edit: `ssh root@VPS "cp /root/clients/consultadespertares/config/client.json.bak.brief243 /root/clients/consultadespertares/config/client.json && cd /root/clients/consultadespertares && docker compose restart"`.

If only the HTML email rendering is misbehaving (e.g., a particular tenant's link looks broken), set `business.dashboard_url` to empty string in that tenant's `client.json` and `docker compose restart` — `_resolve_dashboard_link` returns empty, dispatcher passes plain-only to smtp_send, operator gets the pre-Brief-243 email shape until a fix ships. No code revert needed.
