# EXPLANATION 217 — Escalation alert delivery

Plain-English explanation of commit `91eff7b` for an operator who doesn't read code.

## What was missing

When a customer triggered an escalation (Marina hits `[ESCALATE]`, customer asks for a human, complaint, refund request), a row landed in the dashboard's Escalations tab. **But nothing pinged you.** You had to be looking at the dashboard to know there was one. Useless for cases where the escalation matters most — outside business hours.

Brief 217 wires up alerts: the moment an escalation is created, the backend pings the operator on configured channels.

## What changed

**Two new endpoints in Settings:**
- `GET /settings/escalation-alerts` — returns your current configuration (which channels are enabled, what destination for each).
- `PUT /settings/escalation-alerts` — saves changes.

**Settings UI shape** (per SR's contract):
```
{
  "channels": {
    "email":    { "enabled": true,  "destination": "ops@example.com" },
    "whatsapp": { "enabled": true,  "destination": "+15551234567" },
    "telegram": { "enabled": false, "destination": "" },
    "messenger":{ "enabled": false, "destination": "" }
  }
}
```

Email is enabled by default. The default destination is the `support_email` from your `client.json`. WhatsApp is opt-in: you type your personal/private phone (NOT the business WhatsApp), and that's where the alert goes. Telegram and Messenger are visible but inert — we don't have those provider integrations wired today, so they record `status="skipped: provider not configured"` if you enable them. When SR asks for them, that's a follow-up brief (one provider integration each).

**The alert message format:**
```
New escalation in BlueMarlin Charters

Customer: Calvin Adamus
Channel: whatsapp
Mode: (unset)
Summary: I want to speak to a human
Action: Open dashboard to review.
```

Mode shows `(unset)` for newly-created escalations because Brief 213's mode column is set AFTER row creation (when you click soft/hard in the dashboard). Once you pick a mode, subsequent alerts on that same conversation won't fire — escalations are one-shot rows.

**Per-attempt audit log.** Every alert dispatch writes a row to `alert_deliveries`: `{escalation_id, channel, destination, status, error?, sent_at}`. If WhatsApp fails because Zernio is down, you'll see `status="failed"` with the error string. Useful for debugging when an alert didn't arrive.

**Best-effort.** Critical: if the alert dispatcher crashes (network down, Zernio API rate limit, anything), the escalation row STILL gets saved. Alerts are a side effect; the durable artifact is the escalation row in the dashboard. You can always see escalations in the dashboard regardless of alert state.

**Marina's "ask the team" flow does NOT trigger alerts.** She uses the same internal mechanism as escalations to ask the team a question (relay flow), but those aren't the "human needed now" event SR's contract describes. Reviewer caught this — would have spammed your phone every time Marina had a question.

## What it does now

- Set up your alert config in Settings → Escalation Alerts. WhatsApp gets your personal number. Email defaults to your support email.
- Customer triggers an escalation → within seconds, you get a WhatsApp message + email with the customer name, channel, and a one-line summary.
- Open the dashboard from the alert to handle the escalation.

## What it doesn't do (deferred)

- Telegram and Messenger alerts — providers not wired. Future brief.
- Per-tenant rate limiting — if 10 escalations fire in 30 seconds, you get 10 alerts. Could batch later if it becomes noisy.
- Different mode messages for soft vs hard — alert text says "(unset)" until you pick a mode, then subsequent alerts never fire on that escalation.

## Files changed

- `wtyj/shared/state_registry.py` — two new tables (`alert_settings`, `alert_deliveries`); pluggable callback (`_alert_dispatcher` + `set_alert_dispatcher`); 3 helpers (get/save/record); hook in `create_pending_notification` gated on escalation rows.
- `wtyj/dashboard/api.py` — `_fire_escalation_alerts` dispatcher; GET/PUT `/settings/escalation-alerts` endpoints.
- `wtyj/tests/social/conftest.py` — autouse fixture resets alert_settings to all-disabled before each test in this directory so legacy tests don't see surprise alert sends.
- `wtyj/tests/social/test_217_alert_delivery.py` — 9 tests covering settings round-trip, dispatch on escalation, no-dispatch on relay (regression guard), best-effort failure handling, telegram/messenger skipped status.
