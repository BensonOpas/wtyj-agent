# bluemarlin/agents/social/social_agent.py
# Created: Brief 068
# Last modified: Brief 100
# Purpose: WhatsApp booking orchestrator with escalation — calls marina_agent, validates, holds, confirms, escalates

import random
import re
import string
import time
import json
import uuid
from datetime import datetime, timezone, timedelta
from shared import state_registry
from shared import bm_logger
from shared import config_loader
from agents.marina import marina_agent
from agents.marina import gws_calendar
from agents.marina import payment_stub
from agents.marina import sheets_writer


_BOOKING_INTENTS = {"booking", "reschedule"}

_BOOKING_FLAGS_TO_RESET = {
    "hold_created", "booking_confirmed", "booking_ref", "hold_id",
    "payment_id", "payment_link", "payment_status",
    "event_id", "event_link",
    "slot_checked", "slot_available", "spots_remaining", "trip_capacity",
    "awaiting_booking_confirmation",
    "hold_service_key", "hold_date", "hold_slot_time",
    "awaiting_escalation_email", "needs_escalation_email",
}

_PERSISTENT_FIELDS = {"customer_name", "phone", "email"}

_MAX_REPLIES_PER_HOUR = 50
_REPLY_WINDOW_SECONDS = 3600
_STALE_CONVERSATION_SECONDS = 86400  # 24 hours — matches wa_get_history window


def _day_matches(day_name, days_available):
    """Check if day_name matches the service's days_available string."""
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


def _build_booking_summary(fields, service):
    """Build a data-driven booking summary. WhatsApp adaptation: shorter intro than email."""
    svc_name = service.get("display_name", fields.get("service_key", ""))
    date_str = fields.get("date", "")
    guests = int(fields.get("guests") or 1)
    slot_time = fields.get("slot_time", "")
    slots = service.get("slots", [])
    slot_info = next((d for d in slots if d.get("time") == slot_time), None)
    if not slot_info and slots:
        slot_info = slots[0]
        slot_time = slot_info.get("time", "")
    resource = slot_info.get("resource", "") if slot_info else ""
    location = slot_info.get("location", "") if slot_info else ""
    price_base = service.get("price", 0)
    total = price_base * guests
    included = ", ".join(service.get("included", [])) or "see details"
    try:
        date_fmt = datetime.strptime(date_str, "%Y-%m-%d").strftime("%A, %d %B %Y")
    except ValueError:
        date_fmt = date_str
    return (
        f"Just to confirm: {svc_name} on {date_fmt}, "
        f"{slot_time} from {location} on {resource}. "
        f"{guests} guests, ${total} total (${price_base} each). "
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
            "awaiting_booking_confirmation: false; "
            "(c) unclear — ask for clarification; "
            "(d) declining or saying no — set awaiting_booking_confirmation: false, "
            "use intent 'inquiry' (not 'booking'), acknowledge gracefully and ask "
            "if they'd like to look at something else. "
            "Do NOT generate a new booking summary."
        )
    return ""


def _post_validate(fields, flags, result, service):
    """
    Validate extracted fields after Claude call.
    Returns (reply_override, should_set_awaiting).
    """
    if not any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
        return None, False
    if not all(fields.get(k) for k in ("service_name", "date", "guests", "service_key")):
        return None, False
    if flags.get("awaiting_booking_confirmation") or flags.get("booking_confirmed"):
        return None, False

    date = fields["date"]
    slots = service.get("slots", [])

    # 1. Day-of-week check
    try:
        day_name = datetime.strptime(date, "%Y-%m-%d").strftime("%A")
        days_avail = service.get("days_available", "daily")
        if not _day_matches(day_name, days_avail):
            return (
                f"The {service.get('display_name', fields['service_key'])} "
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
    if len(slots) > 1 and not fields.get("slot_time"):
        dep_lines = "\n".join(
            f"- {d['time']} aboard {d.get('resource', '?')} from {d.get('location', '?')}"
            for d in slots
        )
        return (
            f"The {service.get('display_name', fields['service_key'])} has "
            f"a couple of departure times:\n\n{dep_lines}\n\n"
            f"Which one works for you?"
        ), False

    # 3. Child pricing — Claude sets needs_child_ages flag
    if result.get("flags", {}).get("needs_child_ages"):
        return None, False

    # 4. All checks pass — build data-driven summary
    summary = _build_booking_summary(fields, service)
    return summary, True


def _maybe_reset_stale_conversation(last_activity, fields, flags, completed_bookings):
    """Reset booking state if >24h since last activity. Returns True if reset happened."""
    if not last_activity:
        return False
    try:
        last = datetime.fromisoformat(last_activity)
        now = datetime.now(timezone.utc)
        if (now - last).total_seconds() < _STALE_CONVERSATION_SECONDS:
            return False
    except (ValueError, TypeError):
        return False

    # Archive current booking if one exists
    if flags.get("hold_created"):
        archived = {
            "booking_ref": flags.get("booking_ref", ""),
            "service_key": fields.get("service_key", ""),
            "service_name": fields.get("service_name", ""),
            "date": fields.get("date", ""),
            "guests": fields.get("guests", ""),
            "slot_time": fields.get("slot_time", ""),
            "payment_link": flags.get("payment_link", ""),
        }
        completed_bookings.append(archived)

    # Reset fields — keep customer identity
    preserved = {k: v for k, v in fields.items() if k in _PERSISTENT_FIELDS}
    fields.clear()
    fields.update(preserved)

    # Reset all booking + escalation + rate-limit flags
    for fk in _BOOKING_FLAGS_TO_RESET:
        flags.pop(fk, None)
    for fk in ("fully_escalated", "awaiting_relay", "relay_token",
               "relay_question", "reply_times", "returning_booking"):
        flags.pop(fk, None)

    return True


def handle_incoming_whatsapp_message(message: dict) -> str:
    """
    Process a WhatsApp message: full booking orchestrator.
    Fetch state + history -> build action_context -> call marina_agent ->
    merge fields/flags -> post-validate -> availability + hold ->
    booking confirmation -> persist state -> return reply.
    """
    phone = message.get("from", "")
    text = message.get("text", "")
    from_name = message.get("from_name", "")

    # Get existing booking state
    state = state_registry.wa_get_booking_state(phone)
    fields = state.get("fields", {})
    flags = state.get("flags", {})
    completed_bookings = state.get("completed_bookings", [])
    last_activity = state.get("last_activity")

    # Stale conversation reset — 24h inactivity gap means new conversation
    if _maybe_reset_stale_conversation(last_activity, fields, flags, completed_bookings):
        bm_logger.log("whatsapp_stale_reset", phone=phone)
        state_registry.wa_store_message(phone, "system", "Conversation reset after 24h inactivity")

    # Anti-loop guard — rate limit per phone
    _reply_times = flags.get("reply_times", [])
    _now_ts = int(time.time())
    _reply_times = [t for t in _reply_times if _now_ts - t <= _REPLY_WINDOW_SECONDS]
    flags["reply_times"] = _reply_times
    if len(_reply_times) >= _MAX_REPLIES_PER_HOUR:
        bm_logger.log("whatsapp_rate_limited", phone=phone,
                      count=len(_reply_times))
        state_registry.wa_save_booking_state(phone, fields, flags, completed_bookings)
        return ""

    # Get conversation history (last 10 messages, 24h window)
    history = state_registry.wa_get_history(phone, limit=10)

    # Build from identifier with name if available
    display_name = fields.get("customer_name") or from_name
    from_id = f"{phone} ({display_name})" if display_name else phone

    bm_logger.log("whatsapp_processing", phone=phone, text=text[:100],
                  from_name=from_name)

    # Fully escalated guard — still calls marina_agent (one Claude call), skip booking flow
    if flags.get("fully_escalated"):
        _esc_flags = dict(flags)
        for _rk in ("awaiting_relay", "relay_token", "relay_question", "reply_times"):
            _esc_flags.pop(_rk, None)
        esc_result = marina_agent.process_message(
            from_email=from_id, subject="", body=text,
            thread_fields=fields, thread_flags=_esc_flags,
            channel="whatsapp", messages=history,
        )
        esc_reply = esc_result.get("reply", "")
        bm_logger.log("whatsapp_escalated_reply", phone=phone,
                      reply_length=len(esc_reply))
        # Record reply timestamp + persist (early return bypasses end-of-function persistence)
        if esc_reply:
            _reply_times = flags.get("reply_times", [])
            _reply_times.append(int(time.time()))
            flags["reply_times"] = _reply_times
        state_registry.wa_save_booking_state(phone, fields, flags, completed_bookings)
        return esc_reply

    # Step 1: Build action context
    action_context = _build_action_context(flags)

    # Filter relay flags + internal state before marina_agent call
    agent_flags = dict(flags)
    for _rk in ("awaiting_relay", "relay_token", "relay_question", "reply_times"):
        agent_flags.pop(_rk, None)

    # Returning customer — booking ref detection
    _detected_ref = None
    _ref_match = re.search(r'\b[A-Z0-9]{6}\b', text)
    if _ref_match:
        _detected_ref = _ref_match.group()
        if not flags.get("booking_ref"):
            _past_booking = state_registry.get_booking(_detected_ref)
            if _past_booking:
                flags["returning_booking"] = _detected_ref
                agent_flags["returning_booking"] = _detected_ref
                for _rbk in ("service_key", "date", "guests", "customer_name", "slot_time"):
                    _rbv = _past_booking.get(_rbk)
                    if _rbv and not fields.get(_rbk):
                        fields[_rbk] = _rbv if not isinstance(_rbv, int) else str(_rbv)
                bm_logger.log("whatsapp_returning_customer", phone=phone, booking_ref=_detected_ref)
            else:
                flags["unknown_ref"] = _detected_ref
                agent_flags["unknown_ref"] = _detected_ref
                bm_logger.log("whatsapp_unknown_ref", phone=phone, ref=_detected_ref)

    # Returning customer — phone-based lookup (cross-thread memory)
    if not _detected_ref and not completed_bookings:
        _phone_bookings = state_registry.get_bookings_by_email(phone)
        if _phone_bookings:
            _eb_lines = []
            for _eb in _phone_bookings[:3]:
                _eb_lines.append(
                    f"  - {_eb['service_key']} on {_eb['date']} for {_eb['guests']} guests "
                    f"(ref: {_eb['booking_ref']})")
            agent_flags["_past_customer_bookings"] = "\n".join(_eb_lines)
            bm_logger.log("whatsapp_returning_by_phone", phone=phone,
                          past_count=len(_phone_bookings))

    # Completed bookings context for multi-service conversations
    if completed_bookings:
        _cb_lines = []
        for _cb in completed_bookings:
            _cb_lines.append(
                f"  - {_cb.get('service_name', _cb.get('service_key', '?'))} on "
                f"{_cb.get('date', '?')} for {_cb.get('guests', '?')} guests "
                f"(ref: {_cb.get('booking_ref', 'N/A')})")
        agent_flags["_completed_bookings_summary"] = "\n".join(_cb_lines)
        _max_bk = config_loader.get_booking_rules().get("max_bookings_per_thread", 3)
        if len(completed_bookings) >= _max_bk and flags.get("hold_created"):
            agent_flags["_max_bookings_reached"] = True

    # Call marina_agent with channel="whatsapp"
    result = marina_agent.process_message(
        from_email=from_id,
        subject="",
        body=text,
        thread_fields=fields,
        thread_flags=agent_flags,
        action_context=action_context,
        channel="whatsapp",
        messages=history,
    )

    reply = result.get("reply", "")

    if not reply:
        bm_logger.log("whatsapp_empty_reply", phone=phone,
                      intents=result.get("intents", []),
                      confidence=result.get("confidence", ""),
                      internal_note=result.get("internal_note", "")[:200])
        return ""

    # Multi-service: if booking intent + previous booking completed, archive and reset
    if (any(i in _BOOKING_INTENTS for i in result.get("intents", []))
            and flags.get("hold_created")):
        _max_bk = config_loader.get_booking_rules().get("max_bookings_per_thread", 3)
        if len(completed_bookings) < _max_bk:
            archived = {
                "booking_ref": flags.get("booking_ref", ""),
                "service_key": fields.get("service_key", ""),
                "service_name": fields.get("service_name", ""),
                "date": fields.get("date", ""),
                "guests": fields.get("guests", ""),
                "slot_time": fields.get("slot_time", ""),
                "payment_link": flags.get("payment_link", ""),
            }
            completed_bookings.append(archived)
            preserved = {k: v for k, v in fields.items() if k in _PERSISTENT_FIELDS}
            fields.clear()
            fields.update(preserved)
            for _fk in _BOOKING_FLAGS_TO_RESET:
                flags.pop(_fk, None)
            bm_logger.log("whatsapp_multi_trip_reset", phone=phone,
                          booking_number=len(completed_bookings))
            state_registry.wa_store_message(phone, "system",
                f"Previous booking archived ({archived.get('service_key', '')} {archived.get('date', '')}). Starting new booking.")

    # Clear one-shot flags after Claude has seen them
    flags.pop("unknown_ref", None)

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
            _h_svc = flags.pop("hold_service_key", "")
            _h_date = flags.pop("hold_date", "")
            _h_dep = flags.pop("hold_slot_time", "")
            flags.pop("hold_id", None)
            if _h_svc and _h_date and _h_dep:
                gws_calendar.remove_from_manifest(_h_svc, _h_date, _h_dep)
        flags["slot_checked"] = False
        flags["slot_available"] = False
        bm_logger.log("whatsapp_hold_cancelled", phone=phone,
                      reason="customer_changed_details")

    reply_text = reply

    # Step 6: Post-validation (booking intents only)
    _pv_service_key = fields.get("service_key", "")
    _pv_service = config_loader.get_service(_pv_service_key) if _pv_service_key else {}
    _run_pv = any(i in _BOOKING_INTENTS for i in result.get("intents", []))
    # Guard: if customer was responding to a booking summary and didn't change
    # any booking fields, skip post-validate to prevent decline loop
    if _run_pv and _was_awaiting and not flags.get("booking_confirmed"):
        _new_f = result.get("fields", {}) or {}
        if not any(_new_f.get(k) for k in ("service_name", "date", "guests", "service_key", "slot_time")):
            _run_pv = False
    if _run_pv:
        _pv_override, _pv_set_awaiting = _post_validate(fields, flags, result, _pv_service)
        if _pv_override:
            _intents = result.get("intents", [])
            _has_side_topics = any(i not in _BOOKING_INTENTS for i in _intents)
            if _has_side_topics:
                reply_text = result["reply"].rstrip() + "\n\n" + _pv_override
            else:
                reply_text = _pv_override
            if _pv_set_awaiting:
                flags["awaiting_booking_confirmation"] = True

    _booking_flow_on = config_loader.get_raw().get("features", {}).get("booking_flow", True)

    # Step 7: Availability pre-check + soft hold (SKIP when booking_flow is OFF)
    if (_booking_flow_on
            and flags.get("awaiting_booking_confirmation")
            and not flags.get("slot_checked")):
        _ck_svc = fields.get("service_key", "")
        _ck_deps = config_loader.get_service(_ck_svc).get("slots", []) if _ck_svc else []
        _ck_start = (fields.get("slot_time")
                     or (_ck_deps[0].get("time", "09:00") if _ck_deps else "09:00"))
        _ck_guests = int(fields.get("guests") or 1)
        avail = gws_calendar.check_availability(
            _ck_svc, fields.get("date", ""), _ck_start, _ck_guests)
        flags["slot_checked"] = True
        flags["slot_available"] = avail.get("available", False)
        flags["spots_remaining"] = avail.get("spots_remaining", 0)
        flags["trip_capacity"] = avail.get("capacity", 0)
        if avail.get("available"):
            hold_id = state_registry.create_soft_hold(
                _ck_svc,
                fields.get("date", ""),
                _ck_start,
                _ck_guests,
                avail.get("capacity", 20),
                customer_name=fields.get("customer_name", ""),
                customer_email=fields.get("email") or phone,
            )
            if hold_id is not None:
                flags["hold_id"] = hold_id
                flags["hold_service_key"] = _ck_svc
                flags["hold_date"] = fields.get("date", "")
                flags["hold_slot_time"] = _ck_start
                bm_logger.log("whatsapp_soft_hold_created", phone=phone,
                              hold_id=hold_id, service_key=_ck_svc)
            else:
                # Race: capacity was grabbed between check and insert
                flags["slot_available"] = False
                flags["awaiting_booking_confirmation"] = False
                flags["slot_checked"] = False
                _unavail_name = _pv_service.get("display_name", _ck_svc)
                reply_text = (
                    f"Unfortunately the {_unavail_name} is fully booked on that date. "
                    f"Would you like to try a different date?"
                )
                bm_logger.log("whatsapp_soft_hold_race", phone=phone, service_key=_ck_svc)
        else:
            flags["awaiting_booking_confirmation"] = False
            flags["slot_checked"] = False
            _unavail_name = _pv_service.get("display_name", _ck_svc)
            reply_text = (
                f"Unfortunately the {_unavail_name} is fully booked on that date. "
                f"Would you like to try a different date?"
            )
            bm_logger.log("whatsapp_slot_unavailable", phone=phone, service_key=_ck_svc,
                          spots=avail.get("spots_remaining", 0))

    _skip_booking = False

    # Step 7.5: Semi-escalation → create relay (operator notified via email poller)
    if result.get("semi_escalation"):
        relay_question = result.get("relay_question", "(no question captured)")
        # Cancel any soft hold (capacity leak prevention)
        if flags.get("hold_id"):
            state_registry.cancel_hold(flags["hold_id"])
            _h_svc = flags.pop("hold_service_key", "")
            _h_date = flags.pop("hold_date", "")
            _h_dep = flags.pop("hold_slot_time", "")
            flags.pop("hold_id", None)
            if _h_svc and _h_date and _h_dep:
                gws_calendar.remove_from_manifest(_h_svc, _h_date, _h_dep)
        flags["slot_checked"] = False
        flags["slot_available"] = False
        flags["awaiting_booking_confirmation"] = False
        # Set relay flags (proper relay bridge, not promote to full)
        relay_token = uuid.uuid4().hex[:12]
        flags["awaiting_relay"] = True
        flags["relay_token"] = relay_token
        flags["relay_question"] = relay_question
        reply_text = result["reply"]
        # Build relay alert for operator
        _ref = flags.get("booking_ref") or flags.get("returning_booking") or "NO-REF"
        _cname = fields.get("customer_name") or from_name or "Unknown"
        _alert_subject = f"[RELAY-{relay_token}] {_ref} - {_cname}"
        _alert_body = (
            f"Customer: {_cname} (WhatsApp: {phone})\n"
            f"Their question: {relay_question}\n\n"
            f"Booking context:\n"
            f"  Trip: {fields.get('service_key', '')} | "
            f"Date: {fields.get('date', '')} | "
            f"Guests: {fields.get('guests', '')}\n"
            f"  Ref: {_ref}\n\n"
            f"INSTRUCTIONS: Reply to this email with your answer.\n"
            f"Marina will relay it to the customer in her own words."
        )
        state_registry.create_pending_notification(
            'relay', 'whatsapp', phone, _cname,
            _alert_subject, _alert_body, relay_token=relay_token)
        sheets_writer.log_escalation({
            "email": phone,
            "subject": "WhatsApp",
            "customer_name": _cname,
            "intent": "semi_escalation",
            "fields_collected": fields,
            "internal_note": f"Relay question: {relay_question}",
            "messages_json": json.dumps(history, ensure_ascii=False) if history else "[]",
        })
        bm_logger.log("whatsapp_semi_escalation", phone=phone,
                      relay_question=relay_question, relay_token=relay_token)
        state_registry.wa_store_message(phone, "system", f"Relay question sent to team: {relay_question}")
        _skip_booking = True

    # Step 7.5: Awaiting escalation email — email provided, now fire escalation
    if flags.get("awaiting_escalation_email") and fields.get("email"):
        flags.pop("awaiting_escalation_email", None)
        flags.pop("needs_escalation_email", None)
        result["requires_human"] = True
        bm_logger.log("whatsapp_escalation_email_received", phone=phone,
                      email=fields.get("email", "")[:50])

    # Step 7.55: Needs escalation email — hold escalation, ask for email
    if not _skip_booking and result.get("flags", {}).get("needs_escalation_email"):
        flags["awaiting_escalation_email"] = True
        reply_text = result["reply"]
        _skip_booking = True

    # Step 7.6: Full escalation — requires_human, holding reply to customer
    if not _skip_booking and result.get("requires_human"):
        # Cancel any soft hold (same pattern as semi-escalation — capacity leak prevention)
        if flags.get("hold_id"):
            state_registry.cancel_hold(flags["hold_id"])
            _h_svc = flags.pop("hold_service_key", "")
            _h_date = flags.pop("hold_date", "")
            _h_dep = flags.pop("hold_slot_time", "")
            flags.pop("hold_id", None)
            if _h_svc and _h_date and _h_dep:
                gws_calendar.remove_from_manifest(_h_svc, _h_date, _h_dep)
        flags["slot_checked"] = False
        flags["slot_available"] = False
        flags["fully_escalated"] = True
        flags["awaiting_booking_confirmation"] = False
        reply_text = result["reply"]  # Claude's warm holding reply
        _cname = fields.get("customer_name") or from_name or "Unknown"
        sheets_writer.log_escalation({
            "email": phone,
            "subject": "WhatsApp",
            "customer_name": _cname,
            "intent": (result.get("intents") or ["unknown"])[0],
            "fields_collected": fields,
            "internal_note": result.get("internal_note", ""),
            "messages_json": json.dumps(history, ensure_ascii=False) if history else "[]",
        })
        bm_logger.log("whatsapp_full_escalation", phone=phone,
                      intents=result.get("intents", []))
        _esc_intent = (result.get("intents") or ["unknown"])[0]
        state_registry.wa_store_message(phone, "system", f"Escalated to human: {_esc_intent}")
        # Build escalation alert for operator
        _esc_ref = flags.get("booking_ref") or flags.get("returning_booking") or "NO-REF"
        _esc_intents = ", ".join(result.get("intents") or ["unknown"])
        _esc_history = state_registry.wa_get_history(phone, limit=20)
        _esc_chat_lines = []
        for _em in _esc_history:
            _esc_chat_lines.append(
                f"[{_em['role'].upper()} | {_em.get('created_at', '')}]")
            _esc_chat_lines.append(_em.get("text", ""))
            _esc_chat_lines.append("---")
        _esc_chat_log = "\n".join(_esc_chat_lines) or "(no messages logged)"
        _esc_note = result.get("internal_note", "").strip()
        _esc_summary = _esc_note if _esc_note else _esc_intents
        _esc_subject = (
            f"[ESCALATION] {_esc_ref} - {_cname} "
            f"(WhatsApp: {phone}) - {_esc_summary}")
        _customer_email = fields.get("email", "")
        _esc_body = (
            f"=== CUSTOMER ===\n"
            f"WhatsApp: {phone}\n"
            f"Name: {_cname}\n"
            f"Email: {_customer_email or '(not provided)'}\n\n"
            f"=== CHAT LOG ===\n{_esc_chat_log}\n\n"
            f"=== BOOKING FIELDS ===\n"
            f"{json.dumps(fields, indent=2, ensure_ascii=False)}\n\n"
            f"=== MARINA'S INTERNAL NOTE ===\n"
            f"{result.get('internal_note', '')}"
        )
        state_registry.create_pending_notification(
            'escalation', 'whatsapp', phone, _cname,
            _esc_subject, _esc_body)
        _skip_booking = True

    # Step 7.8: Booking flow toggle — if OFF, escalate booking intents instead
    if not _skip_booking and not _booking_flow_on:
        if any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
            if fields.get("service_name") or fields.get("date") or fields.get("guests"):
                _cname = fields.get("customer_name", phone)
                _customer_email = fields.get("email", "")
                _esc_msgs = state_registry.wa_get_full_history(phone, limit=20)
                _esc_chat_lines = []
                for _em in _esc_msgs:
                    _esc_chat_lines.append(
                        f"[{_em['role'].upper()} | {_em.get('created_at', '')}]")
                    _esc_chat_lines.append(_em.get("text", ""))
                    _esc_chat_lines.append("---")
                _esc_chat_log = "\n".join(_esc_chat_lines) or "(no messages logged)"
                _esc_note = result.get("internal_note", "")
                _esc_subject = (
                    f"[BOOKING REQUEST] {_cname} "
                    f"(WhatsApp: {phone}) - {_esc_note or 'wants to book'}")
                _esc_body = (
                    f"=== BOOKING REQUEST (booking_flow OFF) ===\n\n"
                    f"=== CUSTOMER ===\n"
                    f"WhatsApp: {phone}\n"
                    f"Name: {_cname}\n"
                    f"Email: {_customer_email or '(not provided)'}\n\n"
                    f"=== COLLECTED FIELDS ===\n"
                    f"{json.dumps(fields, indent=2, ensure_ascii=False)}\n\n"
                    f"=== CHAT LOG ===\n{_esc_chat_log}\n\n"
                    f"=== MARINA'S NOTE ===\n{_esc_note}"
                )
                state_registry.create_pending_notification(
                    'escalation', 'whatsapp', phone, _cname,
                    _esc_subject, _esc_body)
                bm_logger.log("booking_flow_off_escalated", phone=phone)
                _skip_booking = True

    # Step 8: Booking confirmation flow (skip if escalated)
    if not _skip_booking and any(i in _BOOKING_INTENTS for i in result.get("intents", [])):
        if (fields.get("service_name") and fields.get("date")
                and fields.get("guests") and fields.get("service_key")
                and flags.get("booking_confirmed")
                and not flags.get("hold_created")):
            bm_logger.log("whatsapp_booking_attempted", phone=phone,
                          service_key=fields.get("service_key"),
                          date=fields.get("date"), guests=fields.get("guests"))

            # Generate booking_ref + set on soft hold BEFORE manifest creation
            _chars = string.ascii_uppercase + string.digits
            booking_ref = ''.join(random.choices(_chars, k=6))
            flags["booking_ref"] = booking_ref
            if flags.get("hold_id"):
                state_registry.set_booking_ref(flags["hold_id"], booking_ref)

            res = gws_calendar.create_or_update_manifest(fields)
            if not res.get("ok"):
                _manifest_error = str(res.get("error", ""))
                _is_api_error = any(s in _manifest_error for s in (
                    '"code": 404', '"code": 500', '"code": 403', '"code": 401',
                    "'code': 404", "'code': 500", "'code': 403", "'code': 401",
                    'Calendar ID not configured'))
                bm_logger.log("whatsapp_manifest_failed", phone=phone,
                              error=_manifest_error[:200],
                              error_type="api" if _is_api_error else "business")
                if flags.get("hold_id"):
                    state_registry.cancel_hold(flags["hold_id"])
                    _h_svc = flags.pop("hold_service_key", "")
                    _h_date = flags.pop("hold_date", "")
                    _h_dep = flags.pop("hold_slot_time", "")
                    flags.pop("hold_id", None)
                    if _h_svc and _h_date and _h_dep:
                        gws_calendar.remove_from_manifest(_h_svc, _h_date, _h_dep)
                flags["slot_checked"] = False
                flags["slot_available"] = False
                if _is_api_error:
                    _retry_count = flags.get("manifest_retry_count", 0) + 1
                    flags["manifest_retry_count"] = _retry_count
                    if _retry_count >= 2:
                        _cname = fields.get("customer_name") or from_name or "Unknown"
                        state_registry.create_pending_notification(
                            'escalation', 'whatsapp', phone, _cname,
                            f"[SYSTEM] Manifest failure for {_cname} (WhatsApp: {phone})",
                            f"Booking failed {_retry_count} times due to API error.\n"
                            f"Error: {_manifest_error[:300]}\n"
                            f"Fields: {json.dumps(fields, indent=2, ensure_ascii=False)}")
                        bm_logger.log("whatsapp_manifest_escalated", phone=phone,
                                      retry_count=_retry_count)
                    flags["booking_confirmed"] = False
                    flags["awaiting_booking_confirmation"] = True
                reply_text = result.get("reply_hold_failed") or reply_text
                sheets_writer.log_hold_failed({
                    "email": phone, "subject": "WhatsApp",
                    "service_name": fields.get("service_name"),
                    "date": fields.get("date"),
                    "guests": fields.get("guests"),
                    "error": _manifest_error[:200],
                })
            else:
                flags.pop("manifest_retry_count", None)
                flags["hold_created"] = True
                if flags.get("hold_id"):
                    state_registry.confirm_hold(flags["hold_id"])
                flags["event_id"] = res.get("eventId")
                flags["event_link"] = res.get("htmlLink")
                service_key = fields.get("service_key", "")
                price_usd = (config_loader.get_service(service_key).get("price", 0)
                             if service_key else 0)
                reply_text = reply_text.replace("[BOOKING_REF]", booking_ref)

                # Payment timing: only generate link for upfront/deposit
                _payment_timing = config_loader.get_raw().get("payment", {}).get("timing", "upfront")
                if _payment_timing in ("upfront", "deposit"):
                    pay = payment_stub.generate_payment_link(booking_ref, price_usd)
                    pay_link = f"https://demo.pay/bluemarlin/{pay['payment_id']}"
                    flags["payment_id"] = pay.get("payment_id")
                    flags["payment_link"] = pay_link
                    flags["payment_status"] = pay.get("status")
                    reply_text = reply_text.replace("[PAYMENT_LINK]", pay_link)
                else:
                    reply_text = reply_text.replace("[PAYMENT_LINK]", "")
                    flags["payment_status"] = "not_required"
                bm_logger.log("whatsapp_booking_confirmed", phone=phone,
                              booking_ref=booking_ref, service_key=service_key)
                state_registry.wa_store_message(phone, "system",
                    f"Booking confirmed: {fields.get('service_name', service_key)}, {fields.get('date', '')}, {fields.get('guests', '')} guests (Ref: {booking_ref})")
                sheets_writer.log_hold_created({
                    "booking_ref": booking_ref,
                    "email": phone, "subject": "WhatsApp",
                    "customer_name": fields.get("customer_name"),
                    "service_name": fields.get("service_name"),
                    "service_key": fields.get("service_key"),
                    "date": fields.get("date"),
                    "guests": fields.get("guests"),
                    "slot_time": fields.get("slot_time"),
                    "phone": phone,
                    "special_requests": fields.get("special_requests"),
                    "total_price": int(fields.get("guests") or 0) * price_usd,
                    "html_link": flags.get("event_link"),
                    "payment_link": flags.get("payment_link"),
                    "payment_status": flags.get("payment_status", ""),
                })
                # Log manifest summary to Sheets
                _m_passengers = state_registry.get_slot_passengers(
                    service_key, fields.get("date", ""), fields.get("slot_time", ""))
                _m_confirmed = sum(1 for p in _m_passengers if p["status"] == "confirmed")
                _m_pending = sum(1 for p in _m_passengers if p["status"] == "soft_hold")
                _m_total_guests = sum(p["guests"] for p in _m_passengers)
                _m_total_revenue = _m_total_guests * price_usd
                _m_capacity = config_loader.get_service(service_key).get("capacity", 20)
                sheets_writer.log_manifest_update({
                    "service_key": service_key,
                    "date": fields.get("date", ""),
                    "slot_time": fields.get("slot_time", ""),
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
                    customer_email=fields.get("email") or phone,
                )

                # Large group notification — operator review after auto-confirm
                _lg_threshold = config_loader.get_booking_rules().get("group_threshold_requires_human", 15)
                _lg_guests = int(fields.get("guests", 0) or 0)
                if _lg_guests >= _lg_threshold:
                    _lg_ref = flags.get("booking_ref", "NO-REF")
                    _lg_name = fields.get("customer_name", "Unknown")
                    _lg_note = (f"Large group booking: {_lg_guests} guests for "
                                f"{fields.get('service_name', '?')} on {fields.get('date', '?')}. "
                                f"Ref: {_lg_ref}. Auto-confirmed — operator review recommended.")
                    state_registry.create_pending_notification(
                        'escalation', 'whatsapp', phone, _lg_name,
                        f"[LARGE GROUP] {_lg_ref} - {_lg_name} (WhatsApp: {phone}) - {_lg_note}",
                        (f"=== LARGE GROUP BOOKING ===\n"
                         f"Ref: {_lg_ref}\nGuests: {_lg_guests}\n"
                         f"Trip: {fields.get('service_name', '?')}\n"
                         f"Date: {fields.get('date', '?')}\n"
                         f"Customer: {_lg_name}\nPhone: {phone}\n"
                         f"Email: {fields.get('email', 'not provided')}\n\n"
                         f"This booking was auto-confirmed. Review and adjust if needed."))
                    state_registry.wa_store_message(phone, "system",
                        f"Large group booking ({_lg_guests} guests) — operator notified for review")
                    bm_logger.log("large_group_booking", phone=phone,
                                  guests=str(_lg_guests), booking_ref=_lg_ref)

    # Step 9: Strip remaining placeholders (safety net)
    reply_text = reply_text.replace("[BOOKING_REF]", "").replace("[PAYMENT_LINK]", "")

    # Record reply timestamp for anti-loop tracking
    if reply_text:
        _reply_times = flags.get("reply_times", [])
        _reply_times.append(int(time.time()))
        flags["reply_times"] = _reply_times

    # Persist state + log
    state_registry.wa_save_booking_state(phone, fields, flags, completed_bookings)
    bm_logger.log("whatsapp_agent_reply", phone=phone,
                  intents=result.get("intents", []), reply_length=len(reply_text))

    return reply_text
