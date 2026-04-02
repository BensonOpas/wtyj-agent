# BRIEF 129 — Large Group Booking: Book First, Escalate After
**Status:** Draft | **Depends on:** Brief 128 | **Blocks:** —

**Files:**
- `bluemarlin/agents/marina/marina_agent.py`
- `bluemarlin/agents/social/social_agent.py`
- `bluemarlin/config/client.json`
- `bluemarlin/tests/social/test_129_large_group.py`

## Context
Groups of 15+ guests trigger `requires_human: true` immediately (marina_agent.py line 333), so the customer never gets a booking summary — they go straight to escalation. The operator has to manually handle the entire booking. Fix: let them book normally, then notify the operator for review.

## Why This Approach
The booking flow already handles large groups fine (capacity check, soft holds, payment links). The only issue is the prompt triggering immediate escalation. Remove that trigger, add a post-confirmation notification. Marina still knows about large groups via a new `large_group` flag for context.

## Source Material

### Change 1 — marina_agent.py line 333: Remove 15+ from requires_human
Current:
```
  "requires_human": <true if group of 15 or more guests, complaint with no booking context, or explicit request to speak to a human — otherwise false>,
```
Replace with:
```
  "requires_human": <true if complaint with no booking context, or explicit request to speak to a human — otherwise false>,
```

### Change 2 — marina_agent.py line 334: Add large_group flag
In the flags JSON schema, add `"large_group"` after `"needs_escalation_email"`:
Current flags end: `"needs_escalation_email": <true when a WhatsApp escalation needs the customer's email before proceeding — omit or false otherwise>}},`
Add before the closing `}}`: `, "large_group": <true when the guest count meets or exceeds the large group threshold — omit or false otherwise>`

### Change 2b — client.json line 265: Update FAQ entry
Current: `"group_bookings": "For groups of 15 or more, contact the team directly for tailored arrangements."`
Replace with: `"group_bookings": "Large groups are welcome. Book normally and the team will review your booking to ensure everything runs smoothly."`

### Change 3 — social_agent.py: Add post-booking large group notification (after line 717)
Insert after `state_registry.save_booking(...)` block (line 717), before `# Step 9`:
```python
                # Large group notification — operator review after auto-confirm
                _lg_threshold = config_loader.get_booking_rules().get("group_threshold_requires_human", 15)
                _lg_guests = int(fields.get("guests", 0) or 0)
                if _lg_guests >= _lg_threshold:
                    _lg_ref = flags.get("booking_ref", "NO-REF")
                    _lg_name = fields.get("customer_name", "Unknown")
                    _lg_note = (f"Large group booking: {_lg_guests} guests for "
                                f"{fields.get('experience', '?')} on {fields.get('date', '?')}. "
                                f"Ref: {_lg_ref}. Auto-confirmed — operator review recommended.")
                    state_registry.create_pending_notification(
                        'escalation', 'whatsapp', phone, _lg_name,
                        f"[LARGE GROUP] {_lg_ref} - {_lg_name} (WhatsApp: {phone}) - {_lg_note}",
                        (f"=== LARGE GROUP BOOKING ===\n"
                         f"Ref: {_lg_ref}\nGuests: {_lg_guests}\n"
                         f"Trip: {fields.get('experience', '?')}\n"
                         f"Date: {fields.get('date', '?')}\n"
                         f"Customer: {_lg_name}\nPhone: {phone}\n"
                         f"Email: {fields.get('email', 'not provided')}\n\n"
                         f"This booking was auto-confirmed. Review and adjust if needed."))
                    state_registry.wa_store_message(phone, "system",
                        f"Large group booking ({_lg_guests} guests) — operator notified for review")
                    bm_logger.log("large_group_booking", phone=phone,
                                  guests=str(_lg_guests), booking_ref=_lg_ref)
```

## Tests

```python
# test_129_large_group.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DASHBOARD_PASSWORD", "testpass")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "test")
os.environ.setdefault("META_ACCESS_TOKEN", "test")
os.environ.setdefault("LATE_API_KEY", "test")

from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from agents.social.social_agent import handle_incoming_whatsapp_message
from shared import state_registry


def _next_wed():
    today = datetime.now(timezone.utc).date()
    d = today + timedelta(days=1)
    while d.weekday() != 2:
        d += timedelta(days=1)
    return d.isoformat()

def _cleanup(phone):
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM pending_notifications WHERE customer_id = ?", (phone,))
    conn.commit()
    conn.close()


# --- Test 1: Prompt no longer triggers requires_human for 15+ guests ---
def test_prompt_no_large_group_in_requires_human():
    from agents.marina.marina_agent import _build_prompt
    prompt = _build_prompt("test@test.com", "Test", "Hello",
                           {}, {}, channel="whatsapp", messages=[])
    # requires_human should NOT mention "15" or "group"
    # Find the requires_human line
    for line in prompt.split("\n"):
        if "requires_human" in line and "true if" in line:
            assert "15" not in line, f"requires_human still mentions 15: {line}"
            assert "group" not in line.lower(), f"requires_human still mentions group: {line}"
            break


# --- Test 2: Prompt has large_group flag ---
def test_prompt_has_large_group_flag():
    from agents.marina.marina_agent import _build_prompt
    prompt = _build_prompt("test@test.com", "Test", "Hello",
                           {}, {}, channel="whatsapp", messages=[])
    assert "large_group" in prompt


# --- Test 3: Confirmed booking with 15+ guests creates notification ---
@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_large_group_creates_notification(mock_process, mock_cal, mock_pay, mock_sheets):
    phone = "129_large_group"
    _cleanup(phone)
    date = _next_wed()

    # Pre-set state: awaiting confirmation with soft hold for 20 guests
    fields = {"trip_key": "west_coast_beach", "experience": "West Coast Beach",
              "date": date, "guests": "20", "departure_time": "09:00",
              "customer_name": "Big Group"}
    hold_id = state_registry.create_soft_hold("west_coast_beach", date, "09:00", 20, 25,
                                               customer_name="Big Group", customer_email=phone)
    flags = {"awaiting_booking_confirmation": True, "slot_checked": True,
             "slot_available": True, "hold_id": hold_id,
             "hold_trip_key": "west_coast_beach", "hold_date": date,
             "hold_departure_time": "09:00"}
    state_registry.wa_save_booking_state(phone, fields, flags)

    mock_process.return_value = {
        "intents": ["booking"],
        "fields": {},
        "confidence": "high",
        "reply": "You're all set! Ref [BOOKING_REF]. Pay here: [PAYMENT_LINK]",
        "reply_hold_failed": "Sorry, that slot is no longer available.",
        "clarifications_needed": [], "requires_human": False,
        "flags": {"booking_confirmed": True, "awaiting_booking_confirmation": False},
        "internal_note": ""
    }
    mock_cal.create_or_update_manifest.return_value = {"ok": True, "eventId": "e1", "htmlLink": "http://cal/e1"}
    mock_pay.generate_payment_link.return_value = {"payment_id": "pay1", "status": "pending"}

    msg = {"from": phone, "text": "Yes book it!", "from_name": "Big Group"}
    reply = handle_incoming_whatsapp_message(msg)

    # Booking should complete normally
    assert "BF-" in reply
    assert "demo.pay" in reply

    # Large group notification should exist
    escs = state_registry.get_all_escalations()
    lg_esc = [e for e in escs if e["customer_id"] == phone and "LARGE GROUP" in e["subject"]]
    assert len(lg_esc) == 1, f"Expected 1 large group notification, got {len(lg_esc)}"
    assert "20 guests" in lg_esc[0]["subject"]
    assert "auto-confirmed" in lg_esc[0]["body"].lower()

    _cleanup(phone)


# --- Test 4: Normal booking (under 15) does NOT create notification ---
@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_normal_booking_no_notification(mock_process, mock_cal, mock_pay, mock_sheets):
    phone = "129_normal_group"
    _cleanup(phone)
    date = _next_wed()

    fields = {"trip_key": "west_coast_beach", "experience": "West Coast Beach",
              "date": date, "guests": "4", "departure_time": "09:00",
              "customer_name": "Small Group"}
    hold_id = state_registry.create_soft_hold("west_coast_beach", date, "09:00", 4, 25,
                                               customer_name="Small Group", customer_email=phone)
    flags = {"awaiting_booking_confirmation": True, "slot_checked": True,
             "slot_available": True, "hold_id": hold_id,
             "hold_trip_key": "west_coast_beach", "hold_date": date,
             "hold_departure_time": "09:00"}
    state_registry.wa_save_booking_state(phone, fields, flags)

    mock_process.return_value = {
        "intents": ["booking"],
        "fields": {},
        "confidence": "high",
        "reply": "You're all set! Ref [BOOKING_REF]. Pay here: [PAYMENT_LINK]",
        "reply_hold_failed": "Sorry, unavailable.",
        "clarifications_needed": [], "requires_human": False,
        "flags": {"booking_confirmed": True, "awaiting_booking_confirmation": False},
        "internal_note": ""
    }
    mock_cal.create_or_update_manifest.return_value = {"ok": True, "eventId": "e2", "htmlLink": "http://cal/e2"}
    mock_pay.generate_payment_link.return_value = {"payment_id": "pay2", "status": "pending"}

    msg = {"from": phone, "text": "Yes!", "from_name": "Small Group"}
    handle_incoming_whatsapp_message(msg)

    escs = state_registry.get_all_escalations()
    lg_esc = [e for e in escs if e["customer_id"] == phone and "LARGE GROUP" in e["subject"]]
    assert len(lg_esc) == 0, f"Normal booking should not create large group notification"

    _cleanup(phone)
```

## Success Condition
15+ guest bookings complete normally (summary, confirmation, payment link). After confirmation, a [LARGE GROUP] notification appears in the dashboard for operator review. Under-15 bookings unaffected.

## Rollback
Revert marina_agent.py and social_agent.py. Delete test file.
