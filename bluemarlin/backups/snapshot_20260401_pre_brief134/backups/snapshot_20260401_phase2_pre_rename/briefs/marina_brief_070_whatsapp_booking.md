# BRIEF 070 — WhatsApp Booking Orchestrator
**Status:** Draft | **Files:** `agents/social/social_agent.py`, `tests/social/test_070_whatsapp_booking.py` | **Depends on:** Brief 069 | **Blocks:** Brief 071 (escalation)

## Context
Brief 069 connected WhatsApp to marina_agent for Q&A only. Booking intents work (Claude extracts fields, returns booking replies) but the Python orchestration layer is missing: no post-validation (day-of-week check, past date check, departure time selection, booking summary), no availability check, no soft hold, no booking confirmation (manifest, booking_ref, payment link), no placeholder replacement with real values. The current code strips `[BOOKING_REF]` and `[PAYMENT_LINK]` to empty strings.

## Why This Approach
Option A (shared orchestrator extracted from email_poller.py) would require refactoring email_poller.py — too risky for a live system. Option B (duplicate booking helpers in social_agent.py) keeps email untouched and lets WhatsApp evolve independently. The helpers are pure functions (`_day_matches`, `_suggest_dates`, `_build_booking_summary`, `_post_validate`) so duplication cost is low. Phase 4 can extract to shared/ when both channels are stable.

This adds ~5 new Rule 3 instances (hardcoded reply strings in post-validation overrides and unavailable-slot messages) — same pattern as the existing 6 accepted instances in email_poller.py. Accepted as known debt.

Escalation (semi + full), relay, multi-trip reset, and returning customer are deferred to Briefs 071-072 to keep this brief focused on the core booking happy path.

## Source Material

### Trip data for tests (from client.json, verified)
- `klein_curacao`: price_adult_usd=120, days_available="daily", departures=[{time:"08:00", vessel:"BlueFinn2"}, {time:"08:30", vessel:"BlueFinn1"}] (multi-departure, 2), capacity=30, dep_point="Jan Thiel Beach"
- `sunset_cruise`: price_adult_usd=79, days_available="Tuesday, Thursday, Friday, Saturday", departures=[{time:"17:30", vessel:"Kailani"}] (single departure), capacity=20, dep_point="Village Marina/Mood pier"
- `west_coast_beach`: price_adult_usd=120, days_available="Wednesdays and Sundays", departures=[{time:"09:00", vessel:"Red Dragon"}] (single departure), capacity=25, dep_point="Mood/Tomatoes"

### Constants to duplicate from email_poller.py
```python
_BOOKING_INTENTS = {"booking", "reschedule"}

_BOOKING_FLAGS_TO_RESET = {
    "hold_created", "booking_confirmed", "booking_ref", "hold_id",
    "payment_id", "payment_link", "payment_status",
    "event_id", "event_link",
    "slot_checked", "slot_available", "spots_remaining", "trip_capacity",
    "awaiting_booking_confirmation",
    "hold_trip_key", "hold_date", "hold_departure_time",
}

_PERSISTENT_FIELDS = {"customer_name", "phone"}
```

### Helper functions to duplicate (adapted from email_poller.py lines 360-491)

`_day_matches(day_name, days_available)` — exact copy.

`_suggest_dates(date_str, days_available)` — exact copy.

`_build_booking_summary(fields, trip)` — adapted for WhatsApp: uses "Just to confirm:" (shorter) instead of email's "Just to confirm the details:". Intentional WhatsApp tone adaptation.

`_build_action_context(flags)` — simplified: takes flags dict directly (not th dict). Same logic.

`_post_validate(fields, flags, result, trip)` — simplified signature: takes fields and flags directly (not th dict). Same logic. Override replies do NOT include email signature (WhatsApp style).

### Booking flow to implement in handle_incoming_whatsapp_message

The flow mirrors email_poller.py lines 731-1146 but adapted for WhatsApp:

1. **Build action_context** from flags → pass to marina_agent
2. **Call marina_agent** with channel="whatsapp"
3. **Merge fields** (same as Brief 069 logic)
4. **Merge flags** — Python manages `awaiting_booking_confirmation` (Claude can only clear it via `false`, not set it)
5. **Change detection** — if was_awaiting and no longer awaiting and not confirmed: cancel hold, reset slot flags
6. **Post-validation** — if booking intent: run `_post_validate`, apply override or set awaiting
7. **Availability + soft hold** — if awaiting and not slot_checked: check availability, create soft hold
8. **Booking confirmation** — if booking intent + confirmed + not hold_created: generate booking_ref, create manifest, generate payment link, replace placeholders
9. **Strip remaining placeholders** — safety net
10. **Persist state + log**

## Instructions

### Step 1 — Rewrite `agents/social/social_agent.py`

Update the file header:
```python
# bluemarlin/agents/social/social_agent.py
# Created: Brief 068
# Last modified: Brief 070
# Purpose: WhatsApp booking orchestrator — calls marina_agent, validates, holds, confirms
```

Add imports:
```python
import time
from datetime import datetime, timezone, timedelta
from shared import state_registry
from shared import bm_logger
from shared import config_loader
from agents.marina import marina_agent
from agents.marina import gws_calendar
from agents.marina import payment_stub
from agents.marina import sheets_writer
```

Add constants (exact copies from email_poller.py):
```python
_BOOKING_INTENTS = {"booking", "reschedule"}

_BOOKING_FLAGS_TO_RESET = {
    "hold_created", "booking_confirmed", "booking_ref", "hold_id",
    "payment_id", "payment_link", "payment_status",
    "event_id", "event_link",
    "slot_checked", "slot_available", "spots_remaining", "trip_capacity",
    "awaiting_booking_confirmation",
    "hold_trip_key", "hold_date", "hold_departure_time",
}

_PERSISTENT_FIELDS = {"customer_name", "phone"}
```

Add helper functions:

```python
def _day_matches(day_name, days_available):
    """Check if day_name matches the trip's days_available string."""
    if days_available.lower() == "daily":
        return True
    return day_name.lower() in days_available.lower()


def _suggest_dates(date_str, days_available):
    """Suggest 2-3 nearby valid dates."""
    base = datetime.strptime(date_str, "%Y-%m-%d")
    suggestions = []
    for offset in range(1, 14):
        candidate = base + timedelta(days=offset)
        if _day_matches(candidate.strftime("%A"), days_available):
            suggestions.append(f"  {candidate.strftime('%A %d %B')}")
            if len(suggestions) >= 3:
                break
    return "\n".join(suggestions) if suggestions else "Please suggest another date!"


def _build_booking_summary(fields, trip):
    """Build a data-driven booking summary. WhatsApp adaptation: shorter intro than email."""
    trip_name = trip.get("display_name", fields.get("trip_key", ""))
    date_str = fields.get("date", "")
    guests = int(fields.get("guests") or 1)
    departure_time = fields.get("departure_time", "")
    departures = trip.get("departures", [])
    dep_info = next((d for d in departures if d.get("time") == departure_time), None)
    if not dep_info and departures:
        dep_info = departures[0]
        departure_time = dep_info.get("time", "")
    vessel = dep_info.get("vessel", "") if dep_info else ""
    dep_point = dep_info.get("departure_point", "") if dep_info else ""
    price_adult = trip.get("price_adult_usd", 0)
    total = price_adult * guests
    included = ", ".join(trip.get("included", [])) or "see trip details"
    try:
        date_fmt = datetime.strptime(date_str, "%Y-%m-%d").strftime("%A, %d %B %Y")
    except ValueError:
        date_fmt = date_str
    return (
        f"Just to confirm: {trip_name} on {date_fmt}, "
        f"{departure_time} departure from {dep_point} on {vessel}. "
        f"{guests} guests, ${total} total (${price_adult} each). "
        f"Includes {included}.\n\n"
        f"Want me to go ahead and book this?"
    )


def _build_action_context(flags):
    """Build action_context string for the Claude prompt based on flags."""
    if flags.get("awaiting_booking_confirmation"):
        return (
            "ACTION: A booking summary was sent. The customer is replying. "
            "Determine if they are: (a) confirming — set booking_confirmed: true, "
            "awaiting_booking_confirmation: false, write a warm celebratory reply "
            "with the exact string [PAYMENT_LINK] where the payment link goes. "
            "Also write reply_hold_failed — an apologetic message if the slot turns "
            "out to be unavailable, without [PAYMENT_LINK]; "
            "(b) changing something — extract new fields, set "
            "awaiting_booking_confirmation: false; (c) unclear — ask "
            "for clarification. Do NOT generate a new booking summary."
        )
    return ""


def _post_validate(fields, flags, result, trip):
    """
    Validate extracted fields after Claude call.
    Returns (reply_override, should_set_awaiting).
    """
    if not any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
        return None, False
    if not all(fields.get(k) for k in ("experience", "date", "guests", "trip_key")):
        return None, False
    if flags.get("awaiting_booking_confirmation") or flags.get("booking_confirmed"):
        return None, False

    date = fields["date"]
    departures = trip.get("departures", [])

    # 1. Day-of-week check
    try:
        day_name = datetime.strptime(date, "%Y-%m-%d").strftime("%A")
        days_avail = trip.get("days_available", "daily")
        if not _day_matches(day_name, days_avail):
            return (
                f"The {trip.get('display_name', fields['trip_key'])} "
                f"doesn't run on {day_name}s, only {days_avail}. "
                f"Would any of these work instead?\n\n"
                f"{_suggest_dates(date, days_avail)}"
            ), False
    except ValueError:
        pass

    # 1b. Past date check
    try:
        _pv_date_obj = datetime.strptime(date, "%Y-%m-%d").date()
        _pv_today = datetime.now(timezone(timedelta(hours=-4))).date()
        if _pv_date_obj < _pv_today:
            return (
                f"That date ({date}) has already passed. "
                f"Would you like to pick a different date?"
            ), False
    except ValueError:
        pass

    # 2. Departure time check (multi-departure trips only)
    if len(departures) > 1 and not fields.get("departure_time"):
        dep_lines = "\n".join(
            f"- {d['time']} aboard {d.get('vessel', '?')} from {d.get('departure_point', '?')}"
            for d in departures
        )
        return (
            f"The {trip.get('display_name', fields['trip_key'])} has "
            f"a couple of departure times:\n\n{dep_lines}\n\n"
            f"Which one works for you?"
        ), False

    # 3. Child pricing — Claude sets needs_child_ages flag
    if result.get("flags", {}).get("needs_child_ages"):
        return None, False

    # 4. All checks pass — build data-driven summary
    summary = _build_booking_summary(fields, trip)
    return summary, True
```

Rewrite `handle_incoming_whatsapp_message` to include the full booking flow:

```python
def handle_incoming_whatsapp_message(message: dict) -> str:
    """
    Process a WhatsApp message: full booking orchestrator.
    Fetch state + history → build action_context → call marina_agent →
    merge fields/flags → post-validate → availability + hold →
    booking confirmation → persist state → return reply.
    """
    phone = message.get("from", "")
    text = message.get("text", "")
    from_name = message.get("from_name", "")

    # Get existing booking state
    state = state_registry.wa_get_booking_state(phone)
    fields = state.get("fields", {})
    flags = state.get("flags", {})
    completed_bookings = state.get("completed_bookings", [])

    # Get conversation history (last 10 messages, 24h window)
    history = state_registry.wa_get_history(phone, limit=10)

    # Build from identifier with name if available
    from_id = f"{phone} ({from_name})" if from_name else phone

    # Step 1: Build action context
    action_context = _build_action_context(flags)

    # Step 2: Call marina_agent with channel="whatsapp"
    result = marina_agent.process_message(
        from_email=from_id,
        subject="",
        body=text,
        thread_fields=fields,
        thread_flags=flags,
        action_context=action_context,
        channel="whatsapp",
        messages=history,
    )

    reply = result.get("reply", "")

    if not reply:
        return ""

    # Step 3: Merge fields — overwrite when Claude returns non-empty values
    new_fields = result.get("fields", {}) or {}
    for k, v in new_fields.items():
        if v is not None and v != "":
            fields[k] = v
        elif v == "" and k in fields:
            del fields[k]

    # Step 4: Merge flags — Python manages awaiting_booking_confirmation (set only)
    new_flags = result.get("flags", {}) or {}
    _was_awaiting = flags.get("awaiting_booking_confirmation", False)
    if new_flags.get("awaiting_booking_confirmation"):
        new_flags.pop("awaiting_booking_confirmation")
    flags.update(new_flags)

    # Step 5: Change detection — cancel soft hold if customer changed booking details
    if (_was_awaiting and not flags.get("awaiting_booking_confirmation")
            and not flags.get("booking_confirmed")):
        if flags.get("hold_id"):
            state_registry.cancel_hold(flags["hold_id"])
            _h_trip = flags.pop("hold_trip_key", "")
            _h_date = flags.pop("hold_date", "")
            _h_dep = flags.pop("hold_departure_time", "")
            flags.pop("hold_id", None)
            if _h_trip and _h_date and _h_dep:
                gws_calendar.remove_from_manifest(_h_trip, _h_date, _h_dep)
        flags["slot_checked"] = False
        flags["slot_available"] = False
        bm_logger.log("whatsapp_hold_cancelled", phone=phone,
                      reason="customer_changed_details")

    reply_text = reply

    # Step 6: Post-validation (booking intents only)
    _pv_trip_key = fields.get("trip_key", "")
    _pv_trip = config_loader.get_trip(_pv_trip_key) if _pv_trip_key else {}
    if any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
        _pv_override, _pv_set_awaiting = _post_validate(fields, flags, result, _pv_trip)
        if _pv_override:
            _intents = result.get("intents", [])
            _has_side_topics = any(i not in _BOOKING_INTENTS for i in _intents)
            if _has_side_topics:
                reply_text = result["reply"].rstrip() + "\n\n" + _pv_override
            else:
                reply_text = _pv_override
            if _pv_set_awaiting:
                flags["awaiting_booking_confirmation"] = True

    # Step 7: Availability pre-check + soft hold when booking summary is being sent
    if (flags.get("awaiting_booking_confirmation")
            and not flags.get("slot_checked")):
        _ck_trip = fields.get("trip_key", "")
        _ck_deps = config_loader.get_trip(_ck_trip).get("departures", []) if _ck_trip else []
        _ck_start = (fields.get("departure_time")
                     or (_ck_deps[0].get("time", "09:00") if _ck_deps else "09:00"))
        _ck_guests = int(fields.get("guests") or 1)
        avail = gws_calendar.check_availability(
            _ck_trip, fields.get("date", ""), _ck_start, _ck_guests)
        flags["slot_checked"] = True
        flags["slot_available"] = avail.get("available", False)
        flags["spots_remaining"] = avail.get("spots_remaining", 0)
        flags["trip_capacity"] = avail.get("capacity", 0)
        if avail.get("available"):
            hold_id = state_registry.create_soft_hold(
                _ck_trip,
                fields.get("date", ""),
                _ck_start,
                _ck_guests,
                avail.get("capacity", 20),
                customer_name=fields.get("customer_name", ""),
                customer_email=phone,
            )
            if hold_id is not None:
                flags["hold_id"] = hold_id
                flags["hold_trip_key"] = _ck_trip
                flags["hold_date"] = fields.get("date", "")
                flags["hold_departure_time"] = _ck_start
                bm_logger.log("whatsapp_soft_hold_created", phone=phone,
                              hold_id=hold_id, trip_key=_ck_trip)
            else:
                # Race: capacity was grabbed between check and insert
                flags["slot_available"] = False
                flags["awaiting_booking_confirmation"] = False
                flags["slot_checked"] = False
                _unavail_name = _pv_trip.get("display_name", _ck_trip)
                reply_text = (
                    f"Unfortunately the {_unavail_name} is fully booked on that date. "
                    f"Would you like to try a different date?"
                )
                bm_logger.log("whatsapp_soft_hold_race", phone=phone, trip_key=_ck_trip)
        else:
            flags["awaiting_booking_confirmation"] = False
            flags["slot_checked"] = False
            _unavail_name = _pv_trip.get("display_name", _ck_trip)
            reply_text = (
                f"Unfortunately the {_unavail_name} is fully booked on that date. "
                f"Would you like to try a different date?"
            )
            bm_logger.log("whatsapp_slot_unavailable", phone=phone, trip_key=_ck_trip,
                          spots=avail.get("spots_remaining", 0))

    # Step 8: Booking confirmation flow
    if any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
        if (fields.get("experience") and fields.get("date")
                and fields.get("guests") and fields.get("trip_key")
                and flags.get("booking_confirmed")
                and not flags.get("hold_created")):
            bm_logger.log("whatsapp_booking_attempted", phone=phone,
                          trip_key=fields.get("trip_key"),
                          date=fields.get("date"), guests=fields.get("guests"))

            # Generate booking_ref + set on soft hold BEFORE manifest creation
            booking_ref = f"BF-{time.strftime('%Y')}-{int(time.time()) % 100000:05d}"
            flags["booking_ref"] = booking_ref
            if flags.get("hold_id"):
                state_registry.set_booking_ref(flags["hold_id"], booking_ref)

            res = gws_calendar.create_or_update_manifest(fields)
            if not res.get("ok"):
                bm_logger.log("whatsapp_manifest_failed", phone=phone,
                              error=res.get("error"))
                if flags.get("hold_id"):
                    state_registry.cancel_hold(flags["hold_id"])
                    _h_trip = flags.pop("hold_trip_key", "")
                    _h_date = flags.pop("hold_date", "")
                    _h_dep = flags.pop("hold_departure_time", "")
                    flags.pop("hold_id", None)
                    if _h_trip and _h_date and _h_dep:
                        gws_calendar.remove_from_manifest(_h_trip, _h_date, _h_dep)
                flags["slot_checked"] = False
                flags["slot_available"] = False
                reply_text = result.get("reply_hold_failed") or reply_text
                sheets_writer.log_hold_failed({
                    "email": phone, "subject": "WhatsApp",
                    "experience": fields.get("experience"),
                    "date": fields.get("date"),
                    "guests": fields.get("guests"),
                    "error": res.get("error"),
                })
            else:
                flags["hold_created"] = True
                if flags.get("hold_id"):
                    state_registry.confirm_hold(flags["hold_id"])
                flags["event_id"] = res.get("eventId")
                flags["event_link"] = res.get("htmlLink")
                trip_key = fields.get("trip_key", "")
                price_usd = (config_loader.get_trip(trip_key).get("price_adult_usd", 0)
                             if trip_key else 0)
                pay = payment_stub.generate_payment_link(booking_ref, price_usd)
                pay_link = f"https://demo.pay/bluemarlin/{pay['payment_id']}"
                flags["payment_id"] = pay.get("payment_id")
                flags["payment_link"] = pay_link
                flags["payment_status"] = pay.get("status")
                reply_text = reply_text.replace("[PAYMENT_LINK]", pay_link)
                reply_text = reply_text.replace("[BOOKING_REF]", booking_ref)
                bm_logger.log("whatsapp_booking_confirmed", phone=phone,
                              booking_ref=booking_ref, trip_key=trip_key)
                sheets_writer.log_hold_created({
                    "booking_ref": booking_ref,
                    "email": phone, "subject": "WhatsApp",
                    "customer_name": fields.get("customer_name"),
                    "experience": fields.get("experience"),
                    "trip_key": fields.get("trip_key"),
                    "date": fields.get("date"),
                    "guests": fields.get("guests"),
                    "departure_time": fields.get("departure_time"),
                    "phone": phone,
                    "special_requests": fields.get("special_requests"),
                    "total_price": int(fields.get("guests") or 0) * price_usd,
                    "html_link": flags.get("event_link"),
                    "payment_link": flags.get("payment_link"),
                    "payment_status": pay.get("status"),
                })
                # Log manifest summary to Sheets
                _m_passengers = state_registry.get_slot_passengers(
                    trip_key, fields.get("date", ""), fields.get("departure_time", ""))
                _m_confirmed = sum(1 for p in _m_passengers if p["status"] == "confirmed")
                _m_pending = sum(1 for p in _m_passengers if p["status"] == "soft_hold")
                _m_total_guests = sum(p["guests"] for p in _m_passengers)
                _m_total_revenue = _m_total_guests * price_usd
                _m_capacity = config_loader.get_trip(trip_key).get("capacity", 20)
                sheets_writer.log_manifest_update({
                    "trip_key": trip_key,
                    "date": fields.get("date", ""),
                    "departure_time": fields.get("departure_time", ""),
                    "total_guests": _m_total_guests,
                    "capacity": _m_capacity,
                    "confirmed_count": _m_confirmed,
                    "pending_count": _m_pending,
                    "total_revenue": _m_total_revenue,
                    "calendar_link": flags.get("event_link", ""),
                    "booking_ref": booking_ref,
                })
                # Save booking for cross-thread memory
                state_registry.save_booking(
                    booking_ref, fields, flags,
                    customer_email=phone,
                )

    # Step 9: Strip remaining placeholders (safety net)
    reply_text = reply_text.replace("[BOOKING_REF]", "").replace("[PAYMENT_LINK]", "")

    # Step 10: Persist state + log
    state_registry.wa_save_booking_state(phone, fields, flags, completed_bookings)
    bm_logger.log("whatsapp_agent_reply", phone=phone,
                  intents=result.get("intents", []), reply_length=len(reply_text))

    return reply_text
```

### Step 2 — Create `tests/social/test_070_whatsapp_booking.py`

```python
# bluemarlin/tests/social/test_070_whatsapp_booking.py
# Created: Brief 070
# Purpose: Tests for WhatsApp booking orchestrator

import os
import sys
import json
import time
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..')))

os.environ["WHATSAPP_VERIFY_TOKEN"] = "test_token_067"
os.environ["WHATSAPP_ACCESS_TOKEN"] = "test_access_token"
os.environ["WHATSAPP_PHONE_NUMBER_ID"] = "990622044139349"

from agents.social.social_agent import (
    _day_matches, _suggest_dates, _build_booking_summary,
    _build_action_context, _post_validate,
    _BOOKING_INTENTS, _BOOKING_FLAGS_TO_RESET, _PERSISTENT_FIELDS,
    handle_incoming_whatsapp_message,
)
from shared import config_loader
from shared import state_registry


# --- Helpers ---

def _cleanup_phone(phone):
    conn = state_registry._get_conn()
    conn.execute("DELETE FROM whatsapp_threads WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM whatsapp_booking_state WHERE phone = ?", (phone,))
    conn.execute("DELETE FROM trip_bookings WHERE customer_email = ?", (phone,))
    conn.commit()
    conn.close()


# --- Helper function unit tests (pure functions, real config_loader) ---

def test_day_matches_daily():
    """Daily trips match any day."""
    assert _day_matches("Monday", "Daily") is True
    assert _day_matches("Sunday", "daily") is True


def test_day_matches_specific_days():
    """Specific days match correctly."""
    assert _day_matches("Wednesday", "Wednesdays and Sundays") is True
    assert _day_matches("Sunday", "Wednesdays and Sundays") is True
    assert _day_matches("Monday", "Wednesdays and Sundays") is False
    assert _day_matches("Friday", "Tuesday, Thursday, Friday, Saturday") is True


def test_suggest_dates_west_coast():
    """West Coast Beach runs Wed/Sun — Monday 2026-03-16 suggests nearby valid dates."""
    suggestions = _suggest_dates("2026-03-16", "Wednesdays and Sundays")
    assert "Wednesday" in suggestions  # 2026-03-18
    assert "Sunday" in suggestions  # 2026-03-22


def test_build_booking_summary_west_coast():
    """Summary contains correct price, date, guests from real trip config."""
    trip = config_loader.get_trip("west_coast_beach")
    fields = {
        "trip_key": "west_coast_beach",
        "experience": "West Coast Beach Trip",
        "date": "2026-03-18",  # Wednesday
        "guests": "3",
        "departure_time": "09:00",
    }
    summary = _build_booking_summary(fields, trip)
    assert "$360" in summary  # 3 * $120
    assert "$120" in summary  # per person
    assert "Wednesday" in summary
    assert "09:00" in summary
    assert "Red Dragon" in summary
    assert "book this?" in summary.lower()


def test_build_booking_summary_single_departure_auto():
    """Single-departure trip auto-selects departure when not specified."""
    trip = config_loader.get_trip("west_coast_beach")
    fields = {
        "trip_key": "west_coast_beach",
        "experience": "West Coast Beach Trip",
        "date": "2026-03-18",  # Wednesday
        "guests": "2",
    }
    summary = _build_booking_summary(fields, trip)
    assert "09:00" in summary  # auto-selected from single departure


def test_build_action_context_awaiting():
    """Action context generated when awaiting_booking_confirmation is True."""
    ctx = _build_action_context({"awaiting_booking_confirmation": True})
    assert "booking summary was sent" in ctx
    assert "[PAYMENT_LINK]" in ctx
    assert "reply_hold_failed" in ctx


def test_build_action_context_not_awaiting():
    """No action context when not awaiting confirmation."""
    ctx = _build_action_context({})
    assert ctx == ""


def test_post_validate_day_of_week_rejection():
    """Monday booking for West Coast Beach (Wed/Sun only) is rejected."""
    trip = config_loader.get_trip("west_coast_beach")
    fields = {"experience": "West Coast Beach Trip", "date": "2026-03-16",
              "guests": "2", "trip_key": "west_coast_beach"}  # Monday
    result = {"intents": ["booking"], "flags": {}}
    override, should_set = _post_validate(fields, {}, result, trip)
    assert override is not None
    assert "doesn't run on Monday" in override
    assert should_set is False


def test_post_validate_past_date_rejection():
    """Past date is rejected (klein_curacao is daily, so day-of-week check passes first)."""
    trip = config_loader.get_trip("klein_curacao")
    fields = {"experience": "Klein Curacao", "date": "2025-01-15",
              "guests": "2", "trip_key": "klein_curacao"}
    result = {"intents": ["booking"], "flags": {}}
    override, should_set = _post_validate(fields, {}, result, trip)
    assert override is not None
    assert "already passed" in override
    assert should_set is False


def test_post_validate_multi_departure_asks():
    """Multi-departure trip (klein_curacao: 08:00, 08:30) without departure_time asks for selection."""
    trip = config_loader.get_trip("klein_curacao")
    fields = {"experience": "Klein Curacao", "date": "2026-03-20",
              "guests": "2", "trip_key": "klein_curacao"}
    result = {"intents": ["booking"], "flags": {}}
    override, should_set = _post_validate(fields, {}, result, trip)
    assert override is not None
    assert "departure time" in override.lower()
    assert "08:00" in override
    assert "08:30" in override
    assert should_set is False


def test_post_validate_all_pass_builds_summary():
    """All fields valid — summary built, should_set_awaiting is True."""
    trip = config_loader.get_trip("west_coast_beach")
    fields = {"experience": "West Coast Beach Trip", "date": "2026-03-18",
              "guests": "2", "trip_key": "west_coast_beach",
              "departure_time": "09:00"}  # Wednesday, single departure
    result = {"intents": ["booking"], "flags": {}}
    override, should_set = _post_validate(fields, {}, result, trip)
    assert override is not None
    assert "$240" in override  # 2 * $120
    assert should_set is True


def test_post_validate_skips_non_booking_intent():
    """Non-booking intent skips validation entirely."""
    trip = config_loader.get_trip("klein_curacao")
    fields = {"experience": "Klein Curacao", "date": "2026-03-20",
              "guests": "2", "trip_key": "klein_curacao"}
    result = {"intents": ["inquiry"], "flags": {}}
    override, should_set = _post_validate(fields, {}, result, trip)
    assert override is None
    assert should_set is False


# --- Orchestrator integration tests (mocked externals) ---

@patch("agents.social.social_agent.marina_agent.process_message")
def test_orchestrator_post_validate_day_override(mock_process):
    """Booking on wrong day returns day-of-week override instead of Claude reply."""
    phone = "TEST_070_DAY_001"
    _cleanup_phone(phone)
    mock_process.return_value = {
        "intents": ["booking"],
        "fields": {"trip_key": "west_coast_beach", "experience": "West Coast Beach",
                    "date": "2026-03-16", "guests": "2"},  # Monday — Wed/Sun only
        "confidence": "high",
        "reply": "I'll book West Coast Beach for you!",
        "clarifications_needed": [], "requires_human": False,
        "flags": {}, "internal_note": ""
    }
    msg = {"from": phone, "text": "Book West Coast Beach March 16 for 2", "from_name": "Test"}
    reply = handle_incoming_whatsapp_message(msg)
    assert "doesn't run on Monday" in reply
    assert "[BOOKING_REF]" not in reply
    _cleanup_phone(phone)


@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_orchestrator_booking_summary_sent(mock_process, mock_cal, mock_pay, mock_sheets):
    """Valid booking fields trigger summary and awaiting_booking_confirmation flag."""
    phone = "TEST_070_SUMMARY_001"
    _cleanup_phone(phone)
    mock_process.return_value = {
        "intents": ["booking"],
        "fields": {"trip_key": "west_coast_beach", "experience": "West Coast Beach",
                    "date": "2026-03-18", "guests": "2",
                    "customer_name": "John"},  # Wednesday — single departure, auto-selects 09:00
        "confidence": "high",
        "reply": "Sounds good!",
        "clarifications_needed": [], "requires_human": False,
        "flags": {}, "internal_note": ""
    }
    mock_cal.check_availability.return_value = {"available": True, "spots_remaining": 23, "capacity": 25}
    msg = {"from": phone, "text": "West Coast Beach March 18 for 2", "from_name": "John"}
    reply = handle_incoming_whatsapp_message(msg)
    # Should contain booking summary (from _post_validate — single departure auto-selects 09:00)
    assert "$240" in reply  # 2 * $120
    assert "book this?" in reply.lower()
    # Check awaiting flag was set
    state = state_registry.wa_get_booking_state(phone)
    assert state["flags"].get("awaiting_booking_confirmation") is True
    assert state["flags"].get("slot_checked") is True
    _cleanup_phone(phone)


@patch("agents.social.social_agent.sheets_writer")
@patch("agents.social.social_agent.payment_stub")
@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_orchestrator_booking_confirmed(mock_process, mock_cal, mock_pay, mock_sheets):
    """Customer confirms booking — booking_ref and payment_link replaced in reply."""
    phone = "TEST_070_CONFIRM_001"
    _cleanup_phone(phone)
    # Pre-set state: awaiting confirmation with soft hold
    fields = {"trip_key": "west_coast_beach", "experience": "West Coast Beach",
              "date": "2026-03-18", "guests": "2",
              "departure_time": "09:00", "customer_name": "John"}
    hold_id = state_registry.create_soft_hold("west_coast_beach", "2026-03-18", "09:00", 2, 25,
                                               customer_name="John", customer_email=phone)
    flags = {"awaiting_booking_confirmation": True, "slot_checked": True,
             "slot_available": True, "hold_id": hold_id,
             "hold_trip_key": "west_coast_beach", "hold_date": "2026-03-18",
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
    mock_cal.create_or_update_manifest.return_value = {"ok": True, "eventId": "e2", "htmlLink": "http://cal/e2"}
    mock_pay.generate_payment_link.return_value = {"payment_id": "pay123", "status": "pending"}

    msg = {"from": phone, "text": "Yes book it!", "from_name": "John"}
    reply = handle_incoming_whatsapp_message(msg)
    assert "[BOOKING_REF]" not in reply
    assert "[PAYMENT_LINK]" not in reply
    assert "BF-" in reply  # real booking ref
    assert "demo.pay" in reply  # real payment link
    # Verify state
    state = state_registry.wa_get_booking_state(phone)
    assert state["flags"].get("hold_created") is True
    assert state["flags"].get("booking_ref", "").startswith("BF-")
    assert "demo.pay" in state["flags"].get("payment_link", "")
    # Cleanup
    _cleanup_phone(phone)


@patch("agents.social.social_agent.gws_calendar")
@patch("agents.social.social_agent.marina_agent.process_message")
def test_orchestrator_slot_unavailable(mock_process, mock_cal):
    """Slot unavailable returns friendly message, does not set awaiting."""
    phone = "TEST_070_UNAVAIL_001"
    _cleanup_phone(phone)
    mock_process.return_value = {
        "intents": ["booking"],
        "fields": {"trip_key": "west_coast_beach", "experience": "West Coast Beach",
                    "date": "2026-03-18", "guests": "2",
                    "departure_time": "09:00", "customer_name": "Jane"},
        "confidence": "high",
        "reply": "Sounds good!",
        "clarifications_needed": [], "requires_human": False,
        "flags": {}, "internal_note": ""
    }
    mock_cal.check_availability.return_value = {"available": False, "spots_remaining": 0, "capacity": 25}
    msg = {"from": phone, "text": "Book it for March 18", "from_name": "Jane"}
    reply = handle_incoming_whatsapp_message(msg)
    assert "fully booked" in reply.lower()
    state = state_registry.wa_get_booking_state(phone)
    assert state["flags"].get("awaiting_booking_confirmation") is not True
    _cleanup_phone(phone)
```

## Tests

Run all tests:
```bash
cd /Users/benson/Projects/bluemarlin-agent/bluemarlin && python3 -m pytest tests/social/test_070_whatsapp_booking.py -v
```

Regression:
```bash
cd /Users/benson/Projects/bluemarlin-agent/bluemarlin && python3 -m pytest tests/social/test_069_whatsapp_agent.py tests/social/test_068_pipeline.py tests/social/test_067_webhook.py -v
```

### Expected test counts
- Brief 070: 17/17
- Brief 069: 17/17 (regression)
- Brief 068: 10/10 (regression)
- Brief 067: 7/7 (regression)

### Regression safety note
Brief 069 tests that call `handle_incoming_whatsapp_message` mock `marina_agent.process_message` to return non-booking intents (inquiry) with empty fields. After Brief 070's rewrite, these paths skip all booking flow sections (no booking intent → no post-validate, no availability check, no confirmation) and reach the placeholder strip + persist steps safely. The new imports (`gws_calendar`, `payment_stub`, `sheets_writer`) have no module-level side effects beyond imports, so they load safely.

## Success Condition
All 51 tests pass (17 new + 34 regression). `social_agent.py` contains complete booking flow: post-validation, availability check, soft hold, booking confirmation with real booking_ref and payment_link in reply.

## Rollback
```bash
git checkout HEAD -- bluemarlin/agents/social/social_agent.py
rm bluemarlin/tests/social/test_070_whatsapp_booking.py
```
