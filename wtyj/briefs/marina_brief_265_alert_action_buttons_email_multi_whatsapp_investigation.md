# BRIEF 265 — Email alert multi-button row + WhatsApp Zernio interactive-button investigation
**Status:** Draft | **Files:** `wtyj/dashboard/api.py`, `wtyj/tests/social/test_217_alert_delivery.py` | **Depends on:** Brief 243 (single-button HTML CTA), Brief 256 (compact WA body) | **Blocks:** issue #33 verification

## Context

Issue #33 P1 (Calvin product request): operator alerts should be **actionable** directly from email and WhatsApp, not just informational.

**Part A — Email**: Calvin wants clear HTML action buttons. Existing system at `dashboard/api.py:2571` (`_build_alert_html_body`, Brief 243) renders **one** inline button (`Open escalation` or `Open appointment`) plus a plain-text fallback link. Calvin's spec: add Open dashboard alongside the existing escalation/appointment button. (Mark resolved is conditional on a safe authenticated deep-link flow — we have no magic-link token system today, so Mark resolved stays out per Calvin's "only if safe" qualifier.)

**Part B — WhatsApp**: Calvin asks Brief 265 to **investigate** Zernio capability for interactive buttons, not guess. Audit:
- `wtyj/agents/social/zernio_dm_client.py:99` exposes `send_dm_reply(conversation_id, account_id, text)` which calls `client.inbox.send_inbox_message(message=text)`. The SDK signature takes a plain text string. No `interactive=` / `buttons=` / `template_components=` parameter is visible in the SDK surface or in any existing usage in the codebase.
- No other Zernio call site in `wtyj/` (verified by grep) constructs a button payload.
- Unboks runs on Zernio NOT Meta Cloud API direct (per session memory + `wtyj/briefs/infra.md` Brief 143/240 entries). The Meta app was archived; bypassing Zernio for direct Cloud API interactive messages is not on the table.

**Verified finding**: the current Zernio SDK surface does not expose interactive WhatsApp buttons. Adding them would require either (a) Zernio adding interactive-button support to their Inbox API + SDK, or (b) migrating WhatsApp operator alerts off Zernio to Meta Cloud API direct (out of scope — Meta app archived per Brief 143 era, would need a fresh Meta Business app registration).

**Calvin's spec rule 5**: *"If not supported, provide a numbered fallback and exact reason."* Brief 265 ships the **exact reason** (this brief Context) and explicitly does NOT add a numbered "Reply with 1/2/3" fallback to the WhatsApp compact body because:
- The numbered text alone is misleading without a Zernio inbound webhook handler that PARSES operator replies like `1` / `2` / `3` and routes them to dashboard actions. That handler doesn't exist.
- Adding the numbered text without the parser would set false expectations (operator types `1`, nothing happens — worse than no buttons at all).
- The reply-parser is a substantial separate brief (Zernio webhook handler updates + state machine for "is this an operator command vs customer message" disambiguation). Out of scope for #33.

Brief 265 therefore ships: (a) email multi-button row, (b) honest Zernio finding documented in OUTPUT + Brief context. If Calvin wants the reply-parser fallback shipped, that's a focused follow-up brief.

## Why This Approach

Three options considered:

1. **Extend `_build_alert_html_body` to render a horizontal row of buttons; add a second "Open dashboard" button; defer WhatsApp interactive-button work pending Zernio capability (chosen)** — adds the Open dashboard button to escalation + appointment alert emails. Uses the same inline-CSS pattern from Brief 243 (Gmail-safe). Plain-text fallback list grows from one URL to two. Email path stays the only changed code; WhatsApp untouched. ~30 LOC + 3 tests.

2. **Add 3+ buttons to email (Open escalation + View conversation + Open dashboard); ship numbered fallback for WhatsApp without the reply-parser** — bigger surface; "View conversation" requires a frontend route SR may not have wired (`{base}/{slug}/inbox/{customer_id}` shape — unverified); numbered WhatsApp text without the reply-parser is actively misleading per the Context analysis. Rejected as scope creep.

3. **Wait for Zernio interactive-button support, ship full feature when available** — Calvin's spec is clear that the investigation finding is part of the deliverable. Rejected; waiting is not delivering.

Trade-off accepted (option 1): the dashboard-root URL `{base}/{slug}` is a soft target (it goes to whatever SR's tenant landing page is — currently the Inbox view). It's still useful as a "go to your dashboard" fallback when the operator wants context beyond the specific escalation/appointment. If SR adds a dedicated `/{tenant}/dashboard` landing page later, the URL pattern can be updated in `_resolve_dashboard_link` without changing this brief's structure.

## Instructions

1. **Extend `_resolve_dashboard_link`** at `wtyj/dashboard/api.py:2544` with an `item_kind="dashboard"` branch returning the dashboard root URL `{base}/{slug}` (no item id). Add to the existing if/elif chain just after the `escalation` and `appointment` branches:
   ```python
   if item_kind == "escalation":
       path = "escalations"
   elif item_kind == "appointment":
       path = "appointments"
   elif item_kind == "dashboard":
       # Brief 265: top-level dashboard root for the "Open dashboard"
       # button in alert emails. No item id appended; the frontend's
       # tenant landing page handles the slug-only URL.
       return f"{base}/{slug}"
   else:
       return ""
   return f"{base}/{slug}/{path}/{item_id}"
   ```

2. **Refactor `_build_alert_html_body`** at `wtyj/dashboard/api.py:2571` to accept a list of buttons instead of a single (link_url, link_label) pair. Preserve backward compat by accepting either the old shape (positional `link_url` + `link_label` strings → wraps into a single-button list) or a new `buttons` kwarg (list of `(url, label)` tuples).

   New signature:
   ```python
   def _build_alert_html_body(text_body: str,
                                link_url: str = "",
                                link_label: str = "",
                                buttons: list = None) -> str:
       """Brief 243 + Brief 265: render the plain-text alert body as HTML
       with one or more inline CTA buttons + plain-text fallback URLs.

       Backward compat: callers passing (text_body, link_url, link_label)
       positionally get a single-button render (Brief 243 behavior). New
       callers can pass `buttons=[(url, label), ...]` for a multi-button
       horizontal row. The fallback "Plain link:" section lists all URLs
       so text-only mail clients still get every link."""
       if buttons is None:
           buttons = []
           if link_url:
               buttons.append((link_url, link_label or "Open dashboard"))
       # ... render each button inline ...
   ```

   Render the buttons as a horizontal flex row (Gmail-safe via inline-block spans separated by 8px right margin). Each button reuses the existing blue `#1a73e8` background + 12px/24px padding + 4px border-radius styling. Plain-text fallback at the bottom lists all URLs, one per line.

3. **Update the email-alert dispatch sites** to pass a multi-button list:

   `_fire_appointment_alerts` (`dashboard/api.py:2604+`) — change the `_link_url` + `_html_body` block to build a buttons list:
   ```python
   _appt_link = _resolve_dashboard_link("appointment", appointment_id)
   _dash_link = _resolve_dashboard_link("dashboard", 0)
   _buttons = []
   if _appt_link:
       _buttons.append((_appt_link, "Open appointment"))
   if _dash_link:
       _buttons.append((_dash_link, "Open dashboard"))
   _html_body = (
       _build_alert_html_body(alert_text, buttons=_buttons)
       if _buttons else None
   )
   ```

   `_fire_escalation_alerts` (`dashboard/api.py:2750+`, the email branch around line 2788) — same pattern with `("escalation", escalation_id)` and `("dashboard", 0)`.

4. **No WhatsApp changes.** The WA branch in `_fire_escalation_alerts` continues to use `_build_alert_body_whatsapp` (Brief 256/257 compact format). Brief 265 explicitly does NOT add numbered "Reply with 1/2/3" text because the inbound reply-parser doesn't exist; adding it would mislead operators.

5. **No changes to `_build_alert_body` / `_build_alert_body_whatsapp` / `_build_alert_subject`** (Brief 239/256/257 helpers preserved unchanged).

## Tests

Append 3 tests to `wtyj/tests/social/test_217_alert_delivery.py` (canonical per-module file Brief 217 named; extended by Briefs 239/240/241/243/247/256/257). Real TestClient round-trips + direct helper calls.

1. **test_brief_265_email_alert_renders_two_buttons** — call `_build_alert_html_body(text="Test", buttons=[("https://dash.test/u/escalations/1", "Open escalation"), ("https://dash.test/u", "Open dashboard")])`. Assert response HTML contains BOTH `>Open escalation<` AND `>Open dashboard<` anchor labels. Assert both URLs appear in the plain-link fallback section. Assert no extra/leaked anchors (count `<a` occurrences equals 4 — 2 buttons + 2 fallback links).

2. **test_brief_265_email_alert_backward_compat_single_button** — call `_build_alert_html_body(text="Test", link_url="https://dash.test/x", link_label="View")` (positional Brief 243 style). Assert response HTML contains exactly ONE button anchor (`>View<`) AND the plain-link section shows the single URL. Proves backward compatibility for any caller still using the old signature.

3. **test_brief_265_resolve_dashboard_link_supports_dashboard_root** — monkeypatch `config_loader.get_business` to return `{"slug": "unboks", "dashboard_url": "https://dashboard.unboks.org"}`. Call `_resolve_dashboard_link("dashboard", 0)`. Assert response is `"https://dashboard.unboks.org/unboks"` (no `/dashboard/0` suffix). Then `_resolve_dashboard_link("escalation", 42)` → `"https://dashboard.unboks.org/unboks/escalations/42"` (regression guard for the existing escalation branch).

## Success Condition

After Brief 265 deploys:
- An email escalation alert renders TWO inline buttons (`Open escalation` + `Open dashboard`) AND a plain-link fallback listing both URLs.
- An email appointment alert renders TWO inline buttons (`Open appointment` + `Open dashboard`) AND a plain-link fallback.
- WhatsApp alerts unchanged from Brief 256/257 compact format.
- No tokens or secrets in any URL (verified by inspection: `_resolve_dashboard_link` reads only `business.slug` + `business.dashboard_url` from `client.json`, both non-secret).
- All 4 production containers healthy post-deploy.
- OUTPUT documents the Zernio interactive-button finding (no SDK support today; Meta direct path blocked by archived app; numbered-reply fallback deferred pending reply-parser brief).

## Rollback

```
ssh root@108.61.192.52 "bash /root/wtyj/scripts/rollback.sh all"
```

Canonical rollback per `wtyj/briefs/infra.md:188`. Pure additive change to existing helpers (`_resolve_dashboard_link` gains a new branch; `_build_alert_html_body` adds a kwarg with backward-compat default). No schema migration. The Brief 243 single-button rendering remains the fallback path if any caller doesn't pass the new `buttons` kwarg. Revert restores the pre-Brief-265 single-button behavior in <30s.
