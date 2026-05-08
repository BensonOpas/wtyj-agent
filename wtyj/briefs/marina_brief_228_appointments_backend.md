# BRIEF 228 — Appointments backend (thread-based, derived from escalation summaries)
**Status:** Draft | **Files:** `wtyj/shared/state_registry.py`, `wtyj/dashboard/api.py`, `wtyj/tests/social/test_228_appointments.py` | **Depends on:** Brief 227 (escalation summary with `extractedDetails.proposedTimes` + `intent: "scheduling"`) | **Blocks:** SR's frontend `useAppointments` hook fetching `GET /appointments` instead of falling back to client-side parsing

## Context

SR's task `4bf443de31a9` ("Appointment detection is message-based. It must become thread-based"):
> "When a scheduling conversation reaches a clear handoff or confirmation state, create or update an appointment record. Use the full conversation history to extract: customer name, requested meeting/topic, proposed times, selected time, location, channel, source conversation id, status. If no chosen time exists, create a detected appointment candidate only if there is enough scheduling intent. Frontend expectation: `GET /api/{client}/dashboard/api/appointments` must return this appointment."

Frontend today (`use-appointments.ts:6-30` + `lib/api.ts:237`):
- Calls `GET /appointments` with graceful 404/501/503 fallback to client-side detection.
- Has a 268-line `appointment-detector.ts` that scans `ConversationDetail` text for day+time tokens and intent keywords.

Backend today: no appointments table, no endpoint. Frontend always falls back. Result: appointment detection happens once per conversation visit (no persistence) and depends on whether the operator opened the inbox detail pane.

**Why appointments derive from escalation summaries.** Brief 227 shipped a Claude-generated `escalation_summary` with `extractedDetails.intent` + `extractedDetails.proposedTimes`. When `intent == "scheduling"` and `proposedTimes` is non-empty, we have everything an appointment row needs — extracted by Claude with full thread context — for free. Reuse > rebuild. The escalation IS the "passed to the team" handoff moment (`status: pending_team_confirmation`).

## Why This Approach

**Chosen:** new `appointments` table, populated as a side-effect of `_generate_escalation_summary` (Brief 227's dispatcher wrapper). When the generator returns a dict with `intent == "scheduling"` and at least one `proposedTimes`, upsert an appointment row keyed on `conversation_id` (one appointment per conversation — same dedup principle as the escalation row). New `GET /appointments` endpoint. No new Claude calls, no separate detector, no schema duplication.

**Rejected: client-side-only detection (status quo).** Status quo is fine while there's only one operator looking at one conversation. Once two operators use the dashboard, every page load re-runs the parser; nothing is shared; the Appointments page has no concept of "appointments I scheduled yesterday." A backend table is the obvious move.

**Rejected: server-side detector with its own Claude call.** Would duplicate the work the escalation-summary generator already does. Adds another API call per escalation, doubles latency, and the detector's prompt would either drift from or copy the summary's `extractedDetails.proposedTimes` extraction. Reuse Brief 227's dict.

**Rejected: server-side regex detector mirroring the frontend's `appointment-detector.ts`.** Brittle (timezone tokens, multilingual day names, "tomorrow" vs absolute dates), and we explicitly DON'T do Python language classification (CLAUDE.md Rule 5). Claude already extracts proposed times in the customer's wording — that's the right layer.

**Rejected: appointment row as a JSON column on `pending_notifications`.** Conflates two concerns. Escalations close out (status `replied` / `resolved`); appointments persist independently of escalation lifecycle. Different table.

**Rejected: multi-row "all proposed times become candidate appointments" model.** SR's spec says "If a chosen time/location exists earlier in the thread, create the appointment. If no chosen time exists, create a detected appointment candidate only if there is enough scheduling intent." That's one row per conversation, status reflecting whether time is selected. Not N rows per proposed slot.

**Status taxonomy.** SR's spec lists `detected | pending_team_confirmation | confirmed | cancelled | completed`. We ship `detected` and `pending_team_confirmation` in v1. Both produced from summary dict:
- `pending_team_confirmation` — `intent == "scheduling"` AND `proposedTimes` non-empty (this is "passed to the team to pick a slot")
- `detected` — `intent == "scheduling"` AND `proposedTimes` empty (vague intent, no time mentioned)

`confirmed` requires an operator action; deferred to a future brief. `cancelled` and `completed` likewise — they're lifecycle states triggered by future operator actions.

**Tradeoff:** appointments only land when an escalation lands. A scheduling conversation that Marina handles end-to-end without escalating doesn't produce an appointment row in v1. For unboks (filter/buffer mode where every scheduling intent escalates) this is fine. For booking-flow tenants like BlueMarlin, they already have a `bookings` table — different system, not in scope. If a future tenant needs appointment detection without escalation, a follow-up brief can add a Marina-side hook.

**Idempotency / dedup.** Upsert keyed on `conversation_id`: one appointment per conversation. A second scheduling escalation on the same conversation UPDATEs the row's `proposed_times` / `date_time_label` / `updated_at` — same model as Brief 227's escalation dedup.

## Instructions

### 1. Schema

In `wtyj/shared/state_registry.py`, after the Brief 227 ALTER block on `pending_notifications`, add a `CREATE TABLE` for `appointments`. Place it next to the other Brief 217-era tables (after `alert_deliveries` around line 421):

```python
    # Brief 228: appointments — derived from escalation summaries when
    # intent=='scheduling'. One row per conversation_id (upsert on duplicate).
    conn.execute(
        "CREATE TABLE IF NOT EXISTS appointments ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "conversation_id TEXT NOT NULL UNIQUE, "
        "channel TEXT NOT NULL, "
        "customer_name TEXT NOT NULL DEFAULT '', "
        "title TEXT NOT NULL DEFAULT '', "
        "date_time_label TEXT NOT NULL DEFAULT '', "
        "proposed_times_json TEXT NOT NULL DEFAULT '[]', "
        "location TEXT NOT NULL DEFAULT '', "
        "status TEXT NOT NULL DEFAULT 'detected', "
        "source TEXT NOT NULL DEFAULT 'conversation', "
        "created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL"
        ")"
    )
```

`proposed_times_json` is a JSON list — keeps the full set of customer-proposed times even when `date_time_label` shows the first one.

### 2. State-registry helpers

Add three helpers next to `get_active_escalation_summary_for` (Brief 227's helper, ~line 1792):

```python
def appointment_upsert(conversation_id: str, channel: str, customer_name: str,
                       title: str, proposed_times: list, location: str = "",
                       status: str = "detected") -> int:
    """Brief 228: upsert an appointment row keyed on conversation_id.
    proposed_times is a list of strings; we store JSON and pick the first
    one for date_time_label (frontend uses that as the headline)."""
    if not conversation_id:
        return 0
    now = datetime.now(timezone.utc).isoformat()
    pt = proposed_times or []
    label = pt[0] if pt else ""
    conn = _get_conn()
    existing = conn.execute(
        "SELECT id FROM appointments WHERE conversation_id = ?",
        (conversation_id,)).fetchone()
    if existing:
        conn.execute(
            "UPDATE appointments SET channel = ?, customer_name = ?, "
            "title = ?, date_time_label = ?, proposed_times_json = ?, "
            "location = ?, status = ?, updated_at = ? "
            "WHERE id = ?",
            (channel, customer_name, title, label, json.dumps(pt),
             location, status, now, existing[0]))
        row_id = existing[0]
    else:
        cur = conn.execute(
            "INSERT INTO appointments "
            "(conversation_id, channel, customer_name, title, date_time_label, "
            "proposed_times_json, location, status, source, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'conversation', ?, ?)",
            (conversation_id, channel, customer_name, title, label,
             json.dumps(pt), location, status, now, now))
        row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


def appointments_list() -> list:
    """Brief 228: return all appointments newest-updated first, in the
    shape SR's frontend expects (camelCase, ISO timestamps).
    proposed_times_json is parsed and surfaced as proposedTimes for
    detail views; date_time_label is the headline string."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, conversation_id, channel, customer_name, title, "
        "date_time_label, proposed_times_json, location, status, source, "
        "created_at, updated_at "
        "FROM appointments ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        try:
            proposed = json.loads(r[6]) if r[6] else []
        except (json.JSONDecodeError, TypeError):
            proposed = []
        out.append({
            "id": str(r[0]),
            "conversationId": r[1],
            "channel": r[2],
            "customerName": r[3] or "",
            "title": r[4] or "Appointment",
            "dateTimeLabel": r[5] or "",
            "proposedTimes": proposed,
            "location": r[7] or None,
            "status": r[8],
            "source": r[9] or "conversation",
            "createdAt": r[10],
            "updatedAt": r[11],
        })
    return out
```

### 3. Wire into the summary dispatcher

In `wtyj/dashboard/api.py`, the `_generate_escalation_summary` wrapper (Brief 227, around the new section near `set_summary_dispatcher`) returns a dict to the state-registry caller. AFTER it gets the dict back, but still inside the wrapper, write the appointment row when the dict says scheduling. Update the wrapper:

```python
def _generate_escalation_summary(escalation_id: int, channel: str,
                                  customer_id: str, customer_name: str) -> dict:
    """Brief 227: dispatcher wrapper. Brief 228: also writes an appointment
    row when the summary indicates scheduling intent."""
    try:
        mode = state_registry.get_active_escalation_mode(customer_id)
    except Exception:
        mode = None

    history = []
    try:
        if channel == "email":
            thread_key = state_registry._find_email_thread_key_for(customer_id)
            if thread_key:
                detail = state_registry.email_get_conversation(thread_key)
                history = detail.get("messages", []) or []
        elif channel in ("instagram", "facebook", "messenger"):
            history = state_registry.dm_get_history(customer_id, channel,
                                                     limit=20)
        else:
            history = state_registry.wa_get_full_history(customer_id, limit=20)
    except Exception:
        history = []

    summary_dict = _esc_summary.generate_summary(
        channel=channel,
        customer_id=customer_id,
        customer_name=customer_name,
        mode=mode,
        history=history,
    )

    # Brief 228: best-effort appointment row write. Only fires when the
    # summary indicates scheduling intent. Failure here never blocks
    # summary persistence (caller's outer try/except already handles it).
    if summary_dict:
        try:
            details = (summary_dict.get("extractedDetails") or {})
            if details.get("intent") == "scheduling":
                proposed = details.get("proposedTimes") or []
                topic = details.get("topic") or "Meeting"
                # Conversation id for the frontend mapper: email rows use
                # the email::<thread_key> shape so /messages/conversations/
                # routes correctly; whatsapp/dm use the bare id.
                if channel == "email":
                    thread_key = state_registry._find_email_thread_key_for(customer_id)
                    conv_id = f"email::{thread_key}" if thread_key else customer_id
                else:
                    conv_id = customer_id
                status = ("pending_team_confirmation"
                          if proposed else "detected")
                state_registry.appointment_upsert(
                    conversation_id=conv_id,
                    channel=channel,
                    customer_name=customer_name or "",
                    title=topic,
                    proposed_times=proposed,
                    status=status,
                )
        except Exception:
            pass

    return summary_dict
```

### 4. Endpoint

Add immediately after the existing `/escalations` GET handler (api.py:1358):

```python
@router.get("/appointments", dependencies=[Depends(_check_auth)])
async def list_appointments_endpoint():
    """Brief 228: return all appointments. Frontend's `useAppointments`
    expects this shape (camelCase). Empty array if no appointments yet."""
    items = state_registry.appointments_list()
    return {"items": items, "appointments": items}
```

We return BOTH `items` and `appointments` keys because SR's normalizer at `lib/api.ts:266-268` accepts either — defensive against shape drift.

## Tests

Place at `wtyj/tests/social/test_228_appointments.py`:

```python
"""Tests for Brief 228 — appointments backend."""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")

from unittest.mock import patch
from fastapi.testclient import TestClient
from agents.social.webhook_server import app
from shared import state_registry

client = TestClient(app)

SCHEDULING_SUMMARY = {
    "reason": "Calvin wants to schedule.",
    "customerWants": "An activation call.",
    "operatorNeedsToDecide": "Pick a time.",
    "recommendedOptions": ["Confirm Thursday at 09:00", "Suggest another time"],
    "extractedDetails": {
        "intent": "scheduling",
        "proposedTimes": ["Thursday at 09:00", "Thursday at 12:00"],
        "topic": "activation call",
    },
}

NON_SCHEDULING_SUMMARY = {
    "reason": "Customer complaint.",
    "customerWants": "A refund.",
    "operatorNeedsToDecide": "Approve refund or deny.",
    "recommendedOptions": ["Approve refund", "Deny refund"],
    "extractedDetails": {
        "intent": "refund",
        "proposedTimes": [],
        "topic": "refund request",
    },
}

VAGUE_SCHEDULING_SUMMARY = {
    "reason": "Customer wants to chat sometime.",
    "customerWants": "A meeting.",
    "operatorNeedsToDecide": "Propose a time.",
    "recommendedOptions": ["Propose a time", "Ask for availability"],
    "extractedDetails": {
        "intent": "scheduling",
        "proposedTimes": [],
        "topic": "general meeting",
    },
}


def _login():
    r = client.post("/dashboard/api/login", json={"password": "testpass"})
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _reset(prefix: str = "test228"):
    conn = state_registry._get_conn()
    conn.execute(
        "DELETE FROM pending_notifications WHERE customer_id LIKE ?",
        (f"{prefix}%",))
    conn.execute(
        "DELETE FROM conversation_status WHERE conversation_id LIKE ?",
        (f"{prefix}%",))
    conn.execute(
        "DELETE FROM appointments WHERE conversation_id LIKE ?",
        (f"%{prefix}%",))
    conn.commit()
    conn.close()


def test_scheduling_escalation_creates_appointment_row():
    """Brief 228: when summary intent=='scheduling' and proposedTimes is
    non-empty, an appointments row lands with status pending_team_confirmation."""
    _reset()
    customer_id = "test228-alice@example.com"
    with patch("dashboard.escalation_summary.generate_summary",
               return_value=SCHEDULING_SUMMARY):
        state_registry.create_pending_notification(
            notification_type="escalation", channel="email",
            customer_id=customer_id, customer_name="Alice",
            subject="Re: scheduling", body="alert")
    appts = state_registry.appointments_list()
    matches = [a for a in appts if customer_id in a["conversationId"]]
    assert len(matches) == 1
    a = matches[0]
    assert a["status"] == "pending_team_confirmation"
    assert a["dateTimeLabel"] == "Thursday at 09:00"
    assert a["proposedTimes"] == ["Thursday at 09:00", "Thursday at 12:00"]
    assert a["title"] == "activation call"
    assert a["channel"] == "email"
    assert a["customerName"] == "Alice"


def test_vague_scheduling_creates_detected_appointment():
    """Brief 228: scheduling intent without proposedTimes still creates a
    row, but with status='detected' (not pending_team_confirmation)."""
    _reset()
    customer_id = "test228-bob@example.com"
    with patch("dashboard.escalation_summary.generate_summary",
               return_value=VAGUE_SCHEDULING_SUMMARY):
        state_registry.create_pending_notification(
            notification_type="escalation", channel="whatsapp",
            customer_id=customer_id, customer_name="Bob",
            subject="WhatsApp", body="alert")
    appts = state_registry.appointments_list()
    matches = [a for a in appts if a["conversationId"] == customer_id]
    assert len(matches) == 1
    assert matches[0]["status"] == "detected"
    assert matches[0]["dateTimeLabel"] == ""


def test_non_scheduling_summary_creates_no_appointment():
    """Brief 228: refund / complaint / etc intents don't write an
    appointment row."""
    _reset()
    customer_id = "test228-carol@example.com"
    with patch("dashboard.escalation_summary.generate_summary",
               return_value=NON_SCHEDULING_SUMMARY):
        state_registry.create_pending_notification(
            notification_type="escalation", channel="whatsapp",
            customer_id=customer_id, customer_name="Carol",
            subject="WhatsApp", body="alert")
    appts = state_registry.appointments_list()
    assert not [a for a in appts if a["conversationId"] == customer_id]


def test_second_scheduling_escalation_updates_existing_appointment():
    """Brief 228: a second scheduling escalation on the same conversation
    UPDATEs the appointment row instead of inserting a duplicate."""
    _reset()
    customer_id = "test228-dan@example.com"
    first_summary = dict(SCHEDULING_SUMMARY)
    second_summary = {
        **SCHEDULING_SUMMARY,
        "extractedDetails": {
            "intent": "scheduling",
            "proposedTimes": ["Friday at 14:00"],
            "topic": "follow-up call",
        },
    }
    with patch("dashboard.escalation_summary.generate_summary",
               return_value=first_summary):
        state_registry.create_pending_notification(
            notification_type="escalation", channel="whatsapp",
            customer_id=customer_id, customer_name="Dan",
            subject="WhatsApp", body="alert")
    with patch("dashboard.escalation_summary.generate_summary",
               return_value=second_summary):
        state_registry.create_pending_notification(
            notification_type="escalation", channel="whatsapp",
            customer_id=customer_id, customer_name="Dan",
            subject="WhatsApp", body="alert")
    appts = state_registry.appointments_list()
    matches = [a for a in appts if a["conversationId"] == customer_id]
    assert len(matches) == 1
    assert matches[0]["dateTimeLabel"] == "Friday at 14:00"
    assert matches[0]["title"] == "follow-up call"


def test_get_appointments_endpoint_returns_items():
    """Brief 228: GET /appointments returns the list under both `items`
    and `appointments` keys."""
    _reset()
    customer_id = "test228-eve@example.com"
    with patch("dashboard.escalation_summary.generate_summary",
               return_value=SCHEDULING_SUMMARY):
        state_registry.create_pending_notification(
            notification_type="escalation", channel="whatsapp",
            customer_id=customer_id, customer_name="Eve",
            subject="WhatsApp", body="alert")
    token = _login()
    r = client.get("/dashboard/api/appointments", headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body
    assert "appointments" in body
    assert body["items"] == body["appointments"]
    matches = [a for a in body["items"] if a["conversationId"] == customer_id]
    assert len(matches) == 1
    assert matches[0]["dateTimeLabel"] == "Thursday at 09:00"


def test_email_appointment_uses_email_routing_key():
    """Brief 228: for email escalations the conversationId is prefixed
    `email::<thread_key>` so the frontend's /messages/conversations/:phone
    routing works (matches what the escalations list returns)."""
    _reset()
    customer_email = "test228-frank@example.com"
    # Seed an email thread so _find_email_thread_key_for returns a real key.
    import json as _json, tempfile
    tmpdir = tempfile.mkdtemp()
    fake_path = os.path.join(tmpdir, "email_thread_state.json")
    thread_key = f"subj:{customer_email}:test228 inquiry"
    with open(fake_path, "w") as f:
        _json.dump({"threads": {thread_key: {"messages": [], "fields": {}, "flags": {}}}}, f)
    orig = state_registry._get_email_state_path
    state_registry._get_email_state_path = lambda: fake_path
    try:
        with patch("dashboard.escalation_summary.generate_summary",
                   return_value=SCHEDULING_SUMMARY):
            state_registry.create_pending_notification(
                notification_type="escalation", channel="email",
                customer_id=customer_email, customer_name="Frank",
                subject="Re: scheduling", body="alert")
    finally:
        state_registry._get_email_state_path = orig

    appts = state_registry.appointments_list()
    matches = [a for a in appts if customer_email in a["conversationId"]]
    assert len(matches) == 1
    assert matches[0]["conversationId"] == f"email::{thread_key}"
```

## Success Condition

After deploy, an escalation triggered against a conversation containing two proposed times produces an `appointments` row with `status: "pending_team_confirmation"`, `dateTimeLabel: "Thursday at 09:00"` (first proposed time as headline), `proposedTimes` as full list, `title` from `extractedDetails.topic`. `GET /appointments` returns it in SR's expected shape (camelCase, both `items` and `appointments` keys for backward compat). A second scheduling escalation on the same conversation updates the row in place. New regression tests cover scheduling-with-times, vague-scheduling, non-scheduling-no-row, dedup-update, endpoint shape, email routing-key prefix. Full suite stays at 1053 + 6 new = 1059 passing / 0 failures.

## Rollback

`git revert <commit>`. The `appointments` table survives revert (CREATE TABLE IF NOT EXISTS, no DROP); reverted code paths simply ignore it. The endpoint disappears, frontend gracefully falls back to client-side detection on 404 (existing behavior). No data migration needed.
