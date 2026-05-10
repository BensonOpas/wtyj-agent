# BRIEF 241 — Appointment alerts using shared alert destinations (TASK-074)

**Status:** Draft | **Files:** `wtyj/shared/state_registry.py` (2 ALTER ADD COLUMN on `alert_deliveries` for `alert_type` + `appointment_id`; 2 ALTER ADD COLUMN on `alert_settings` for `alert_type_escalation_enabled` + `alert_type_appointment_enabled`; extend `record_alert_delivery` with optional `alert_type` + `appointment_id` kwargs; add `appointment_alert_already_sent` helper; modify `appointment_upsert` to detect transition-to-confirmed and fire the dispatcher; add `_appointment_alert_dispatcher` global + `set_appointment_alert_dispatcher`; extend `get_alert_settings` and `save_alert_settings` with the alertTypes block), `wtyj/dashboard/api.py` (new `_fire_appointment_alerts` + `_build_appointment_subject` + `_build_appointment_body` helpers; register dispatcher at module load via `state_registry.set_appointment_alert_dispatcher(_fire_appointment_alerts)`; modify `_fire_escalation_alerts` to short-circuit when `alertTypes.escalations is False`; modify the `AlertChannelConfig` Pydantic model + `get/put` endpoints to accept and return the new top-level `alertTypes` block), `wtyj/tests/social/test_217_alert_delivery.py` (EXTEND with 6 new behavioral tests + reuse `_wipe_*` helpers from Brief 240) | **Depends on:** Brief 217 (alert dispatcher + alert_settings + alert_deliveries), Brief 226 (alternative email destination + INSERT OR REPLACE pattern that Brief 240 fixed), Brief 228 (appointments table + `appointment_upsert` + escalation_dispatcher's appointment-row-write hook), Brief 235 (escalation_dispatcher refactor — appointment_upsert is currently called from there with status='detected'/'pending_team_confirmation', never 'confirmed'), Brief 240 (Zernio operator route + ON CONFLICT DO UPDATE in save_alert_settings + record_alert_delivery is the one this brief generalizes) | **Blocks:** Future operator dashboard endpoint or Marina-side detection that promotes appointment status to `confirmed` (see "Reachability gap" in Context — the dispatcher this brief installs is dormant until SOMEONE calls `appointment_upsert(..., status='confirmed', ...)`).

## Context

Issue #4 asks for appointment alerts in addition to escalation alerts, reusing the same destinations (default email + alternative email + WhatsApp via Brief 240's Zernio route + Telegram/Messenger placeholders). Calvin/Jr2 explicitly says: "Send appointment alert only when final confirmation is explicit." Negative cases enumerated:

> Do NOT send when: customer only asks to book, Marina asks for time slots, customer gives multiple proposed slots, operator chooses one slot but final confirmation is still pending, Marina says "team will confirm", status is detected, status is needs_operator_decision, status is pending_team_confirmation, status is pending_customer_confirmation. Safest initial trigger: `confirmed` only.

### Current appointment lifecycle (verified read-only)

`appointments` table (`wtyj/shared/state_registry.py:497-510`): `id INTEGER PK`, `conversation_id TEXT UNIQUE`, `channel TEXT`, `customer_name TEXT`, `title TEXT`, `date_time_label TEXT`, `proposed_times_json TEXT`, `location TEXT`, `status TEXT NOT NULL DEFAULT 'detected'`, `source TEXT`, `created_at`, `updated_at`. The UNIQUE constraint on `conversation_id` is what makes `appointment_upsert` an upsert.

`appointment_upsert` (state_registry.py:2040-2075): keyed on `conversation_id`, UPDATEs if exists, INSERTs if not. Returns row_id. Currently does NOT detect transitions; just writes whatever status the caller passes.

Only call site today: `wtyj/shared/escalation_dispatcher.py:74-86` inside `_generate_escalation_summary`. Calls `appointment_upsert` with `status="pending_team_confirmation"` when summary has scheduling intent + proposed_times non-empty, else `status="detected"`. **Never with `status="confirmed"`.**

Grep across the source tree confirms: no other code path calls `appointment_upsert`. No code path currently sets `appointments.status = 'confirmed'`. The dashboard's `GET /appointments` endpoint is read-only (`dashboard/api.py:1784-1790`); no POST/PUT to confirm exists yet.

### Reachability gap (intentional, documented)

This brief installs the alert dispatcher and the trigger inside `appointment_upsert`. Once shipped, ANY future code that calls `appointment_upsert(..., status='confirmed', ...)` AND the previous status was not 'confirmed' AND alertTypes.appointments is enabled → alerts fire. Until that future caller exists (operator dashboard endpoint to confirm OR Marina-side customer-confirmation detection), the dispatcher is dormant in production. Tests exercise the trigger by calling `appointment_upsert` directly with `status='confirmed'` — that's a real behavioral assertion of the wired path.

This is acceptable because issue #4 said: "When an appointment, booking, order, or scheduled call becomes confirmed, send an Appointment Alert" — it asks for the alert wiring, not the upstream confirmation signal. The signal is a separate product decision (operator clicks "Confirm" in dashboard? Marina detects "yes Friday 12:00 works for me" from the customer? Both?). Out of scope here; flag for the next brief.

### `alert_deliveries` schema today vs needed

Today (state_registry.py:484-491): `id, escalation_id INTEGER (nullable), channel, destination, status, error, sent_at`. **No `alert_type`, no `appointment_id`.** Smallest safe migration: 2 ALTER ADD COLUMN, both with sensible defaults so existing rows are correctly retro-labeled and existing code keeps working.

`record_alert_delivery` today (state_registry.py:1844): `(escalation_id, channel, destination, status, error=None) -> int`. 8+ existing call sites in `_fire_escalation_alerts` (dashboard/api.py:1695-1751). Generalize by adding optional kwargs at the END so existing positional callers still work; the dispatcher passes them only for appointment alerts.

### Settings shape evolution

Today's `GET /settings/escalation-alerts` returns `{channels: {email, whatsapp, telegram, messenger}}` (with Brief 240's `whatsappZernioResolved` field). Issue #4's preferred shape adds a top-level `alertTypes: {escalations: bool, appointments: bool}` block. Picked: extend the EXISTING endpoints (don't add `/settings/alerts` — Calvin's option B). New shape is additive: pre-Brief-241 frontend ignores the new field; post-Brief-241 frontend reads it. Both schemes coexist gracefully.

The `deliveryStatus` per-channel field issue #4's example shows is intentionally NOT added — it's redundant with the existing `enabled` flag plus Brief 240's `whatsappZernioResolved` flag. If Calvin/SR push back during review, easy to add.

## Why This Approach

**Trigger placement** — three options were considered:

**A — Trigger inside `appointment_upsert`, detect transition (chosen).** The function already has the only WRITE path to `appointments`; placing the trigger there guarantees no caller can bypass it. Detect transition by reading the OLD status before the UPDATE, then comparing to the NEW status. Insert+confirmed = trigger fires; update from non-confirmed → confirmed = trigger fires; update from confirmed → confirmed (re-save) = no trigger; update from confirmed → some other status = no trigger.

**B — Separate `appointment_confirm(appointment_id)` helper with the trigger inline; require all callers to use it.** Rejected: requires callers to know to call the right helper. Easy to forget. Less robust than placing the trigger at the data-write boundary.

**C — Periodic poll of `appointments WHERE status='confirmed'` to detect new confirmations.** Rejected: race conditions with operator clicks vs poll cadence; doubles the work; doesn't reuse the existing dispatcher pattern Brief 217/240 established.

**Dedup design** — two layers:

**Layer 1 — transition-aware trigger.** `appointment_upsert` only fires the dispatcher when status TRANSITIONS into confirmed (insert with status=confirmed, OR update from non-confirmed to confirmed). Re-saves with the same confirmed status do NOT fire. This is the primary defense.

**Layer 2 — per-(appointment_id, destination) audit-log dedup.** New helper `appointment_alert_already_sent(appointment_id, channel, destination) -> bool` queries `alert_deliveries` for an existing row with `alert_type='appointment'` AND matching appointment_id + channel + destination AND `status IN ('sent', 'failed')`. The dispatcher checks this BEFORE each per-destination send. Belt-and-suspenders against any other accidental re-trigger source (e.g., a future operator endpoint that bypasses the transition detection).

`status='skipped'` is intentionally NOT in the dedup query — a destination skipped because the WhatsApp Zernio route wasn't yet bootstrapped should retry on the next confirmation event after the route resolves. (In practice the trigger only fires once per appointment lifecycle anyway, but the semantics are correct: skipped means "we didn't try", not "we tried and failed.")

**Endpoint extension** — three options were considered:

**1 — Add `GET /settings/alerts` + `PUT /settings/alerts` and keep old endpoints frozen for backward compat.** Rejected: more endpoints to maintain, more frontend code to migrate, more docs to update. Issue #4's option B but issue says "If creating new endpoints, keep old endpoints compatible for the frontend until migration is complete" — that's already 4 endpoints to maintain.

**2 — Replace the existing endpoint shape entirely (breaking change).** Rejected: SR's frontend would break.

**3 — Extend the existing `GET/PUT /settings/escalation-alerts` shape with a new top-level `alertTypes` block (chosen).** Additive. Pre-Brief-241 frontend ignores the field; post-Brief-241 frontend reads it. The `escalation-alerts` endpoint name becomes slightly off-brand (it now also configures appointment alerts) but that's cosmetic — issue #4 explicitly said extending is fine. Renaming the endpoint is its own future cleanup.

**Reachability gap acknowledgement** — see Context. The dispatcher is wired but dormant until a future caller flips an appointment to `'confirmed'`. This is honest scope: issue #4 asks for the alert wiring, not the confirmation signal. The negative cases (1-5 in acceptance) are testable today without any caller changes; the positive case (6) is testable in tests by calling `appointment_upsert(..., status='confirmed')` directly. The "in production a customer confirms → alert fires" round-trip requires the next brief that adds the confirm caller.

## Instructions

### Step 1 — Schema migrations on `alert_deliveries` and `alert_settings`

In `_get_conn` schema-migration block (`state_registry.py` near the existing Brief 226/240 ALTERs, around line 460-480), append:

```python
# Brief 241: alert_type + appointment_id columns on alert_deliveries.
# Existing rows (all from Brief 217-240 era) get retro-labeled as
# 'escalation' via the DEFAULT — semantically correct since they were all
# escalation-alert deliveries. appointment_id stays NULL for those rows.
for _coldef in (
    "ADD COLUMN alert_type TEXT NOT NULL DEFAULT 'escalation'",
    "ADD COLUMN appointment_id INTEGER",
):
    try:
        conn.execute(f"ALTER TABLE alert_deliveries {_coldef}")
    except sqlite3.OperationalError:
        pass  # column already exists

# Brief 241: per-alert-type enable flags on alert_settings (singleton row).
# Both default ON for backward compat — existing tenants continue to receive
# escalation alerts; appointment alerts begin firing once the trigger
# (appointment_upsert transition-to-confirmed) is reached for any tenant
# whose alert_type_appointment_enabled = 1 (default).
for _coldef in (
    "ADD COLUMN alert_type_escalation_enabled INTEGER NOT NULL DEFAULT 1",
    "ADD COLUMN alert_type_appointment_enabled INTEGER NOT NULL DEFAULT 1",
):
    try:
        conn.execute(f"ALTER TABLE alert_settings {_coldef}")
    except sqlite3.OperationalError:
        pass  # column already exists
```

### Step 2 — Generalize `record_alert_delivery` (state_registry.py:1844)

Add two optional kwargs at the END (so all 8+ existing positional callers in `_fire_escalation_alerts` keep working with zero changes):

```python
def record_alert_delivery(escalation_id, channel: str, destination: str,
                           status: str, error: str = None,
                           alert_type: str = "escalation",
                           appointment_id: int = None) -> int:
    """Brief 217 + 241: append a row to alert_deliveries. status one of
    'sent', 'failed', 'skipped'. alert_type is 'escalation' (default,
    backward compat) or 'appointment'. For appointment rows, pass
    escalation_id=None and appointment_id=<row_id>; for escalation rows,
    pass appointment_id=None (default). Returns row id."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO alert_deliveries "
        "(escalation_id, channel, destination, status, error, sent_at, "
        "alert_type, appointment_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (escalation_id, channel, destination or "", status, error, now,
         alert_type, appointment_id))
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id
```

### Step 3 — `appointment_alert_already_sent` helper (new function in state_registry.py)

Place near `record_alert_delivery`. Query `alert_deliveries` for the dedup tuple:

```python
def appointment_alert_already_sent(appointment_id: int, channel: str,
                                    destination: str) -> bool:
    """Brief 241: layer-2 dedup for appointment alerts. Returns True when
    a previous appointment-alert delivery has already been recorded for
    this exact (appointment_id, channel, destination) tuple with a
    terminal status ('sent' or 'failed'). 'skipped' rows do NOT count as
    "already sent" — they reflect "we couldn't send" (e.g., Zernio route
    not bootstrapped yet) and SHOULD retry on the next confirmation
    event if the configuration changes. Layer 1 dedup is the
    transition-aware trigger inside appointment_upsert."""
    if not appointment_id:
        return False
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM alert_deliveries "
        "WHERE alert_type = 'appointment' AND appointment_id = ? "
        "AND channel = ? AND destination = ? "
        "AND status IN ('sent', 'failed') LIMIT 1",
        (appointment_id, channel, destination or "")).fetchone()
    conn.close()
    return row is not None
```

### Step 4 — Dispatcher pointer + setter (state_registry.py top, near `_alert_dispatcher`)

Add a parallel pointer for the appointment dispatcher. Pattern mirrors Brief 217's `_alert_dispatcher` + `set_alert_dispatcher`:

```python
# Brief 241: optional callback set by dashboard.api at module-import
# time. dashboard.api registers _fire_appointment_alerts here so that
# appointment_upsert can fire alerts WITHOUT state_registry having to
# import dashboard.api (would create a circular import). When None,
# appointment alert dispatch is silently skipped (e.g., state_registry
# helper unit tests that don't load the dashboard router).
_appointment_alert_dispatcher = None


def set_appointment_alert_dispatcher(fn):
    """Brief 241: dashboard.api registers _fire_appointment_alerts here at
    import time. Decoupled callback so state_registry doesn't import
    dashboard."""
    global _appointment_alert_dispatcher
    _appointment_alert_dispatcher = fn
```

### Step 5 — Modify `appointment_upsert` to detect transition + fire dispatcher

Rewrite `appointment_upsert` (state_registry.py:2040-2075). Key changes:
- Read OLD status BEFORE the UPDATE (only relevant on the existing-row path).
- Detect transition: insert with status='confirmed' OR (update where old != 'confirmed' AND new == 'confirmed').
- AFTER the row write commits, if transition detected AND `_appointment_alert_dispatcher is not None` AND tenant has `alert_type_appointment_enabled=1`, fire the dispatcher with the appointment row id + customer_name + channel + an appointment dict containing the freshly-saved fields.

```python
def appointment_upsert(conversation_id: str, channel: str, customer_name: str,
                       title: str, proposed_times: list, location: str = "",
                       status: str = "detected") -> int:
    """Brief 228: upsert an appointment row keyed on conversation_id.
    proposed_times is a list of strings; we store JSON and pick the first
    one for date_time_label (frontend uses that as the headline).

    Brief 241: when this call transitions the appointment INTO 'confirmed'
    (insert with status='confirmed', OR update from a non-confirmed status
    to 'confirmed'), fire the registered _appointment_alert_dispatcher
    best-effort. Re-saves of the same 'confirmed' status do NOT fire
    (transition detection)."""
    if not conversation_id:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    pt = proposed_times or []
    label = pt[0] if pt else ""
    conn = _get_conn()
    existing = conn.execute(
        "SELECT id, status FROM appointments WHERE conversation_id = ?",
        (conversation_id,)).fetchone()
    transitioned_to_confirmed = False
    if existing:
        old_status = existing[1] or ""
        conn.execute(
            "UPDATE appointments SET channel = ?, customer_name = ?, "
            "title = ?, date_time_label = ?, proposed_times_json = ?, "
            "location = ?, status = ?, updated_at = ? "
            "WHERE id = ?",
            (channel, customer_name, title, label, json.dumps(pt),
             location, status, now, existing[0]))
        row_id = existing[0]
        if old_status != "confirmed" and status == "confirmed":
            transitioned_to_confirmed = True
    else:
        cur = conn.execute(
            "INSERT INTO appointments "
            "(conversation_id, channel, customer_name, title, date_time_label, "
            "proposed_times_json, location, status, source, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'conversation', ?, ?)",
            (conversation_id, channel, customer_name, title, label,
             json.dumps(pt), location, status, now, now))
        row_id = cur.lastrowid
        if status == "confirmed":
            transitioned_to_confirmed = True
    conn.commit()
    conn.close()

    # Brief 241: best-effort appointment alert dispatch on transition.
    # Wrapped in try/except so a dispatcher failure NEVER blocks the
    # appointment row from being saved. Tenant gate: alert_type_
    # appointment_enabled lives on alert_settings; default 1 (on).
    if transitioned_to_confirmed and _appointment_alert_dispatcher is not None:
        try:
            settings = get_alert_settings(default_email_destination="")
            alert_types = (settings or {}).get("alertTypes") or {}
            if alert_types.get("appointments", True):  # default True
                appointment_dict = {
                    "id": row_id,
                    "conversation_id": conversation_id,
                    "channel": channel,
                    "customer_name": customer_name,
                    "title": title,
                    "date_time_label": label,
                    "proposed_times": pt,
                    "location": location,
                    "status": "confirmed",
                }
                _appointment_alert_dispatcher(
                    row_id, customer_name, channel, appointment_dict)
        except Exception:
            pass

    return row_id
```

### Step 6 — `_fire_appointment_alerts` + body/subject helpers in `wtyj/dashboard/api.py`

Place above `_fire_escalation_alerts` so the helpers are reachable. Mirror the email + WhatsApp + telegram/messenger structure exactly, but with:
- New subject builder for appointments
- New body builder for appointments
- All `record_alert_delivery` calls pass `alert_type='appointment'` + `appointment_id=<id>`, escalation_id=None
- Per-channel dedup check via `appointment_alert_already_sent` BEFORE each send
- WhatsApp branch reuses Brief 240's `get_resolved_operator_whatsapp_route` + `send_dm_reply` path (do NOT duplicate)

```python
def _build_appointment_subject(customer_name: str,
                                appointment_dict: dict) -> str:
    """Brief 241: 'Appointment confirmed: {name} — {time}'. Falls back to
    just the customer name when no time is set on the appointment."""
    name = customer_name or "customer"
    time_label = (appointment_dict.get("date_time_label") or "").strip()
    proposed = appointment_dict.get("proposed_times") or []
    if not time_label and proposed:
        time_label = proposed[0]
    if time_label:
        return f"Appointment confirmed: {name} — {time_label}"
    return f"Appointment confirmed: {name}"


def _build_appointment_body(appointment_dict: dict, customer_name: str,
                             channel: str, client_name: str) -> str:
    """Brief 241: rich operator-facing body for confirmed appointments."""
    topic = (appointment_dict.get("title") or "Appointment").strip()
    time_label = (appointment_dict.get("date_time_label") or "").strip()
    proposed = appointment_dict.get("proposed_times") or []
    if not time_label and proposed:
        time_label = proposed[0]
    location = (appointment_dict.get("location") or "").strip() or "Location not set"
    return (
        f"Appointment confirmed\n\n"
        f"Customer: {customer_name or '(unknown)'}\n"
        f"Channel: {_channel_label(channel)}\n"
        f"Topic: {topic}\n"
        f"Time: {time_label or '(time not set)'}\n"
        f"Location: {location}\n\n"
        f"Open the dashboard to review or update this appointment."
    )


def _fire_appointment_alerts(appointment_id: int, customer_name: str,
                              channel: str, appointment_dict: dict) -> None:
    """Brief 241: build the appointment alert message, dispatch to enabled
    channels, record delivery status per attempt with alert_type='appointment'.
    Never raises. Per-channel dedup via appointment_alert_already_sent
    (layer-2 defense; layer-1 is the transition-aware trigger in
    appointment_upsert). WhatsApp uses the Brief 240 Zernio route — same
    helper, no Meta fallback."""
    try:
        biz = config_loader.get_business() or {}
        client_name = biz.get("name", "Unboks")
        default_email = biz.get("support_email", "") or biz.get("email", "")
    except Exception:
        client_name = "Unboks"
        default_email = ""

    settings = state_registry.get_alert_settings(
        default_email_destination=default_email)
    channels_cfg = settings.get("channels", {})

    email_subject = _build_appointment_subject(customer_name, appointment_dict)
    alert_text = _build_appointment_body(appointment_dict, customer_name,
                                          channel, client_name)

    em = channels_cfg.get("email", {})
    if em.get("enabled"):
        primary = em.get("destination", "")
        if primary in ("", "default"):
            primary = default_email
        alternative = (em.get("alternativeDestination") or "").strip()
        recipients = []
        if primary:
            recipients.append(primary)
        if alternative and alternative != primary:
            recipients.append(alternative)
        if not recipients:
            state_registry.record_alert_delivery(
                None, "email", "", "skipped",
                "no email destination configured",
                alert_type="appointment", appointment_id=appointment_id)
        else:
            for dest in recipients:
                if state_registry.appointment_alert_already_sent(
                        appointment_id, "email", dest):
                    continue  # layer-2 dedup
                try:
                    smtp_send(dest, email_subject, alert_text)
                    state_registry.record_alert_delivery(
                        None, "email", dest, "sent",
                        alert_type="appointment", appointment_id=appointment_id)
                except Exception as exc:
                    state_registry.record_alert_delivery(
                        None, "email", dest, "failed", str(exc)[:200],
                        alert_type="appointment", appointment_id=appointment_id)

    wa = channels_cfg.get("whatsapp", {})
    if wa.get("enabled"):
        dest = wa.get("destination", "")
        if not dest:
            state_registry.record_alert_delivery(
                None, "whatsapp", "", "skipped",
                "no whatsapp destination configured",
                alert_type="appointment", appointment_id=appointment_id)
        else:
            if state_registry.appointment_alert_already_sent(
                    appointment_id, "whatsapp", dest):
                pass  # layer-2 dedup, no row written
            else:
                route = state_registry.get_resolved_operator_whatsapp_route()
                if not route:
                    state_registry.record_alert_delivery(
                        None, "whatsapp", dest, "skipped",
                        "zernio_operator_destination_not_resolved",
                        alert_type="appointment", appointment_id=appointment_id)
                else:
                    from agents.social.zernio_dm_client import send_dm_reply
                    try:
                        ok = send_dm_reply(
                            route["conversation_id"],
                            route["account_id"],
                            alert_text)
                        if ok:
                            state_registry.record_alert_delivery(
                                None, "whatsapp", dest, "sent",
                                alert_type="appointment",
                                appointment_id=appointment_id)
                        else:
                            state_registry.record_alert_delivery(
                                None, "whatsapp", dest, "failed",
                                "zernio_send_dm_reply_returned_false",
                                alert_type="appointment",
                                appointment_id=appointment_id)
                    except Exception as exc:
                        state_registry.record_alert_delivery(
                            None, "whatsapp", dest, "failed",
                            f"zernio_send_dm_reply_exception: {str(exc)[:200]}",
                            alert_type="appointment",
                            appointment_id=appointment_id)

    if channels_cfg.get("telegram", {}).get("enabled"):
        state_registry.record_alert_delivery(
            None, "telegram",
            channels_cfg["telegram"].get("destination", ""),
            "skipped", "telegram provider not configured",
            alert_type="appointment", appointment_id=appointment_id)
    if channels_cfg.get("messenger", {}).get("enabled"):
        state_registry.record_alert_delivery(
            None, "messenger",
            channels_cfg["messenger"].get("destination", ""),
            "skipped", "messenger provider not configured",
            alert_type="appointment", appointment_id=appointment_id)


# Brief 241: register the appointment dispatcher with state_registry.
state_registry.set_appointment_alert_dispatcher(_fire_appointment_alerts)
```

### Step 7 — Per-alert-type gate on the existing escalation dispatcher

In `_fire_escalation_alerts` (dashboard/api.py:1664), after the `settings = state_registry.get_alert_settings(...)` line, add a top-level gate:

```python
    settings = state_registry.get_alert_settings(default_email_destination=default_email)
    # Brief 241: per-alert-type gate. When alertTypes.escalations is False
    # (operator disabled escalation alerts in Settings), short-circuit the
    # entire dispatcher — no rows written, no provider calls. Default True
    # for backward compat (pre-Brief-241 settings rows have the column at
    # default 1 from the Step 1 ALTER).
    alert_types = (settings or {}).get("alertTypes") or {}
    if not alert_types.get("escalations", True):
        return
    channels_cfg = settings.get("channels", {})
    ...
```

### Step 8 — Extend `get_alert_settings` and `save_alert_settings` to surface/persist `alertTypes`

In `get_alert_settings` (state_registry.py:1690), extend the SELECT to include the 2 new alert_type columns and add the `alertTypes` block to both the synthesized-default branch AND the real-row branch:

```python
    # SELECT extended to read the 2 new columns
    row = conn.execute(
        "SELECT email_enabled, email_destination, whatsapp_enabled, "
        "whatsapp_destination, telegram_enabled, telegram_destination, "
        "messenger_enabled, messenger_destination, "
        "email_alternative_destination, "
        "alert_type_escalation_enabled, alert_type_appointment_enabled "
        "FROM alert_settings WHERE id = 1").fetchone()
    ...
    # Synthesized-default branch (no row yet) — defaults both to True
    return {
        "alertTypes": {"escalations": True, "appointments": True},
        "channels": { ... existing ... }
    }
    ...
    # Real-row branch — read columns 9 + 10 (zero-indexed) for the toggles
    return {
        "alertTypes": {
            "escalations": bool(row[9]),
            "appointments": bool(row[10]),
        },
        "channels": { ... existing ... }
    }
```

In `save_alert_settings` (state_registry.py:1735), extend the signature to optionally accept `alert_types` dict, and include the 2 new columns in the ON CONFLICT DO UPDATE list. Persist booleans as 0/1 integers:

```python
def save_alert_settings(channels: dict, alert_types: dict = None) -> None:
    """Brief 217 + 226 + 241: upsert alert_settings using ON CONFLICT DO
    UPDATE so Brief 240's bootstrap-only whatsapp_zernio_* columns AND
    Brief 241's alert_type_* toggles all coexist with user-controlled
    Settings saves. alert_types is optional ({"escalations": bool,
    "appointments": bool}); defaults to leaving the existing values alone
    (COALESCE pattern)."""
    now = datetime.now(timezone.utc).isoformat()
    em = channels.get("email", {}) or {}
    wa = channels.get("whatsapp", {}) or {}
    tg = channels.get("telegram", {}) or {}
    ms = channels.get("messenger", {}) or {}
    at = alert_types or {}
    # Read current values to feed COALESCE-style behavior on the toggles
    ate = 1 if at.get("escalations", True) else 0
    ata = 1 if at.get("appointments", True) else 0
    conn = _get_conn()
    conn.execute(
        "INSERT INTO alert_settings "
        "(id, email_enabled, email_destination, whatsapp_enabled, whatsapp_destination, "
        "telegram_enabled, telegram_destination, messenger_enabled, messenger_destination, "
        "email_alternative_destination, "
        "alert_type_escalation_enabled, alert_type_appointment_enabled, "
        "updated_at) "
        "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET "
        "email_enabled = excluded.email_enabled, "
        "email_destination = excluded.email_destination, "
        "whatsapp_enabled = excluded.whatsapp_enabled, "
        "whatsapp_destination = excluded.whatsapp_destination, "
        "telegram_enabled = excluded.telegram_enabled, "
        "telegram_destination = excluded.telegram_destination, "
        "messenger_enabled = excluded.messenger_enabled, "
        "messenger_destination = excluded.messenger_destination, "
        "email_alternative_destination = excluded.email_alternative_destination, "
        "alert_type_escalation_enabled = excluded.alert_type_escalation_enabled, "
        "alert_type_appointment_enabled = excluded.alert_type_appointment_enabled, "
        "updated_at = excluded.updated_at",
        (1 if em.get("enabled") else 0, em.get("destination", ""),
         1 if wa.get("enabled") else 0, wa.get("destination", ""),
         1 if tg.get("enabled") else 0, tg.get("destination", ""),
         1 if ms.get("enabled") else 0, ms.get("destination", ""),
         em.get("alternativeDestination", "") or "",
         ate, ata, now))
    conn.commit()
    conn.close()
```

### Step 9 — Endpoint surface in `wtyj/dashboard/api.py`

In `dashboard/api.py:760-790` near `AlertSettingsRequest` + the GET/PUT endpoints, extend the Pydantic model with an optional `alertTypes` field and pass it through to `save_alert_settings`:

```python
class AlertTypesConfig(BaseModel):
    escalations: bool = True
    appointments: bool = True


class AlertSettingsRequest(BaseModel):
    channels: dict[str, AlertChannelConfig]
    alertTypes: AlertTypesConfig = AlertTypesConfig()  # Brief 241


@router.put("/settings/escalation-alerts", dependencies=[Depends(_check_auth)])
async def put_alert_settings_endpoint(req: AlertSettingsRequest):
    channels_dict = {k: v.model_dump() for k, v in req.channels.items()}
    state_registry.save_alert_settings(
        channels_dict,
        alert_types=req.alertTypes.model_dump())  # Brief 241
    return state_registry.get_alert_settings(
        default_email_destination=_resolved_default_email())
```

The GET endpoint needs no changes — `get_alert_settings` was extended in Step 8 to surface `alertTypes`.

### Step 10 — Tests in `wtyj/tests/social/test_217_alert_delivery.py` (EXTEND)

Add 6 new tests. Reuse the existing `_wipe_escalations_for(customer_id)` helper from Brief 240 + add a parallel `_wipe_appointments_for(conversation_id)`.

```python
def _wipe_appointments_for(conversation_id: str):
    """Brief 241: wipe appointment row + its alert_deliveries audit rows
    before a test runs. Tests share the dev DB."""
    from shared import state_registry
    conn = state_registry._get_conn()
    rows = conn.execute(
        "SELECT id FROM appointments WHERE conversation_id = ?",
        (conversation_id,)).fetchall()
    for r in rows:
        conn.execute("DELETE FROM alert_deliveries WHERE appointment_id = ?",
                     (r[0],))
        conn.execute("DELETE FROM appointments WHERE id = ?", (r[0],))
    conn.commit()
    conn.close()


def test_appointment_upsert_does_not_fire_dispatcher_for_pending(monkeypatch):
    """Brief 241: status='pending_team_confirmation' on insert does NOT
    fire the appointment alert dispatcher (acceptance #2/#3)."""
    from shared import state_registry
    conv = "test-241-pending"
    _wipe_appointments_for(conv)
    fired = []
    monkeypatch.setattr(state_registry, "_appointment_alert_dispatcher",
                         lambda *a, **k: fired.append(a))
    state_registry.appointment_upsert(
        conv, "whatsapp", "Calvin", "Intake call",
        ["Friday 12:00"], status="pending_team_confirmation")
    assert fired == []


def test_appointment_upsert_fires_dispatcher_on_insert_confirmed(monkeypatch):
    """Brief 241: status='confirmed' on FRESH insert fires the dispatcher
    (acceptance #6)."""
    from shared import state_registry
    conv = "test-241-insert-confirmed"
    _wipe_appointments_for(conv)
    fired = []
    monkeypatch.setattr(state_registry, "_appointment_alert_dispatcher",
                         lambda *a, **k: fired.append(a))
    rid = state_registry.appointment_upsert(
        conv, "whatsapp", "Calvin", "Intake call",
        ["Friday 12:00"], location="Café Paris", status="confirmed")
    assert len(fired) == 1
    assert fired[0][0] == rid
    assert fired[0][1] == "Calvin"
    assert fired[0][2] == "whatsapp"
    appt = fired[0][3]
    assert appt["status"] == "confirmed"
    assert appt["title"] == "Intake call"


def test_appointment_upsert_fires_dispatcher_on_transition_to_confirmed(monkeypatch):
    """Brief 241: pending_team_confirmation → confirmed fires dispatcher
    (acceptance #6 via update path)."""
    from shared import state_registry
    conv = "test-241-transition"
    _wipe_appointments_for(conv)
    state_registry.appointment_upsert(
        conv, "whatsapp", "Calvin", "Intake call",
        ["Friday 12:00"], status="pending_team_confirmation")
    fired = []
    monkeypatch.setattr(state_registry, "_appointment_alert_dispatcher",
                         lambda *a, **k: fired.append(a))
    state_registry.appointment_upsert(
        conv, "whatsapp", "Calvin", "Intake call",
        ["Friday 12:00"], location="Café Paris", status="confirmed")
    assert len(fired) == 1


def test_appointment_upsert_does_not_refire_on_resave_confirmed(monkeypatch):
    """Brief 241: confirmed → confirmed re-save does NOT fire dispatcher
    again (acceptance #11 layer-1 dedup via transition detection)."""
    from shared import state_registry
    conv = "test-241-resave"
    _wipe_appointments_for(conv)
    state_registry.appointment_upsert(
        conv, "whatsapp", "Calvin", "Intake call",
        ["Friday 12:00"], status="confirmed")
    fired = []
    monkeypatch.setattr(state_registry, "_appointment_alert_dispatcher",
                         lambda *a, **k: fired.append(a))
    state_registry.appointment_upsert(
        conv, "whatsapp", "Calvin", "Intake call",
        ["Friday 12:00"], status="confirmed")
    assert fired == []  # transition detection blocks re-fire


def test_fire_appointment_alerts_sends_email_with_correct_shape(monkeypatch):
    """Brief 241: dispatcher writes correct subject + body via email,
    records alert_type='appointment', appointment_id=<id> in
    alert_deliveries (acceptance #6, #7, #12)."""
    from dashboard import api as dapi
    from shared import state_registry
    captured_email = {}
    def fake_smtp(to, subj, body):
        captured_email.update(to=to, subj=subj, body=body)
    monkeypatch.setattr(dapi, "smtp_send", fake_smtp)
    monkeypatch.setattr(state_registry, "get_alert_settings",
                         lambda **k: {
                             "alertTypes": {"escalations": True, "appointments": True},
                             "channels": {"email": {"enabled": True,
                                                     "destination": "ops@example.com",
                                                     "alternativeDestination": ""}}})
    monkeypatch.setattr(state_registry, "appointment_alert_already_sent",
                         lambda *a, **k: False)
    captured_delivery = []
    monkeypatch.setattr(state_registry, "record_alert_delivery",
                         lambda *a, **k: captured_delivery.append((a, k)))
    appt = {"id": 99, "conversation_id": "conv-x", "channel": "whatsapp",
            "customer_name": "Calvin", "title": "Intake call",
            "date_time_label": "Friday 12:00",
            "proposed_times": ["Friday 12:00"],
            "location": "Café Paris", "status": "confirmed"}
    dapi._fire_appointment_alerts(99, "Calvin", "whatsapp", appt)
    assert captured_email["subj"] == "Appointment confirmed: Calvin — Friday 12:00"
    assert "Appointment confirmed" in captured_email["body"]
    assert "Topic: Intake call" in captured_email["body"]
    assert "Time: Friday 12:00" in captured_email["body"]
    assert "Location: Café Paris" in captured_email["body"]
    # alert_deliveries row records appointment_id=99 + alert_type='appointment'
    em_rows = [(a, k) for (a, k) in captured_delivery if a[1] == "email"]
    assert len(em_rows) == 1
    args, kwargs = em_rows[0]
    assert kwargs.get("alert_type") == "appointment"
    assert kwargs.get("appointment_id") == 99
    assert args[0] is None  # escalation_id should be None for appointment rows


def test_fire_appointment_alerts_dedup_skips_already_sent(monkeypatch):
    """Brief 241: layer-2 dedup — if appointment_alert_already_sent
    returns True for a destination, the dispatcher does NOT call
    smtp_send for it AND records no new alert_deliveries row
    (acceptance #11)."""
    from dashboard import api as dapi
    from shared import state_registry
    smtp_calls = []
    monkeypatch.setattr(dapi, "smtp_send",
                         lambda to, s, b: smtp_calls.append(to))
    monkeypatch.setattr(state_registry, "get_alert_settings",
                         lambda **k: {
                             "alertTypes": {"escalations": True, "appointments": True},
                             "channels": {"email": {"enabled": True,
                                                     "destination": "ops@example.com",
                                                     "alternativeDestination": ""}}})
    monkeypatch.setattr(state_registry, "appointment_alert_already_sent",
                         lambda aid, ch, dest: True)  # already sent
    record_calls = []
    monkeypatch.setattr(state_registry, "record_alert_delivery",
                         lambda *a, **k: record_calls.append((a, k)))
    appt = {"id": 100, "conversation_id": "conv-y", "channel": "whatsapp",
            "customer_name": "Calvin", "title": "Intake call",
            "date_time_label": "Friday 12:00", "proposed_times": ["Friday 12:00"],
            "location": "", "status": "confirmed"}
    dapi._fire_appointment_alerts(100, "Calvin", "whatsapp", appt)
    assert smtp_calls == []  # no email sent
    em_rows = [(a, k) for (a, k) in record_calls if a[1] == "email"]
    assert em_rows == []  # no new alert_deliveries row written
```

Six new tests. All exercise real branches:
1. pending status → no dispatcher fire
2. fresh insert with confirmed → fires
3. transition pending → confirmed → fires
4. confirmed → confirmed re-save → does NOT fire
5. dispatcher writes correct email shape + alert_type/appointment_id audit columns
6. layer-2 dedup blocks send when already-sent returns True

**Regression baseline:** 1032 passing / 0 failures (per Brief 240 system_state). After this brief: **1038 passing / 0 failures** (1032 + 6 new).

## Success Condition

After execution:

1. `python3 -m pytest wtyj/tests/social/test_217_alert_delivery.py -q` passes (existing 19 + 6 new = 25).
2. `python3 -m pytest wtyj/tests/ -q` reports 1038 passing / 0 failures.
3. After deploy, `curl -sf https://api.unboks.org/api/unboks/dashboard/api/settings/escalation-alerts -H "Authorization: Bearer <token>"` returns a JSON with `alertTypes: {escalations: true, appointments: true}` AND the existing `channels` block intact (Brief 240's `whatsappZernioResolved` field still present).
4. `docker exec wtyj-unboks sqlite3 /app/data/state_registry.db "SELECT alert_type, appointment_id FROM alert_deliveries WHERE alert_type='appointment' LIMIT 1;"` returns 0 rows immediately post-deploy (no appointments are in `confirmed` state; dispatcher hasn't fired). After a test sentinel insert via `docker exec ... python3 -c "from shared import state_registry as s; s.appointment_upsert('test-conv-241-prod','whatsapp','Test','Topic',['x'],'',status='confirmed')"`, the count becomes ≥ 1 (one row per enabled-and-resolved destination).
5. `tenant_guard.is_account_allowed` still importable in unboks/bluemarlin (Brief 238 not regressed). Brief 240's `get_resolved_operator_whatsapp_route` still returns the resolved route for unboks (no Brief 240 regression).
6. CI green; all 4 containers healthy.
7. Existing escalation alert behavior unchanged — Brief 239's rich body + Brief 240's Zernio path still work for escalation alerts (verified by the existing 19 tests in `test_217_alert_delivery.py` continuing to pass).

## Rollback

Code-only rollback: `git revert <this brief's source commit>` and push. Pipeline auto-deploys (~90s). The 4 new schema columns (2 on alert_deliveries, 2 on alert_settings) survive a revert — SQLite ALTER ADD is forward-compatible — and sit unused. Existing `alert_deliveries` rows from before this brief retain their auto-defaulted `alert_type='escalation'` value, which is semantically correct.

If only the appointment dispatcher is misbehaving in production, set `state_registry._appointment_alert_dispatcher = None` (e.g., a one-line monkey-patch + `docker compose restart wtyj-unboks`) and the appointment trigger inside `appointment_upsert` becomes a no-op — escalation alerts continue to fire normally.

To globally disable appointment alerts via Settings: `PUT /settings/escalation-alerts` with `{alertTypes: {escalations: true, appointments: false}, channels: {...}}`. The dispatcher checks `alert_types.get("appointments", True)` before firing.

To clear stuck appointment_id-keyed dedup rows on the VPS (e.g., test sentinel inserts pollute the table): `docker exec wtyj-unboks sqlite3 /app/data/state_registry.db "DELETE FROM alert_deliveries WHERE alert_type='appointment' AND appointment_id IN (<ids>);"`.
